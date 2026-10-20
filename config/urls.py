from django.contrib import admin
from django.urls import include, path
from catalog.views import health
admin.site.site_header = "Recitera Administration"
admin.site.site_title = "Recitera Admin"
admin.site.index_title = "Manage teachers and recorded courses"
urlpatterns = [path("api/academy/", include("academy.urls")), path("admin/", admin.site.urls), path("api/health/", health), path("api/", include("catalog.urls"))]
