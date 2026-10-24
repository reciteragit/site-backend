from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Sum
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied,NotFound
from academy.views import AcademyView,AcademyWriteThrottle
from catalog.models import Course
from .models import Episode,CourseBundle,Enrollment,EpisodeProgress,vimeo_embed
from .services import has_access,can_watch,purchase_courses


def progress_data(progress):
    return {'position_seconds':progress.position_seconds,'duration_seconds':progress.duration_seconds,'watched_seconds':progress.watched_seconds,'completed':progress.completed} if progress else {'position_seconds':0,'duration_seconds':0,'watched_seconds':0,'completed':False}


def course_data(course,user,details=False):
    owned=has_access(user,course)
    episodes=list(course.episodes.filter(published=True))
    progress={row.episode_id:row for row in EpisodeProgress.objects.filter(user=user,episode__in=episodes)} if user.is_authenticated else {}
    completed=sum(bool(progress.get(ep.pk) and progress[ep.pk].completed) for ep in episodes)
    unfinished=[p for p in progress.values() if not p.completed and p.position_seconds>0]
    resume=max(unfinished,key=lambda p:p.updated_at).episode_id if unfinished else next((ep.pk for ep in episodes if not (progress.get(ep.pk) and progress[ep.pk].completed)),episodes[0].pk if episodes else None)
    result={'slug':course.slug,'title':course.title,'description':course.description,'teacher':course.teacher.name,'image':course.image or '/assets/self-paced.png','price':str(course.price),'currency':course.currency,'owned':owned,'resume_episode_id':resume,'episode_count':len(episodes),'completed_count':completed,'progress_percent':round(completed/len(episodes)*100) if episodes else 0,'watched_seconds':sum(p.watched_seconds for p in progress.values()),'ready':bool(episodes)}
    if details:
        result['episodes']=[{'id':ep.pk,'title':ep.title,'description':ep.description,'duration_seconds':ep.duration_seconds,'free':ep.is_free or course.price==0,'accessible':owned or ep.is_free or course.price==0,'completed':bool(progress.get(ep.pk) and progress[ep.pk].completed)} for ep in episodes]
    return result


def bundle_data(bundle):
    return {'slug':bundle.slug,'title':bundle.title,'description':bundle.description,'image':bundle.image or '/assets/self-paced.png','base_price':f'{bundle.base_price:.2f}','price':f'{bundle.price:.2f}','currency':'CAD','discount_percent':str(bundle.discount_percent),'courses':[{'slug':course.slug,'title':course.title,'price':str(course.price)} for course in bundle.courses.all()]}


class Courses(AcademyView):
    permission_classes=[AllowAny]
    def get(self,request,slug=None):
        if slug:
            course=get_object_or_404(Course.objects.select_related('teacher'),slug=slug,delivery_mode='platform')
            if (not course.published or not course.teacher.published) and not has_access(request.user,course):raise NotFound()
            return Response(course_data(course,request.user,True),headers={'Cache-Control':'private, no-store'})
        rows=Course.objects.filter(delivery_mode='platform',published=True,teacher__published=True).select_related('teacher')
        return Response([course_data(c,request.user) for c in rows],headers={'Cache-Control':'private, no-store'})


class Bundles(AcademyView):
    permission_classes=[AllowAny]
    def get(self,request,slug=None):
        rows=CourseBundle.objects.filter(published=True).prefetch_related('courses')
        if slug:return Response(bundle_data(get_object_or_404(rows,slug=slug)))
        return Response([bundle_data(b) for b in rows])


class FreeEnroll(AcademyView):
    throttle_classes=[AcademyWriteThrottle]
    def post(self,request,slug,kind='course'):
        courses=purchase_courses(kind,slug)
        if kind=='course':price=courses[0].price
        else:price=get_object_or_404(CourseBundle,slug=slug,published=True).price
        if price!=0:raise PermissionDenied('Purchase this course or package to unlock its paid episodes.')
        with transaction.atomic():
            for course in courses:
                enrollment,_=Enrollment.objects.get_or_create(user=request.user,course=course)
                if not enrollment.active:raise PermissionDenied('Your course access is inactive. Contact Recitera.')
        return Response({'enrolled':True,'courses':[c.slug for c in courses]})


class Library(AcademyView):
    def get(self,request):
        rows=Enrollment.objects.filter(user=request.user,active=True).select_related('course__teacher').order_by('-enrolled_at')
        return Response([course_data(row.course,request.user,True) for row in rows],headers={'Cache-Control':'private, no-store'})


class Video(AcademyView):
    permission_classes=[AllowAny]
    def get(self,request,episode_id):
        episode=get_object_or_404(Episode.objects.select_related('course__teacher'),pk=episode_id)
        if not can_watch(request.user,episode):raise PermissionDenied('Enrol in this course to watch this episode.')
        progress=EpisodeProgress.objects.filter(user=request.user,episode=episode).first() if request.user.is_authenticated else None
        return Response({'id':episode.pk,'title':episode.title,'description':episode.description,'provider':episode.video_provider,'playback_url':vimeo_embed(episode.video_url) if episode.video_provider=='vimeo' else episode.video_url,'duration_seconds':episode.duration_seconds,'progress':progress_data(progress)},headers={'Cache-Control':'private, no-store'})


class Progress(AcademyView):
    throttle_classes=[AcademyWriteThrottle]
    def post(self,request,episode_id):
        class Input(serializers.Serializer):
            position_seconds=serializers.IntegerField(min_value=0,max_value=86400)
            duration_seconds=serializers.IntegerField(min_value=0,max_value=86400,default=0)
            watched_delta=serializers.IntegerField(min_value=0,max_value=20,default=0)
            completed=serializers.BooleanField(default=False)
        s=Input(data=request.data);s.is_valid(raise_exception=True);data=s.validated_data
        episode=get_object_or_404(Episode.objects.select_related('course__teacher'),pk=episode_id)
        if not can_watch(request.user,episode):raise PermissionDenied('You do not have access to this episode.')
        with transaction.atomic():
            row,created=EpisodeProgress.objects.get_or_create(user=request.user,episode=episode)
            row=EpisodeProgress.objects.select_for_update().get(pk=row.pk)
            duration=episode.duration_seconds or data['duration_seconds'] or row.duration_seconds
            position=min(data['position_seconds'],duration) if duration else data['position_seconds']
            elapsed=20 if created else max(0,min(20,int((timezone.now()-row.updated_at).total_seconds())+2))
            row.watched_seconds+=min(data['watched_delta'],elapsed)
            row.position_seconds=position;row.duration_seconds=duration
            row.completed=row.completed or data['completed'] or bool(duration and position>=duration*.95)
            row.save()
        return Response(progress_data(row),headers={'Cache-Control':'private, no-store'})
