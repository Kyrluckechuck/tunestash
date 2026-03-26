"""Settings registry — single source of truth for all app settings.

Each setting is defined with its key, default, type, category, and metadata.
`get_setting(key)` is the only read interface — sync, callable anywhere.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Value types for settings (drives UI control selection and validation)
TYPE_BOOL = "bool"
TYPE_STRING = "string"
TYPE_INT = "int"
TYPE_FLOAT = "float"
TYPE_LIST = "list"  # JSON list of strings
TYPE_SECRET = "secret"  # String, masked in API responses

# Categories (UI section order)
CAT_AUTH = "authentication"
CAT_DOWNLOADS = "downloads"
CAT_DISCOVERY = "discovery"
CAT_LYRICS_MEDIA = "lyrics_media"
CAT_NOTIFICATIONS = "notifications"
CAT_EXTERNAL = "external_lists"
CAT_INFRA = "infrastructure"

CATEGORY_ORDER = [
    CAT_AUTH,
    CAT_DOWNLOADS,
    CAT_DISCOVERY,
    CAT_LYRICS_MEDIA,
    CAT_NOTIFICATIONS,
    CAT_EXTERNAL,
    CAT_INFRA,
]

CATEGORY_LABELS = {
    CAT_AUTH: "Authentication",
    CAT_DOWNLOADS: "Downloads",
    CAT_DISCOVERY: "Discovery",
    CAT_LYRICS_MEDIA: "Lyrics & Media",
    CAT_NOTIFICATIONS: "Notifications",
    CAT_EXTERNAL: "External Lists",
    CAT_INFRA: "Infrastructure",
}

SENSITIVE_PLACEHOLDER = "**configured**"

# ── Registry ──────────────────────────────────────────────────────────────────
# Each entry: key → {default, type, category, label, description, sensitive?, options?}
#
# Keys are lowercase. get_setting() normalises lookups to lowercase.
# Only user-modified values are stored in DB; defaults live here.

SETTINGS_REGISTRY: dict[str, dict[str, Any]] = {
    # ── Authentication ────────────────────────────────────────────────────
    "youtube_premium": {
        "default": True,
        "type": TYPE_BOOL,
        "category": CAT_AUTH,
        "label": "YouTube Premium Account",
        "description": (
            "When enabled, downloads require valid cookies and POT token for "
            "256kbps AAC. When disabled, cookie/POT validation is skipped and "
            "downloads proceed at free-tier quality (128kbps)."
        ),
    },
    "po_token": {
        "default": None,
        "type": TYPE_SECRET,
        "category": CAT_AUTH,
        "label": "YouTube POT Token",
        "description": "Proof of Origin token for YouTube Music downloads.",
    },
    "spotify_user_auth_enabled": {
        "default": False,
        "type": TYPE_BOOL,
        "category": CAT_AUTH,
        "label": "Spotify User Auth",
        "description": "Enable OAuth flow for private Spotify playlist access.",
    },
    "spotify_redirect_uri": {
        "default": "http://127.0.0.1:5000/auth/spotify/callback",
        "type": TYPE_STRING,
        "category": CAT_AUTH,
        "label": "Spotify Redirect URI",
        "description": (
            "OAuth redirect URI — must match your Spotify app settings. "
            "Use explicit IP (127.0.0.1), not 'localhost'."
        ),
    },
    "spotipy_client_id": {
        "default": "",
        "type": TYPE_SECRET,
        "category": CAT_AUTH,
        "label": "Spotify Client ID",
        "description": "Spotify Developer App client ID for OAuth.",
    },
    "spotipy_client_secret": {
        "default": "",
        "type": TYPE_SECRET,
        "category": CAT_AUTH,
        "label": "Spotify Client Secret",
        "description": "Spotify Developer App client secret for OAuth.",
    },
    # ── Downloads ─────────────────────────────────────────────────────────
    "download_provider_order": {
        "default": ["youtube", "tidal", "qobuz", "monochrome"],
        "type": TYPE_LIST,
        "category": CAT_DOWNLOADS,
        "label": "Provider Order",
        "description": (
            "Download providers tried in order. "
            "Available: youtube, tidal, qobuz, monochrome."
        ),
        "options": ["youtube", "tidal", "qobuz", "monochrome"],
    },
    "fallback_quality": {
        "default": "high",
        "type": TYPE_STRING,
        "category": CAT_DOWNLOADS,
        "label": "Download Quality",
        "description": (
            "high = 320kbps AAC (M4A), lossless = FLAC 16-bit, "
            "hi_res = FLAC 24-bit (when available)."
        ),
        "options": ["high", "lossless", "hi_res"],
    },
    "qobuz_use_mp3": {
        "default": False,
        "type": TYPE_BOOL,
        "category": CAT_DOWNLOADS,
        "label": "Qobuz MP3 Mode",
        "description": (
            "When enabled, Qobuz downloads MP3 320kbps directly instead of "
            "FLAC→M4A conversion."
        ),
    },
    "album_types_to_download": {
        "default": ["single", "album", "compilation"],
        "type": TYPE_LIST,
        "category": CAT_DOWNLOADS,
        "label": "Album Types to Download",
        "description": "Which album types to include when downloading artist catalogs.",
        "options": ["single", "album", "compilation", "ep"],
    },
    "album_groups_to_ignore": {
        "default": ["appears_on"],
        "type": TYPE_LIST,
        "category": CAT_DOWNLOADS,
        "label": "Album Groups to Ignore",
        "description": "Album groups excluded from artist catalog downloads.",
        "options": ["album", "single", "compilation", "appears_on"],
    },
    "overwrite": {
        "default": False,
        "type": TYPE_BOOL,
        "category": CAT_DOWNLOADS,
        "label": "Overwrite Existing Files",
        "description": "Re-download and overwrite files that already exist on disk.",
    },
    "disable_missing_tracked_artist_download": {
        "default": False,
        "type": TYPE_BOOL,
        "category": CAT_DOWNLOADS,
        "label": "Disable Auto-Download for Tracked Artists",
        "description": (
            "When enabled, new albums from tracked artists are fetched but not "
            "automatically queued for download."
        ),
    },
    "pause_downloads_on_auth_failure": {
        "default": True,
        "type": TYPE_BOOL,
        "category": CAT_DOWNLOADS,
        "label": "Pause Downloads on Auth Failure",
        "description": (
            "Pause the download queue when authentication fails (expired POT, "
            "invalid cookies). Downloads resume after restart or auth fix."
        ),
    },
    # ── Discovery ─────────────────────────────────────────────────────────
    "new_releases_genre_ids": {
        "default": [0],
        "type": TYPE_LIST,
        "category": CAT_DISCOVERY,
        "label": "New Releases Genre IDs",
        "description": (
            "Deezer editorial genre IDs to scan for tracked artist releases. "
            "0 = All genres. See https://api.deezer.com/editorial for IDs."
        ),
    },
    # ── Lyrics & Media ────────────────────────────────────────────────────
    "lyrics_enabled": {
        "default": True,
        "type": TYPE_BOOL,
        "category": CAT_LYRICS_MEDIA,
        "label": "Lyrics (.lrc) Fetching",
        "description": (
            "Fetch synced lyrics from LRClib after downloads and save as .lrc "
            "sidecar files. Media players auto-discover these."
        ),
    },
    "navidrome_enabled": {
        "default": False,
        "type": TYPE_BOOL,
        "category": CAT_LYRICS_MEDIA,
        "label": "Navidrome Integration",
        "description": "Trigger a Navidrome library rescan when new music is downloaded.",
    },
    "navidrome_url": {
        "default": "http://navidrome:4533",
        "type": TYPE_STRING,
        "category": CAT_LYRICS_MEDIA,
        "label": "Navidrome URL",
        "description": "Navidrome server URL for Subsonic API.",
    },
    "navidrome_user": {
        "default": "admin",
        "type": TYPE_STRING,
        "category": CAT_LYRICS_MEDIA,
        "label": "Navidrome Username",
        "description": "Navidrome admin username for library rescan.",
    },
    "navidrome_password": {
        "default": "",
        "type": TYPE_SECRET,
        "category": CAT_LYRICS_MEDIA,
        "label": "Navidrome Password",
        "description": "Navidrome admin password for Subsonic API auth.",
    },
    "m3u_playlists_directory": {
        "default": "Playlists",
        "type": TYPE_STRING,
        "category": CAT_LYRICS_MEDIA,
        "label": "M3U Playlists Directory",
        "description": "Directory for .m3u files, relative to the music output path.",
    },
    # ── Notifications ─────────────────────────────────────────────────────
    "notifications_enabled": {
        "default": False,
        "type": TYPE_BOOL,
        "category": CAT_NOTIFICATIONS,
        "label": "Notifications Enabled",
        "description": "Enable Apprise notifications for credential expiry and error alerts.",
    },
    "notifications_urls": {
        "default": [],
        "type": TYPE_LIST,
        "category": CAT_NOTIFICATIONS,
        "label": "Notification URLs",
        "description": (
            "Apprise notification service URLs. "
            "Examples: discord://..., tgram://..., ntfy://..."
        ),
        "sensitive": True,
    },
    "notifications_cooldown_minutes": {
        "default": 60,
        "type": TYPE_INT,
        "category": CAT_NOTIFICATIONS,
        "label": "Cooldown (minutes)",
        "description": "Minimum minutes between repeated notifications of the same type.",
    },
    "notifications_error_max_failure_pct": {
        "default": 50,
        "type": TYPE_INT,
        "category": CAT_NOTIFICATIONS,
        "label": "Error Alert Threshold (%)",
        "description": "Alert when download failure percentage exceeds this value.",
    },
    "notifications_error_min_downloads": {
        "default": 20,
        "type": TYPE_INT,
        "category": CAT_NOTIFICATIONS,
        "label": "Minimum Downloads Before Alert",
        "description": "Minimum downloads in the error window before alerting (avoids false positives).",
    },
    "notifications_error_window_hours": {
        "default": 6,
        "type": TYPE_INT,
        "category": CAT_NOTIFICATIONS,
        "label": "Error Window (hours)",
        "description": "Time window for calculating download failure rate.",
    },
    "notifications_cookie_warn_days": {
        "default": 7,
        "type": TYPE_INT,
        "category": CAT_NOTIFICATIONS,
        "label": "Cookie Warning (days)",
        "description": "Days before cookie expiry to send the first warning.",
    },
    "notifications_cookie_urgent_days": {
        "default": 1,
        "type": TYPE_INT,
        "category": CAT_NOTIFICATIONS,
        "label": "Cookie Urgent Warning (days)",
        "description": "Days before cookie expiry to send the urgent warning.",
    },
    "notifications_instance_name": {
        "default": "",
        "type": TYPE_STRING,
        "category": CAT_NOTIFICATIONS,
        "label": "Instance Name",
        "description": (
            "Name shown in notification titles (e.g. 'MyServer: Cookies Expired'). "
            "Defaults to 'TuneStash' if empty."
        ),
    },
    # ── External Lists ────────────────────────────────────────────────────
    "lastfm_api_key": {
        "default": "",
        "type": TYPE_SECRET,
        "category": CAT_EXTERNAL,
        "label": "Last.fm API Key",
        "description": "Free API key from https://www.last.fm/api/account/create",
    },
    "listenbrainz_user_token": {
        "default": "",
        "type": TYPE_SECRET,
        "category": CAT_EXTERNAL,
        "label": "ListenBrainz User Token",
        "description": "User token from https://listenbrainz.org/settings/",
    },
    # ── Infrastructure ────────────────────────────────────────────────────
    "final_path": {
        "default": "/mnt/music_spotify",
        "type": TYPE_STRING,
        "category": CAT_INFRA,
        "label": "Music Output Path",
        "description": "Final path for downloaded music files. Must match the Docker volume mount.",
    },
    "log_level": {
        "default": "INFO",
        "type": TYPE_STRING,
        "category": CAT_INFRA,
        "label": "Log Level",
        "description": "Application log verbosity.",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
    "worker_diagnostics_enabled": {
        "default": False,
        "type": TYPE_BOOL,
        "category": CAT_INFRA,
        "label": "Worker Diagnostics",
        "description": "Enable verbose diagnostic logging for worker crashes and performance issues.",
    },
    "deezer_rate_limit_per_second": {
        "default": 10,
        "type": TYPE_INT,
        "category": CAT_INFRA,
        "label": "Deezer Rate Limit (req/s)",
        "description": "Maximum Deezer API requests per second.",
    },
    "monochrome_api_urls": {
        "default": ["https://api.monochrome.tf"],
        "type": TYPE_LIST,
        "category": CAT_INFRA,
        "label": "Monochrome API URLs",
        "description": (
            "Monochrome (Tidal CDN) API endpoints, tried in order with "
            "5-minute cooldown on failure."
        ),
    },
}


# ── Lookup helpers ────────────────────────────────────────────────────────────


def _normalize_key(key: str) -> str:
    """Normalize a setting key to lowercase for registry lookup."""
    return key.lower()


def get_setting(key: str) -> Any:
    """Read a single setting value. Sync, safe to call anywhere.

    Resolution order:
      1. DB (AppSetting row for this key) — user-configured value
      2. Registry default

    Returns the registry default if the key has no DB override.
    Raises KeyError if the key is not in the registry.
    """
    norm_key = _normalize_key(key)
    entry = SETTINGS_REGISTRY.get(norm_key)
    if entry is None:
        raise KeyError(f"Unknown setting: {key!r}")

    try:
        from library_manager.models import AppSetting

        row = AppSetting.objects.filter(key=norm_key).first()
        if row is not None:
            return row.value
    except Exception:
        # DB unavailable (e.g. during migrations or tests) — fall through to default
        pass

    return entry["default"]


def get_setting_with_default(key: str, default: Any = None) -> Any:
    """Like get_setting() but returns *default* for unknown keys instead of raising."""
    try:
        return get_setting(key)
    except KeyError:
        return default


def is_sensitive(key: str) -> bool:
    """Check whether a setting should be masked in API responses."""
    norm_key = _normalize_key(key)
    entry = SETTINGS_REGISTRY.get(norm_key, {})
    return entry.get("type") == TYPE_SECRET or entry.get("sensitive", False)
