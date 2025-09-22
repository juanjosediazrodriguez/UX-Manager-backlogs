import os
import re

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse, resolve


def test_settings_core():
    assert settings.ROOT_URLCONF == "uxmanager.urls"
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in settings.MIDDLEWARE
    assert "django_htmx" in settings.INSTALLED_APPS
    assert "allauth" in settings.INSTALLED_APPS


def test_urls_and_homepage_renders(client: Client):
    # allauth included
    assert resolve("/accounts/login/")
    resp = client.get("/")
    assert resp.status_code == 200
    # Tailwind CDN presence and accessible landmark
    content = resp.content.decode("utf-8")
    assert "cdn.tailwindcss.com" in content
    assert re.search(r"role=\"main\"", content)


def test_db_engine_for_tests_sqlite():
    # We force SQLite in tests for speed and portability
    assert settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")


@pytest.mark.django_db
def test_migrations_apply():
    # Smoke test creating a user using auth models
    from django.contrib.auth import get_user_model

    User = get_user_model()
    u = User.objects.create_user(email="test@example.com", username="test", password="Passw0rd!")
    assert u.pk is not None

