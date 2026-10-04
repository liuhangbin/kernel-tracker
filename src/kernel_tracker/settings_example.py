"""Example local settings for kernel-tracker.

Copy this file to settings_local.py and adjust as needed.
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = "change-me-to-a-real-secret-key"

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Set to show version in footer, etc.
VERSION = "unreleased"

# Path to the git repository used for fetching trees.
# Leave empty to use <BASE_DIR>/data.git
GIT_REPO = ""

# Set to True to use external git commands instead of pygit2 for some
# operations. Works around some pygit2/libgit2 limitations.
PYGIT_WORKAROUNDS = True

# Path for the processing lock file
PROCESSING_LOCK_FILE = os.path.join(BASE_DIR, "_processing.lock")

# Administrator created by `manage ensure_admin` when none exists yet. With
# no ADMIN_PASSWORD, a random one is generated and printed to stdout.
# ADMIN_NAME = "admin"
# ADMIN_EMAIL = ""
# ADMIN_PASSWORD = ""

# For local development with SQLite:
DBLITE = os.path.join(BASE_DIR, "db.sqlite3")

# For MariaDB (used in production / containers). The container reads these
# from the MARIADB_* variables set in compose_example.yaml:
# DBNAME = "kernel_tracker"
# DBUSER = "kernel_tracker"
# DBPASSWD = "kernel_tracker"
# DBHOST = ""
# DBPORT = ""

# Static files directory
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Zone used for displayed timestamps and for the update schedule. The container
# reads TZ from the environment instead, see contrib/settings_local.py.
TIME_ZONE = "UTC"
