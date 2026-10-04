"""Django settings for kernel-tracker."""

import os
from typing import Any

try:
    import kernel_tracker.settings_local as sl
except ImportError:
    import kernel_tracker.settings_example as sl

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = sl.SECRET_KEY
DEBUG = sl.DEBUG
if not DEBUG:
    ALLOWED_HOSTS = sl.ALLOWED_HOSTS
else:
    ALLOWED_HOSTS = ["*"]

# Origins accepted by the CSRF check even when they differ from the Host
# header, for example behind a proxy that rewrites it or terminates TLS.
CSRF_TRUSTED_ORIGINS = getattr(sl, "CSRF_TRUSTED_ORIGINS", [])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_prometheus",
    "kernel_tracker",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "kernel_tracker.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "kernel_tracker.context_processors.version_processor",
            ],
        },
    },
]

WSGI_APPLICATION = "kernel_tracker.wsgi.application"

DATABASES: dict[str, dict[str, Any]]

if hasattr(sl, "DBLITE"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.path.join(BASE_DIR, sl.DBLITE),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": sl.DBNAME,
            "USER": sl.DBUSER,
            "PASSWORD": sl.DBPASSWD,
            "HOST": getattr(sl, "DBHOST", ""),
            "PORT": getattr(sl, "DBPORT", ""),
            "OPTIONS": {
                "init_command": "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED",
            },
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

LOGGING = getattr(sl, "LOGGING", "")
if not LOGGING:
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "console": {
                "level": "DEBUG",
                "class": "logging.StreamHandler",
            },
        },
        "loggers": {
            "django.request": {
                "level": "DEBUG",
                "handlers": ["console"],
                "propagate": True,
            },
        },
    }

LANGUAGE_CODE = "en-us"
# Storage stays UTC (USE_TZ); this is the zone timestamps are displayed in and
# the update schedule is read in. The container takes it from TZ.
TIME_ZONE = getattr(sl, "TIME_ZONE", "UTC")
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = getattr(sl, "STATIC_DIR", os.path.join(BASE_DIR, "static"))

# kernel-tracker specific settings

GIT_REPO = getattr(sl, "GIT_REPO", "")
if not GIT_REPO:
    GIT_REPO = os.path.join(BASE_DIR, "data.git")

PYGIT_WORKAROUNDS = getattr(sl, "PYGIT_WORKAROUNDS", True)

PROCESSING_LOCK_FILE = getattr(
    sl, "PROCESSING_LOCK_FILE", os.path.join(BASE_DIR, "_processing.lock")
)

# Administrator created by the ensure_admin command when none exists yet.
ADMIN_NAME = getattr(sl, "ADMIN_NAME", "admin")
ADMIN_EMAIL = getattr(sl, "ADMIN_EMAIL", "")
ADMIN_PASSWORD = getattr(sl, "ADMIN_PASSWORD", "")

VERSION = getattr(sl, "VERSION", "unreleased")
