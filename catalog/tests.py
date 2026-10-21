from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, SimpleTestCase
from rest_framework.test import APIClient
from .models import Teacher, Course
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from config.database import database_settings
from unittest.mock import patch
import os

class DatabaseConfigurationTests(SimpleTestCase):
    def test_vercel_integration_connection_and_ssl(self):
        db = database_settings({"POSTGRES_URL": "postgresql://localhost/recitera"}, Path("/tmp"), False)["default"]
        self.assertEqual(db["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(db["OPTIONS"]["sslmode"], "require")
        self.assertEqual(db["CONN_MAX_AGE"], 0)
        self.assertTrue(db["DISABLE_SERVER_SIDE_CURSORS"])
        self.assertIsNone(db["OPTIONS"]["prepare_threshold"])

    def test_supabase_metadata_removed_without_disabling_tls(self):
        db = database_settings({"POSTGRES_URL": "postgresql://localhost/recitera?supa=client-metadata&sslmode=require&connect_timeout=10"}, Path("/tmp"), False)["default"]
        self.assertNotIn("supa", db["OPTIONS"])
        self.assertEqual(db["OPTIONS"]["sslmode"], "require")
        self.assertEqual(str(db["OPTIONS"]["connect_timeout"]), "10")

    def test_explicit_connection_has_priority(self):
        db = database_settings({"DATABASE_URL": "postgresql://localhost/explicit", "POSTGRES_URL": "postgresql://localhost/integration"}, Path("/tmp"), False)["default"]
        self.assertEqual(db["NAME"], "explicit")

    def test_production_rejects_missing_or_non_postgres_database(self):
        for environ in [{}, {"DATABASE_URL": "sqlite:////tmp/not-production.sqlite3", "DATABASE_SSL_REQUIRED": "false"}]:
            with self.assertRaises(ImproperlyConfigured):
                database_settings(environ, Path("/tmp"), False)

class CatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", verbosity=0)

    def test_seed_is_repeatable_and_preserves_admin_edits(self):
        teacher = Teacher.objects.first()
        teacher.name = "Edited in admin"
        teacher.save()
        call_command("seed_catalog", verbosity=0)
        teacher.refresh_from_db()
        self.assertEqual(teacher.name, "Edited in admin")
        self.assertEqual(Teacher.objects.count(), 11)
        self.assertEqual(Course.objects.count(), 12)

    def test_admin_bootstrap_is_idempotent(self):
        password = "local-test-password-only-for-bootstrap-2026"
        with patch.dict(os.environ, {"DJANGO_SUPERUSER_USERNAME": "bootstrap-test", "DJANGO_SUPERUSER_PASSWORD": password}):
            call_command("bootstrap_admin", verbosity=0)
            call_command("bootstrap_admin", verbosity=0)
        user = get_user_model().objects.get(username="bootstrap-test")
        self.assertTrue(user.is_superuser and user.is_staff)
        self.assertTrue(user.check_password(password))
        self.assertEqual(get_user_model().objects.filter(username="bootstrap-test").count(), 1)

    def test_public_catalog_and_detail(self):
        response = self.client.get("/api/teachers/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 11)
        response = self.client.get("/api/courses/")
        self.assertEqual(len(response.json()), 12)
        self.assertEqual(response.json()[0]["price"], "0.00")
        self.assertEqual(self.client.get("/api/teachers/mohammed-atalla/").status_code, 200)
        self.assertEqual(self.client.get("/api/teachers/missing/").status_code, 404)

    def test_unpublished_content_not_exposed(self):
        teacher = Teacher.objects.get(slug="mohammed-atalla")
        teacher.published = False
        teacher.save()
        self.assertEqual(len(self.client.get("/api/teachers/").json()), 10)
        self.assertEqual(self.client.get("/api/courses/").json(), [])
        self.assertEqual(self.client.get("/api/teachers/mohammed-atalla/").status_code, 404)

    def test_public_cannot_write(self):
        client = APIClient()
        self.assertEqual(client.post("/api/teachers/", {"name": "Unauthorized"}, format="json").status_code, 405)
        self.assertEqual(client.delete("/api/courses/surah-al-ikhlas-step-by-step/").status_code, 405)

    def test_health_and_admin(self):
        self.assertEqual(self.client.get("/api/health/").json()["status"], "ok")
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        user = get_user_model().objects.create_superuser("admin-test", "admin@example.com", "test-only-password")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/admin/catalog/teacher/").status_code, 200)
        self.assertEqual(self.client.get("/admin/catalog/course/").status_code, 200)

    def test_admin_can_edit_live_catalog(self):
        user = get_user_model().objects.create_superuser("editor", "editor@example.com", "test-only-password")
        self.client.force_login(user)
        teacher = Teacher.objects.get(slug="mohammed-atalla")
        response = self.client.post(f"/admin/catalog/teacher/{teacher.pk}/change/", {
            "slug": teacher.slug, "name": "Updated teacher", "experience": teacher.experience,
            "languages": '["Arabic", "English"]', "image": teacher.image,
            "profile_url": teacher.profile_url, "price": "35.00", "currency": "CAD",
            "sort_order": teacher.sort_order, "published": "on", "_save": "Save",
        })
        self.assertEqual(response.status_code, 302)
        data = self.client.get("/api/teachers/mohammed-atalla/").json()
        self.assertEqual(data["name"], "Updated teacher")
        self.assertEqual(data["price"], "35.00")
        self.assertEqual(data["languages"], ["Arabic", "English"])
