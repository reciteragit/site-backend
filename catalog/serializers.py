from rest_framework import serializers
from .models import Teacher, Course

class TeacherSerializer(serializers.ModelSerializer):
    class Meta:
        model = Teacher
        fields = ("slug", "name", "biography", "based_in", "specialities", "experience", "languages", "image", "profile_url", "price", "currency", "sort_order")

class CourseSerializer(serializers.ModelSerializer):
    course_url=serializers.SerializerMethodField()
    def get_course_url(self,obj):return f"/courses/{obj.slug}" if obj.delivery_mode=="platform" else obj.course_url
    teacher_slug = serializers.SlugRelatedField(source="teacher", slug_field="slug", read_only=True)
    teacher_name = serializers.CharField(source="teacher.name", read_only=True)
    teacher_image = serializers.CharField(source="teacher.image", read_only=True)
    class Meta:
        model = Course
        fields = ("slug", "title", "description", "delivery_mode", "teacher_slug", "teacher_name", "teacher_image", "course_url", "price", "currency", "sort_order")
