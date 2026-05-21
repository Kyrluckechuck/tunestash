import os
from pathlib import Path

import dynaconf
from celery_beat_schedule import CELERY_BEAT_SCHEDULE

# django_stubs_ext is a dev-only dependency for type checking
# Only import and monkeypatch if available (dev environment)
try:
    import django_stubs_ext

    django_stubs_ext.monkeypatch()
except ImportError:
    pass

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent

# Use dynaconf for configuration management (same as monolith)
settings = dynaconf.DjangoDynaconf(
    __name__,
    PRELOAD_FOR_DYNACONF=[
        "../settings.yaml",
        "*.yaml",
        "/config/settings.yaml",
    ],
    ENVVAR_FOR_DYNACONF="DJANGO_ENV",
    settings_files=[
        "../settings.yaml",
        "*.yaml",
        "/config/settings.yaml",
    ],
    # Override defaults for API-specific settings
    SECRET_KEY=os.getenv("DJANGO_SECRET_KEY", "django-insecure-development-only-key"),
    DEBUG=os.getenv("DJANGO_DEBUG", "True").lower() == "true",
    ALLOWED_HOSTS=["*"],
    # API-specific installed apps (keeping core Django + adding API needs)
    INSTALLED_APPS=[
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        "django_celery_results",
        "django_celery_beat",
        "library_manager",
        "queuetip",
        # Dev-only apps are appended conditionally below
    ],
    # API-specific middleware (simpler than full web app)
    MIDDLEWARE=[
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
    ],
    TEMPLATES=[
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [],
            "APP_DIRS": True,
            "OPTIONS": {
                "context_processors": [
                    "django.template.context_processors.debug",
                    "django.template.context_processors.request",
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                ],
            },
        },
    ],
    ROOT_URLCONF="urls",
    STATIC_ROOT=BASE_DIR / "staticfiles",
    STATIC_URL="/static/",
    # Database: PostgreSQL for better concurrent access
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "tunestash"),
            "USER": os.getenv("POSTGRES_USER", "slm_user"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", "slm_dev_password"),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            # Keep connections alive for 10 minutes (helps long-running processes like Celery Beat)
            "CONN_MAX_AGE": 600,
            # Check connection health before using (Django 4.1+) - prevents stale connection errors
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "connect_timeout": 10,
            },
        }
    },
    # Celery Configuration — Redis-protocol broker (Valkey in production)
    CELERY_BROKER_URL=os.getenv("CELERY_BROKER_URL", "redis://valkey:6379/0"),
    CELERY_RESULT_BACKEND="django-db",
    CELERY_ACCEPT_CONTENT=["json"],
    CELERY_TASK_SERIALIZER="json",
    CELERY_RESULT_SERIALIZER="json",
    CELERY_TIMEZONE="UTC",
    CELERY_TASK_TRACK_STARTED=True,
    CELERY_RESULT_EXTENDED=True,
    CELERY_TASK_TIME_LIMIT=30 * 60,  # 30 minutes
    CELERY_BEAT_SCHEDULER="django_celery_beat.schedulers:DatabaseScheduler",
    CELERY_BEAT_SCHEDULE=CELERY_BEAT_SCHEDULE,
    # Retry broker connection forever on startup and at runtime so a transient
    # DNS/network blip cannot leave the consumer loop silently wedged.
    CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP=True,
    CELERY_BROKER_CONNECTION_MAX_RETRIES=None,
    # priority_steps activates priority routing on Redis-family brokers
    # (the kombu Django/SQLAlchemy transport silently ignored it).
    CELERY_BROKER_TRANSPORT_OPTIONS={
        "visibility_timeout": 3600,
        "priority_steps": [0, 3, 6, 9],
        "queue_order_strategy": "priority",
    },
)


# Add django_extensions if available (useful for shell_plus in prod debugging)
_installed_apps = list(settings.INSTALLED_APPS)
try:
    import django_extensions  # noqa: F401

    _installed_apps.append("django_extensions")
except ImportError:
    pass

# Internal IPs and dev-only apps
if settings.DEBUG:  # type: ignore[name-defined]
    INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]  # For Docker, VMs

    try:
        import django_stubs_ext  # noqa: F401

        _installed_apps.append("django_stubs_ext")
    except ImportError:
        pass

settings.set("INSTALLED_APPS", _installed_apps)

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# STATIC_URL is now set in the dynaconf configuration above
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Custom configuration for downloader
# YouTube Music cookies (for high-quality audio downloads via yt-dlp)
youtube_cookies_location = "/config/youtube_music_cookies.txt"

# Spotify OAuth Configuration
spotify_user_auth_enabled = False
# NOTE: Spotify requires 127.0.0.1 instead of localhost
# The system auto-detects the host from requests, but this is the fallback
spotify_redirect_uri = "http://127.0.0.1:5000/auth/spotify/callback"

# Spotify Developer App Credentials (required for OAuth)
# Can be set via environment variables or in /config/settings.yaml
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID", "")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET", "")

# Legacy fallback for backwards compatibility
cookies_location = youtube_cookies_location
po_token = None
log_level = "INFO"
no_lrc = False
overwrite = False
print_exceptions = True

