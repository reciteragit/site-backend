from django.db import connection, DatabaseError
from django.http import JsonResponse
from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ReadOnlyModelViewSet
from .models import Teacher, Course, VolunteerApplication, NewsletterSubscriber, TeacherApplication, TeacherAttachment
from .payment_models import PaymentOrder,StripeSettings
from .serializers import TeacherSerializer, CourseSerializer

class TeacherViewSet(ReadOnlyModelViewSet):
    queryset = Teacher.objects.filter(published=True)
    serializer_class = TeacherSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = "slug"

class CourseViewSet(ReadOnlyModelViewSet):
    queryset = Course.objects.filter(published=True, teacher__published=True).select_related("teacher")
    serializer_class = CourseSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = "slug"

def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        # A connection alone does not demonstrate completed migrations.
        Teacher.objects.exists()
        Course.objects.exists()
        VolunteerApplication.objects.exists()
        NewsletterSubscriber.objects.exists()
        TeacherApplication.objects.exists()
        TeacherAttachment.objects.exists()
        PaymentOrder.objects.exists()
        StripeSettings.objects.exists()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "database": connection.vendor})

