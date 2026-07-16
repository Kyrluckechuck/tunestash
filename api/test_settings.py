"""Test-specific Django settings that use PostgreSQL for production parity."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "django-insecure-ci-testing-key")
os.environ.setdefault("DJANGO_DEBUG", "true")

from settings import *  # noqa: E402,F401,F403
from settings import settings as dynaconf_settings  # noqa: E402

# Provide dummy Spotify credentials for tests
# These allow the Spotipy client to initialize without raising SpotifyOauthError
# Actual API calls should be mocked in tests
# Note: We use dynaconf's set() method to override values loaded from config files
# Simple module-level assignment doesn't work because dynaconf wraps the settings
SPOTIPY_CLIENT_ID = "test_client_id_for_ci_tests"
SPOTIPY_CLIENT_SECRET = "test_client_secret_for_ci_tests"

# Force dynaconf to use our test values (overrides /config/settings.yaml)
dynaconf_settings.set("SPOTIPY_CLIENT_ID", SPOTIPY_CLIENT_ID)
dynaconf_settings.set("SPOTIPY_CLIENT_SECRET", SPOTIPY_CLIENT_SECRET)


# Support for pytest-xdist parallel execution
# Each worker gets its own test database
def get_test_database_name():
    """Generate unique test database name for parallel execution."""
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    if worker_id == "master":
        return "test_tunestash"
    else:
        return f"test_tunestash_{worker_id}"


# Use PostgreSQL for tests (production parity)
# Connect to the Docker postgres instance but use a separate test database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": get_test_database_name(),
        "USER": os.getenv("POSTGRES_USER", "slm_user"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "slm_dev_password"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "OPTIONS": {
            "connect_timeout": 10,
        },
        "TEST": {
            "NAME": get_test_database_name(),
        },
    }
}

# Use simple password hasher for tests (much faster)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]


# Disable migrations for tests
class DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = DisableMigrations()

# Disable Celery task execution during tests
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Disable logging during tests
LOGGING_CONFIG = None
LOGGING = {}

# Use simple cache for tests
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    }
}

# Use in-memory email backend so mailoutbox fixture works in tests
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Fixed Fernet key for queuetip's at-rest secret encryption (SubsonicConnection
# passwords). Real production keys come from the QUEUETIP_FERNET_KEY env var;
# tests need a deterministic value so encrypt → decrypt round-trips work.
# Dynaconf doesn't expose module-level attributes added after init, so the
# helper reaches through dynaconf's set() — same pattern as SPOTIPY above.
QUEUETIP_FERNET_KEY = "f0Q5J5gXqaV6BV5q3lH0OmYjBgaO3SjA0PpBnUaqIz4="
dynaconf_settings.set("QUEUETIP_FERNET_KEY", QUEUETIP_FERNET_KEY)