# Logging configuration to reduce verbosity
# File logging is enabled when TUNESTASH_SERVICE is set (per-service in compose).
# Rotates daily at midnight, keeps 2 backups → today + yesterday + day-before = 72h.
# Falls back silently to console-only if /config/logs is not writable, so the app
# never fails to start over a logging permissions issue.
_log_service = os.environ.get("TUNESTASH_SERVICE", "")
_log_handlers = ["console"]
_file_handler: dict | None = None
if _log_service:
    _log_dir = Path("/config/logs")
    try:
        _log_dir.mkdir(parents=True, exist_ok=True)
        _file_handler = {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": str(_log_dir / f"{_log_service}.log"),
            "when": "midnight",
            "backupCount": 2,
            "formatter": "verbose",
            "encoding": "utf-8",
        }
        _log_handlers = ["console", "file"]
    except OSError:
        _file_handler = None

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        **({"file": _file_handler} if _file_handler else {}),
    },
    "root": {
        "handlers": _log_handlers,
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": _log_handlers,
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": _log_handlers,
            "level": "WARNING",
            "propagate": False,
        },
        "django.server": {
            "handlers": _log_handlers,
            "level": "WARNING",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": _log_handlers,
            "level": "ERROR",
            "propagate": False,
        },
        "celery": {
            "handlers": _log_handlers,
            "level": "WARNING",
            "propagate": False,
        },
        "library_manager": {
            "handlers": _log_handlers,
            "level": "INFO",
            "propagate": False,
        },
    },
}
# Storage configuration (replaces deprecated DEFAULT_FILE_STORAGE and STATICFILES_STORAGE)
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Note: Using STORAGES configuration above instead of deprecated DEFAULT_FILE_STORAGE and STATICFILES_STORAGE
# The Django deprecation warnings for these settings are unavoidable in Django 5.0 when using dynaconf

# ── Queuetip ────────────────────────────────────────────────────────────────
# Public base URL of the Queuetip ASGI process — used to build magic-link URLs.
# Browser-facing base URL for the Queuetip stack — used in magic-link emails,
# m3u download URLs, and as the Spotify OAuth redirect_uri fallback when
# X-Forwarded-Host is absent. In dev this points at the Vite proxy (3001),
# which forwards /graphql, /auth, /exports to the backend container — same
# pattern TuneStash uses for its frontend↔backend interaction. 127.0.0.1
# (not 'localhost') because Spotify OAuth hard-rejects 'localhost'.
QUEUETIP_PUBLIC_URL = os.getenv("QUEUETIP_PUBLIC_URL", "http://127.0.0.1:3001")
# Same value as QUEUETIP_PUBLIC_URL in single-origin dev/prod setups —
# kept as a separate setting in case a future deployment splits the API
# host from the frontend host. Used for CORS allowlist + post-OAuth redirect.
QUEUETIP_FRONTEND_URL = os.getenv("QUEUETIP_FRONTEND_URL", "http://127.0.0.1:3001")

# Fernet key for at-rest encryption of queuetip-owned secrets
# (SubsonicConnection.password_encrypted is the first user). Generate with
# `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`.
# In DEBUG, an empty value falls back to a SECRET_KEY-derived dev key; in
# production, a missing key raises CryptoError on any encrypt/decrypt call.
QUEUETIP_FERNET_KEY = os.getenv("QUEUETIP_FERNET_KEY", "")
# Trusted reverse-proxy IPs/CIDRs for X-Forwarded-For parsing. When the
# direct connection comes from one of these addresses, the XFF header is
# trusted and the real client IP is extracted from it. Accepts individual IPs
# and CIDR blocks (e.g. "10.0.0.0/8"). Empty by default — safe for deployments
# that expose the process directly. Example production values:
#   ["127.0.0.1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
# For Cloudflare Tunnel, add Cloudflare's published IPv4/IPv6 ranges instead.
QUEUETIP_TRUSTED_PROXIES: list[str] = []

# Email — magic-link delivery. Resolution order:
#   1. DJANGO_EMAIL_BACKEND env var (escape hatch for dev: force console backend
#      without editing settings.yaml — useful when SMTP isn't reachable locally).
#   2. settings.yaml `email_host` → SMTP backend with the related SMTP settings.
#   3. Otherwise → console backend (links print to the container logs).
_email_backend_env = os.getenv("DJANGO_EMAIL_BACKEND")
_email_host = settings.get("email_host", None)
if _email_backend_env:
    EMAIL_BACKEND = _email_backend_env
elif _email_host:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = _email_host
    EMAIL_PORT = int(settings.get("email_port", 587))
    EMAIL_HOST_USER = settings.get("email_host_user", "")
    EMAIL_HOST_PASSWORD = settings.get("email_host_password", "")
    EMAIL_USE_TLS = bool(settings.get("email_use_tls", True))
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = settings.get("default_from_email", "Queuetip <queuetip@localhost>")

# Sign-up gate. When True (default), only emails on the QueuetipSignupAllowlist
# can create new accounts. Existing accounts always sign in normally.
# Set to False to allow open sign-ups (e.g. for personal local-only use).
QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST = (
    os.getenv("QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST", "true").lower() != "false"
)
