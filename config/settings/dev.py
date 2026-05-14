"""Local development settings."""

from .base import *  # noqa: F403
from .base import BASE_DIR, env

DEBUG = True

# Insecure key is fine for local dev; prod requires a real one from the env.
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="django-insecure-dev-key-not-for-production",
)

ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
