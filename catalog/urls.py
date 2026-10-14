from rest_framework.routers import DefaultRouter
from .views import TeacherViewSet, CourseViewSet
router = DefaultRouter()
router.register("teachers", TeacherViewSet)
router.register("courses", CourseViewSet)
urlpatterns = router.urls
