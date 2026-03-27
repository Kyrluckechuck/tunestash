"""Settings service — async CRUD for the GraphQL layer.

Handles validation, type coercion, sensitive masking, cookie file upload,
and YAML migration.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from asgiref.sync import sync_to_async

from src.app_settings.registry import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    SETTINGS_REGISTRY,
    TYPE_BOOL,
    TYPE_FLOAT,
    TYPE_INT,
    TYPE_LIST,
    TYPE_SECRET,
    TYPE_STRING,
    is_sensitive,
)

logger = logging.getLogger(__name__)

COOKIE_FILE_PATH = Path("/config/youtube_music_cookies.txt")

# Simple cache for Deezer genres (rarely changes)
_genre_cache: list[Any] = []
_genre_cache_time: float = 0
_GENRE_CACHE_TTL = 3600  # 1 hour


class SettingsService:
    """Async service wrapping AppSetting CRUD for GraphQL resolvers."""

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_all_settings(self) -> list[dict[str, Any]]:
        """Return all settings grouped by category, with masking."""
        return await sync_to_async(self._get_all_settings_sync)()

    def _get_all_settings_sync(self) -> list[dict[str, Any]]:
        from library_manager.models import AppSetting

        db_values: dict[str, Any] = {}
        for row in AppSetting.objects.all():
            db_values[row.key] = row.value

        result: list[dict[str, Any]] = []
        for key, entry in SETTINGS_REGISTRY.items():
            raw_value = db_values.get(key, entry["default"])
            result.append(self._format_setting(key, entry, raw_value))
        return result

    async def get_settings_by_category(self) -> list[dict[str, Any]]:
        """Return settings organized into category groups for the UI."""
        return await sync_to_async(self._get_settings_by_category_sync)()

    def _get_settings_by_category_sync(self) -> list[dict[str, Any]]:
        from library_manager.models import AppSetting

        db_values: dict[str, Any] = {}
        for row in AppSetting.objects.all():
            db_values[row.key] = row.value

        categories: list[dict[str, Any]] = []
        for cat in CATEGORY_ORDER:
            settings_in_cat = []
            for key, entry in SETTINGS_REGISTRY.items():
                if entry["category"] != cat:
                    continue
                raw_value = db_values.get(key, entry["default"])
                settings_in_cat.append(self._format_setting(key, entry, raw_value))
            if settings_in_cat:
                categories.append(
                    {
                        "category": cat,
                        "label": CATEGORY_LABELS.get(cat, cat),
                        "settings": settings_in_cat,
                    }
                )
        return categories

    # ── Deezer genres ─────────────────────────────────────────────────────

    async def get_deezer_genres(self) -> list[Any]:
        """Fetch Deezer editorial genres, cached for 1 hour."""
        from src.graphql_types.settings import DeezerGenreType

        global _genre_cache, _genre_cache_time  # pylint: disable=global-statement

        if _genre_cache and (time.monotonic() - _genre_cache_time) < _GENRE_CACHE_TTL:
            return _genre_cache

        import requests

        try:
            resp = requests.get(
                "https://api.deezer.com/editorial",
                timeout=10,
                headers={"User-Agent": "TuneStash/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            genres = [
                DeezerGenreType(id=g["id"], name=g["name"])
                for g in data.get("data", [])
            ]
            _genre_cache = genres
            _genre_cache_time = time.monotonic()
            return genres
        except Exception as exc:
            logger.warning("Failed to fetch Deezer genres: %s", exc)
            return _genre_cache or []

    # ── Write ─────────────────────────────────────────────────────────────

    async def update_setting(self, key: str, value: Any) -> dict[str, Any]:
        """Validate, coerce, and persist a setting value.

        Returns the formatted setting after update.
        Skips save if value is the sensitive placeholder.
        """
        return await sync_to_async(self._update_setting_sync)(key, value)

    def _update_setting_sync(self, key: str, value: Any) -> dict[str, Any]:
        from library_manager.models import AppSetting

        norm_key = key.lower()
        entry = SETTINGS_REGISTRY.get(norm_key)
        if entry is None:
            raise ValueError(f"Unknown setting: {key!r}")

        coerced = self._coerce_value(norm_key, entry, value)

        # If coerced equals the default, delete the DB row (keep DB lean)
        if coerced == entry["default"]:
            AppSetting.objects.filter(key=norm_key).delete()
            logger.info("Setting %s reset to default (removed from DB)", norm_key)
            return self._format_setting(norm_key, entry, entry["default"])

        AppSetting.objects.update_or_create(
            key=norm_key,
            defaults={"value": coerced, "category": entry["category"]},
        )
        logger.info("Setting %s updated", norm_key)
        return self._format_setting(norm_key, entry, coerced)

    async def reset_setting(self, key: str) -> dict[str, Any]:
        """Reset a setting to its registry default (delete DB row)."""
        return await sync_to_async(self._reset_setting_sync)(key)

    def _reset_setting_sync(self, key: str) -> dict[str, Any]:
        from library_manager.models import AppSetting

        norm_key = key.lower()
        entry = SETTINGS_REGISTRY.get(norm_key)
        if entry is None:
            raise ValueError(f"Unknown setting: {key!r}")

        deleted, _ = AppSetting.objects.filter(key=norm_key).delete()
        if deleted:
            logger.info("Setting %s reset to default", norm_key)
        return self._format_setting(norm_key, entry, entry["default"])

    # ── Cookie file upload ────────────────────────────────────────────────

    async def upload_cookie_file(self, content: str) -> dict[str, Any]:
        """Write cookie content to the hardcoded cookie file path."""
        return await sync_to_async(self._upload_cookie_file_sync)(content)

    def _upload_cookie_file_sync(self, content: str) -> dict[str, Any]:
        try:
            COOKIE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            COOKIE_FILE_PATH.write_text(content, encoding="utf-8")
            logger.info("Cookie file written to %s", COOKIE_FILE_PATH)
            return {"success": True, "path": str(COOKIE_FILE_PATH)}
        except Exception as exc:
            logger.error("Failed to write cookie file: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── YAML migration ────────────────────────────────────────────────────

    def migrate_from_yaml_sync(
        self, yaml_path: str = "/config/settings.yaml"
    ) -> dict[str, Any]:
        """Sync version of migrate_from_yaml for Celery tasks."""
        return self._migrate_from_yaml_sync(yaml_path)

    async def migrate_from_yaml(
        self, yaml_path: str = "/config/settings.yaml"
    ) -> dict[str, Any]:
        """Import settings from a YAML file, then remove the original.

        Idempotent — uses update_or_create. Only imports keys that exist
        in the registry. Backs up the YAML before deletion.
        """
        return await sync_to_async(self._migrate_from_yaml_sync)(yaml_path)

    def _migrate_from_yaml_sync(self, yaml_path: str) -> dict[str, Any]:
        from library_manager.models import AppSetting

        path = Path(yaml_path)
        if not path.exists():
            return {
                "success": True,
                "migrated": 0,
                "skipped": 0,
                "message": "No YAML file found — nothing to migrate.",
            }

        try:
            import yaml

            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            return {"success": False, "migrated": 0, "skipped": 0, "error": str(exc)}

        # Dynaconf nests under "default:" key
        if "default" in raw and isinstance(raw["default"], dict):
            raw = raw["default"]

        migrated = 0
        skipped = 0
        for yaml_key, yaml_value in raw.items():
            norm_key = yaml_key.lower()
            entry = SETTINGS_REGISTRY.get(norm_key)
            if entry is None:
                skipped += 1
                continue

            # Skip if value matches default (don't store defaults in DB)
            if yaml_value == entry["default"]:
                skipped += 1
                continue

            # Coerce to expected type
            try:
                coerced = self._coerce_value(norm_key, entry, yaml_value)
            except (ValueError, TypeError):
                skipped += 1
                continue

            # Skip if coerced matches default
            if coerced == entry["default"]:
                skipped += 1
                continue

            AppSetting.objects.update_or_create(
                key=norm_key,
                defaults={"value": coerced, "category": entry["category"]},
            )
            migrated += 1

        # Backup and remove original YAML
        backup_path = path.with_suffix(".yaml.bak")
        try:
            shutil.copy2(path, backup_path)
            path.unlink()
            logger.info(
                "YAML migration complete: %d migrated, %d skipped. "
                "Backup at %s, original removed.",
                migrated,
                skipped,
                backup_path,
            )
        except Exception as exc:
            logger.warning("Migration succeeded but cleanup failed: %s", exc)

        return {
            "success": True,
            "migrated": migrated,
            "skipped": skipped,
            "message": f"Migrated {migrated} settings, skipped {skipped}.",
        }

    # ── Private helpers ───────────────────────────────────────────────────

    def _format_setting(
        self, key: str, entry: dict[str, Any], raw_value: Any
    ) -> dict[str, Any]:
        """Format a setting for API responses."""
        is_default = raw_value == entry["default"]

        return {
            "key": key,
            "value": (
                json.dumps(raw_value) if not isinstance(raw_value, str) else raw_value
            ),
            "default": entry["default"],
            "type": entry["type"],
            "category": entry["category"],
            "label": entry["label"],
            "description": entry["description"],
            "isDefault": is_default,
            "options": entry.get("options"),
            "sensitive": is_sensitive(key),
        }

    @staticmethod
    def _get_db_value(key: str, default: Any) -> Any:
        from library_manager.models import AppSetting

        row = AppSetting.objects.filter(key=key).first()
        return row.value if row is not None else default

    @staticmethod
    def _coerce_value(  # pylint: disable=too-many-return-statements
        key: str, entry: dict[str, Any], value: Any
    ) -> Any:
        """Coerce an incoming value to the expected type."""
        target_type = entry["type"]

        if target_type == TYPE_BOOL:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)

        if target_type == TYPE_INT:
            return int(value)

        if target_type == TYPE_FLOAT:
            return float(value)

        if target_type in (TYPE_STRING, TYPE_SECRET):
            return str(value) if value is not None else ""

        if target_type == TYPE_LIST:
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                # Try JSON parse first, then comma-separated
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass
                return [item.strip() for item in value.split(",") if item.strip()]
            return list(value)

        return value
