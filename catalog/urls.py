from rest_framework.routers import DefaultRouter
from .views import TeacherViewSet, CourseViewSet
from django.urls import path
from .forms import VolunteerRegistration, NewsletterRegistration
router = DefaultRouter()
router.register("teachers", TeacherViewSet)
router.register("courses", CourseViewSet)
urlpatterns = [path('forms/volunteer/', VolunteerRegistration.as_view()), path('forms/newsletter/', NewsletterRegistration.as_view())] + router.urls

