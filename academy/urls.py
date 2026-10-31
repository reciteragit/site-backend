from crm.views import TeacherTrialReport,StudentTrialFeedback,ClaimTrialRequest
from django.urls import path, include
from . import views
from .account_finance import AccountFinance
from .cancellations import Cancellation, CancellationDecision
from .google_auth import GoogleConfiguration, GoogleStart, GoogleComplete
urlpatterns=[path("crm/claim-trial/",ClaimTrialRequest.as_view()),path("teacher/bookings/<uuid:booking_id>/trial-report/",TeacherTrialReport.as_view()),path("bookings/<uuid:booking_id>/feedback/",StudentTrialFeedback.as_view()),path("bookings/<uuid:booking_id>/cancellation/",Cancellation.as_view()),path("teacher/bookings/<uuid:booking_id>/cancellation/",CancellationDecision.as_view()),path("account/finance/",AccountFinance.as_view()),path("learning/",include("learning.urls")),path('auth/google/config/',GoogleConfiguration.as_view()),path('auth/google/start/',GoogleStart.as_view()),path('auth/google/complete/',GoogleComplete.as_view()),path('notifications/retry/',views.MailRetry.as_view()),path('internal/send-mail/',views.ScheduledMail.as_view()),
    path('auth/register/',views.Register.as_view()),path('auth/login/',views.Login.as_view()),path('auth/logout/',views.Logout.as_view()),path('auth/password/',views.Password.as_view()),
    path('me/',views.Me.as_view()),path('teachers/<slug:slug>/',views.PublicTeacher.as_view()),path('teachers/<slug:slug>/availability/',views.PublicDates.as_view()),path('teachers/<slug:slug>/slots/',views.PublicSlots.as_view()),
    path('teacher/availability/',views.MyAvailability.as_view()),path('teacher/profile/',views.MyTeacher.as_view()),path('teacher/slots/',views.MySlots.as_view()),path('teacher/bookings/',views.TeachingBookings.as_view()),
    path('cart/',views.Cart.as_view()),path('cart/quote/',views.CartQuote.as_view()),path('checkout/',views.Checkout.as_view()),path('bookings/',views.MyBookings.as_view()),path('bookings/<uuid:booking_id>/calendar/',views.BookingCalendar.as_view()),
]
