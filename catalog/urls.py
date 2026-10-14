from rest_framework.routers import DefaultRouter
from .views import TeacherViewSet, CourseViewSet
from django.urls import path
from .forms import VolunteerRegistration, NewsletterRegistration
from .teacher_forms import TeacherRegistration
from .payments import Checkout, PaymentStatus, PaymentConfiguration, PaymentItemDetails, stripe_webhook
router = DefaultRouter()
router.register("teachers", TeacherViewSet)
router.register("courses", CourseViewSet)
urlpatterns = [path('payments/items/<str:purpose>/<slug:reference>/',PaymentItemDetails.as_view()),path('payments/config/',PaymentConfiguration.as_view()),path('payments/checkout/',Checkout.as_view()),path('payments/status/<uuid:order_id>/',PaymentStatus.as_view()),path('payments/stripe/webhook/',stripe_webhook),path('forms/teacher/', TeacherRegistration.as_view()), path('forms/volunteer/', VolunteerRegistration.as_view()), path('forms/newsletter/', NewsletterRegistration.as_view())] + router.urls

