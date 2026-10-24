from django.urls import path
from . import views
urlpatterns=[path('courses/',views.Courses.as_view()),path('courses/<slug:slug>/',views.Courses.as_view()),path('courses/<slug:slug>/enroll/',views.FreeEnroll.as_view()),path('bundles/',views.Bundles.as_view()),path('bundles/<slug:slug>/',views.Bundles.as_view()),path('bundles/<slug:slug>/enroll/',views.FreeEnroll.as_view(),{'kind':'bundle'}),path('library/',views.Library.as_view()),path('episodes/<int:episode_id>/',views.Video.as_view()),path('episodes/<int:episode_id>/progress/',views.Progress.as_view())]
