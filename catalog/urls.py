from rest_framework.routers import DefaultRouter
from .views import TeacherViewSet, CourseViewSet
from django.urls import path
from .forms import VolunteerRegistration, NewsletterRegistration
from .teacher_forms import TeacherRegistration
router = DefaultRouter()
router.register("teachers", TeacherViewSet)
router.register("courses", CourseViewSet)
urlpatterns = [path('forms/teacher/', TeacherRegistration.as_view()), path('forms/volunteer/', VolunteerRegistration.as_view()), path('forms/newsletter/', NewsletterRegistration.as_view())] + router.urls

