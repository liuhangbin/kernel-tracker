"""Container-local settings for kernel-tracker.

Every value is read from an environment variable, which is how
compose_example.yaml configures the container; nothing needs to be edited
in this file. The defaults are the paths used inside the image, all of
them inside the /data volume.
"""

import os
import warnings
import zoneinfo

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "container-dev-key-change-in-production"
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# Comma-separated, scheme included, e.g.
# http://localhost:8080,https://tracker.example.com
CSRF_TRUSTED_ORIGINS = [
    origin
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin
]

# Administrator created by `manage ensure_admin` when none exists yet. With
# no ADMIN_PASSWORD, a random one is generated and written to the log.
ADMIN_NAME = os.environ.get("ADMIN_NAME", "admin")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

VERSION = os.environ.get("KERNEL_TRACKER_VERSION", "container")

# %__version__%

# Zone used for every displayed timestamp and for the update schedule, taken
# from the standard TZ variable (glibc honours it too, so the container clock
# and its logs agree with the schedule). An unknown name would raise inside
# Django and stop the container from starting, hence the check.
_TZ = os.environ.get("TZ", "UTC")
try:
    zoneinfo.ZoneInfo(_TZ)
    TIME_ZONE = _TZ
except (KeyError, ValueError):
    warnings.warn(f"unknown TZ '{_TZ}', falling back to UTC", stacklevel=2)
    TIME_ZONE = "UTC"

GIT_REPO = os.environ.get("GIT_REPO", "/data/data.git")

PYGIT_WORKAROUNDS = os.environ.get("PYGIT_WORKAROUNDS", "1") == "1"

PROCESSING_LOCK_FILE = os.environ.get("PROCESSING_LOCK_FILE", "/data/tmp/processing.lock")

STATIC_DIR = os.environ.get("STATIC_DIR", "/data/static")

# SQLite is used unless the MARIADB_* variables are set (compose_example.yaml).
if not os.environ.get("MARIADB_HOST"):
    DBLITE = os.environ.get("DBLITE", "/data/db.sqlite3")

DBNAME = os.environ.get("MARIADB_DATABASE", "kernel_tracker")
DBUSER = os.environ.get("MARIADB_USER", "kernel_tracker")
DBPASSWD = os.environ.get("MARIADB_PASSWORD", "kernel_tracker")
DBHOST = os.environ.get("MARIADB_HOST", "")
DBPORT = os.environ.get("MARIADB_PORT", "")
