from decimal import Decimal, ROUND_HALF_UP
import ipaddress
from urllib.parse import urlsplit, parse_qs, urlencode
import re
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


def vimeo_embed(value):
    try:
        url=urlsplit(value)
        if url.scheme!='https' or url.hostname not in ['vimeo.com','www.vimeo.com','player.vimeo.com'] or url.username or url.password or url.port not in [None,443]:raise ValueError()
        pattern=r'^/video/(\d+)/?$' if url.hostname=='player.vimeo.com' else r'^/(\d+)(?:/([A-Za-z0-9]+))?/?$'
        match=re.fullmatch(pattern,url.path)
        if not match:raise ValueError()
        token=parse_qs(url.query).get('h',[''])[0] or (match.group(2) if url.hostname!='player.vimeo.com' and match.lastindex==2 else '')
        if token and not re.fullmatch(r'[A-Za-z0-9]+',token):raise ValueError()
        query={'dnt':'1','title':'0','byline':'0','portrait':'0','api':'1'}
        if token:query['h']=token
        return f'https://player.vimeo.com/video/{match.group(1)}?'+urlencode(query)
    except (ValueError,TypeError):raise ValidationError('Enter an HTTPS Vimeo video link, including the privacy hash for an unlisted video.')


def validate_video_url(value):
    try:
        url=urlsplit(value)
        if url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError()
        if url.hostname.lower()=='localhost' or url.hostname.lower().endswith(('.localhost','.local')):raise ValueError()
        try:
            if not ipaddress.ip_address(url.hostname).is_global:raise ValueError()
        except ValueError as exc:
            if ':' in url.hostname or re.fullmatch(r'[0-9.]+',url.hostname):raise exc
        if url.port is not None and not 1<=url.port<=65535:raise ValueError()
    except (ValueError,TypeError):raise ValidationError('Enter a public HTTPS video URL without embedded usernames or passwords.')


class Episode(models.Model):
    course=models.ForeignKey('catalog.Course',on_delete=models.CASCADE,related_name='episodes')
    title=models.CharField(max_length=200)
    description=models.TextField(blank=True)
    video_provider=models.CharField(max_length=10,choices=[('vimeo','Vimeo'),('direct','Direct video / other host')],default='vimeo')
    video_url=models.URLField(max_length=2000,validators=[validate_video_url],help_text='Vimeo video link (including its unlisted hash), or a direct HTTPS MP4/WebM video URL from your own host, CDN or storage. Enter a media URL, not a web page or iframe HTML.')
    duration_seconds=models.PositiveIntegerField(default=0,validators=[MaxValueValidator(86400)],help_text='Optional duration in seconds. Zero uses the Vimeo player duration for learner progress.')
    is_free=models.BooleanField(default=False,help_text='Allow this episode as a free preview in a paid course. All episodes are accessible when the course price is zero.')
    published=models.BooleanField(default=True)
    sort_order=models.PositiveIntegerField(default=0)
    class Meta:ordering=['sort_order','id']
    def clean(self):
        super().clean()
        if self.video_provider=='vimeo' and self.video_url:vimeo_embed(self.video_url)
    def __str__(self):return self.title


class CourseBundle(models.Model):
    title=models.CharField(max_length=200)
    slug=models.SlugField(unique=True)
    description=models.TextField(blank=True)
    image=models.CharField(max_length=500,blank=True,help_text='Optional /assets/ path or HTTPS cover image.')
    courses=models.ManyToManyField('catalog.Course',related_name='bundles')
    discount_percent=models.DecimalField(max_digits=5,decimal_places=2,default=0,validators=[MinValueValidator(0),MaxValueValidator(100)],help_text='Package discount off the combined course prices, from 0 to 100%.')
    published=models.BooleanField(default=False)
    sort_order=models.PositiveIntegerField(default=0)
    class Meta:ordering=['sort_order','id']
    @property
    def base_price(self):return sum((course.price for course in self.courses.all()),Decimal('0.00'))
    @property
    def price(self):return (self.base_price*(100-self.discount_percent)/100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    def __str__(self):return self.title


class CoursePurchase(models.Model):
    order=models.ForeignKey('catalog.PaymentOrder',on_delete=models.PROTECT,related_name='course_lines')
    course=models.ForeignKey('catalog.Course',on_delete=models.PROTECT)
    class Meta:constraints=[models.UniqueConstraint(fields=['order','course'],name='learning_unique_order_course')]
    def __str__(self):return self.course.title


class Enrollment(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='course_enrollments')
    course=models.ForeignKey('catalog.Course',on_delete=models.PROTECT,related_name='enrollments')
    source_order=models.ForeignKey('catalog.PaymentOrder',null=True,blank=True,on_delete=models.PROTECT)
    active=models.BooleanField(default=True)
    enrolled_at=models.DateTimeField(auto_now_add=True)
    class Meta:constraints=[models.UniqueConstraint(fields=['user','course'],name='learning_unique_user_course')]
    def __str__(self):return f'{self.user} · {self.course}'


class EpisodeProgress(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='episode_progress')
    episode=models.ForeignKey(Episode,on_delete=models.CASCADE,related_name='learner_progress')
    position_seconds=models.PositiveIntegerField(default=0)
    duration_seconds=models.PositiveIntegerField(default=0)
    watched_seconds=models.PositiveIntegerField(default=0)
    completed=models.BooleanField(default=False)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:constraints=[models.UniqueConstraint(fields=['user','episode'],name='learning_unique_user_episode')]
    def __str__(self):return f'{self.user} · {self.episode}'
