"""Production settings. All secrets and host config come from the environment."""

from pathlib import Path

from .base import *  # noqa: F403
from .base import BASE_DIR, env

DEBUG = False

# Required, no fallback. The app must not boot without these.
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(env("DJANGO_DB_PATH", default=str(BASE_DIR / "db.sqlite3"))),
    }
}

# Static files are collected here and served directly by Caddy.
STATIC_ROOT = BASE_DIR / "staticfiles"

# Caddy terminates TLS and forwards over plain HTTP on the loopback.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Trust the configured hosts for CSRF over HTTPS.
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS if host not in ("*",)]
