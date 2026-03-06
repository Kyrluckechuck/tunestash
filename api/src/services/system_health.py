"""
System health service for monitoring authentication and configuration status.
"""

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from django.conf import settings

from downloader.cookie_validator import CookieValidationResult, CookieValidator
from downloader.premium_detector import PremiumDetector
from lib.config_class import Config

logger = logging.getLogger(__name__)


@dataclass
class AuthenticationStatus:  # pylint: disable=too-many-instance-attributes
    """Authentication status for YouTube Music Premium and Spotify access."""

    # YouTube Music authentication (for high-quality audio downloads)
    cookies_valid: bool
    cookies_error_type: Optional[str] = None  # 'missing', 'malformed', 'expired'
    cookies_error_message: Optional[str] = None
    cookies_expire_in_days: Optional[int] = None
    po_token_configured: bool = False
    po_token_valid: bool = False
    po_token_error_message: Optional[str] = None

    # Spotify authentication mode (for playlist access)
    spotify_user_auth_enabled: bool = False
    spotify_auth_mode: str = (
        "public"  # 'public' (public playlists only) or 'user-authenticated' (includes private)
    )

    # Spotify OAuth token status (when using user-authenticated mode)
    spotify_token_valid: bool = True
    spotify_token_expired: bool = False
    spotify_token_expires_in_hours: Optional[int] = None
    spotify_token_error_message: Optional[str] = None


class SystemHealthService:
    """Service for checking system health and configuration."""

    # Shared PremiumDetector instance for caching validation results
    _detector_cache: Dict[str, PremiumDetector] = {}

    @staticmethod
    def _check_spotify_oauth_token_exists() -> bool:
        """
        Sync helper to check if Spotify OAuth token exists in database.

        This method is separated so it can be properly called from async contexts.
        """
        import logging

        from library_manager.models import SpotifyOAuthToken

        logger = logging.getLogger(__name__)

        try:
            token = SpotifyOAuthToken.objects.get(id=1)
            logger.info(
                f"OAuth token check: FOUND token with access_token length {len(token.access_token)}"
            )
            return True
        except SpotifyOAuthToken.DoesNotExist:
            logger.info("OAuth token check: Token does NOT exist")
            return False
        except Exception as e:
            # Handle any unexpected errors (e.g., database connection issues)
            logger.error(
                f"OAuth token check: Exception occurred: {type(e).__name__}: {e}"
            )
            return False

    @staticmethod
    def _check_spotify_oauth_token_status() -> Dict[str, Any]:
        """
        Check Spotify OAuth token validity and expiration status.

        If the token is expired or expiring soon, this will attempt to refresh it
        automatically using the refresh token.

        Returns:
            Dict with token status information:
            - valid: bool - Whether token exists and is not expired
            - expired: bool - Whether token is expired
            - expires_in_hours: Optional[int] - Hours until expiration
            - error_message: Optional[str] - Error message if any
        """
        import logging

        from django.utils import timezone

        from library_manager.models import SpotifyOAuthToken

        logger = logging.getLogger(__name__)

        try:
            token = SpotifyOAuthToken.objects.get(id=1)

            # Check if token needs refresh (expired or expiring within 5 minutes)
            if token.is_expired():
                # Attempt to refresh the token proactively
                logger.info(
                    "Spotify OAuth token expired or expiring soon, attempting refresh"
                )
                try:
                    from src.services.spotify_oauth import SpotifyOAuthService

                    new_token_data = SpotifyOAuthService.refresh_access_token(
                        token.refresh_token
                    )
                    token = SpotifyOAuthService.save_tokens(new_token_data)
                    logger.info("Successfully refreshed Spotify OAuth token")
                except Exception as refresh_error:
                    logger.error(
                        f"Failed to refresh Spotify OAuth token: {refresh_error}"
                    )
                    return {
                        "valid": False,
                        "expired": True,
                        "expires_in_hours": None,
                        "error_message": "Spotify OAuth token has expired and refresh failed. Please re-authenticate.",
                    }

            # Token is now valid (either it was valid, or we just refreshed it)
            now = timezone.now()

            # Calculate hours until expiration
            time_until_expiry = token.expires_at - now
            hours_until_expiry = int(time_until_expiry.total_seconds() / 3600)

            return {
                "valid": True,
                "expired": False,
                "expires_in_hours": hours_until_expiry,
                "error_message": None,
            }

        except SpotifyOAuthToken.DoesNotExist:
            # No token stored - not an error if not using OAuth
            return {
                "valid": True,  # Consider valid if not using OAuth
                "expired": False,
                "expires_in_hours": None,
                "error_message": None,
            }
        except Exception as e:
            logger.error(f"Error checking Spotify OAuth token status: {e}")
            return {
                "valid": False,
                "expired": False,
                "expires_in_hours": None,
                "error_message": f"Error checking token: {str(e)}",
            }

    @staticmethod
    def _get_detector(config: Config) -> PremiumDetector:
        """
        Get or create a cached PremiumDetector instance.

        Uses cookies_location + po_token as cache key to reuse detector instances
        and preserve validation cache across multiple health checks.
        """
        cache_key = f"{config.youtube_cookies_location}:{config.po_token}"

        if cache_key not in SystemHealthService._detector_cache:
            SystemHealthService._detector_cache[cache_key] = PremiumDetector(
                cookies_file=(
                    str(config.youtube_cookies_location)
                    if config.youtube_cookies_location
                    else None
                ),
                po_token=config.po_token,
            )

        return SystemHealthService._detector_cache[cache_key]

    @staticmethod
    def check_authentication_status(
        config: Optional[Config] = None,
    ) -> AuthenticationStatus:
        """
        Check YouTube Music Premium authentication status (cookies and po_token).

        This system requires BOTH valid cookies AND a valid PO token for premium downloads.

        Args:
            config: Optional Config instance. If None, creates new one.

        Returns:
            AuthenticationStatus with current auth state
        """
        if config is None:
            config = Config()

        # Check YouTube cookies
        cookie_result: CookieValidationResult
        if config.youtube_cookies_location:
            cookie_path = Path(config.youtube_cookies_location)
            cookie_result = CookieValidator.validate_file(cookie_path)
        else:
            cookie_result = CookieValidationResult(
                valid=False,
                error_type="missing",
                error_message="Cookie file path not configured",
            )

        # Check po_token - REQUIRED for premium
        # First do format validation
        format_result = CookieValidator.validate_po_token(config.po_token)
        po_token_configured = bool(config.po_token and len(config.po_token.strip()) > 0)

        # If format is valid AND cookies are valid, do live validation against YouTube API
        # (PO token validation requires valid cookies to work)
        if format_result.valid and cookie_result.valid:
            # Use cached detector instance to preserve validation cache
            detector = SystemHealthService._get_detector(config)
            po_token_result = detector.validate_po_token_live()
        else:
            # Format invalid OR cookies invalid - can't do live validation
            # Convert format result to match live validation result structure
            from downloader.premium_detector import (
                PoTokenValidationResult as LivePoTokenValidationResult,
            )

            if not format_result.valid:
                # Format validation failed
                error_msg = format_result.error_message
            else:
                # Cookies are invalid, can't test PO token
                error_msg = (
                    "Cannot validate PO token - cookies are invalid. Fix cookies first."
                )

            po_token_result = LivePoTokenValidationResult(
                valid=False,
                error_message=error_msg,
                can_authenticate=False,
            )

        # Check Spotify authentication mode and OAuth connection status
        import logging

        logger = logging.getLogger(__name__)

        spotify_user_auth = config.spotify_user_auth_enabled
        # Check if OAuth tokens are actually stored
        has_oauth_token = SystemHealthService._check_spotify_oauth_token_exists()
        spotify_mode = "user-authenticated" if has_oauth_token else "public"

        logger.info(
            f"Spotify auth check: has_oauth_token={has_oauth_token}, spotify_mode={spotify_mode}"
        )

        # Check Spotify OAuth token status (expiration, validity)
        spotify_token_status = SystemHealthService._check_spotify_oauth_token_status()

        return AuthenticationStatus(
            cookies_valid=cookie_result.valid,
            cookies_error_type=cookie_result.error_type,
            cookies_error_message=cookie_result.error_message,
            cookies_expire_in_days=cookie_result.days_until_expiry,
            po_token_configured=po_token_configured,
            po_token_valid=po_token_result.valid,
            po_token_error_message=po_token_result.error_message,
            spotify_user_auth_enabled=spotify_user_auth,
            spotify_auth_mode=spotify_mode,
            spotify_token_valid=spotify_token_status["valid"],
            spotify_token_expired=spotify_token_status["expired"],
            spotify_token_expires_in_hours=spotify_token_status["expires_in_hours"],
            spotify_token_error_message=spotify_token_status["error_message"],
        )

    @staticmethod
    def is_download_capable(
        config: Optional[Config] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if system can perform premium downloads.

        Requires BOTH valid cookies AND valid PO token for YouTube Music Premium.

        Returns:
            Tuple of (can_download, reason_if_not)
        """
        status = SystemHealthService.check_authentication_status(config)

        # Check cookies first
        if not status.cookies_valid:
            return (
                False,
                f"Cookies {status.cookies_error_type}: {status.cookies_error_message}",
            )

        # Check PO token - REQUIRED for premium
        if not status.po_token_valid:
            return (
                False,
                f"PO Token invalid: {status.po_token_error_message}. This system requires YouTube Music Premium authentication.",
            )

        # Check storage health
        storage_status = SystemHealthService.check_storage_status()
        if not storage_status.is_writable:
            return (
                False,
                f"Storage unavailable: {storage_status.error_message}",
            )

        # Check if storage is critically low
        if storage_status.is_critically_low:
            return (
                False,
                f"Storage critically low: {storage_status.available_gb:.1f}GB available "
                f"({storage_status.usage_percent:.0f}% used)",
            )

        return True, None

    @staticmethod
    def get_output_directory() -> Path:
        """Get the configured music output directory."""
        # Check for configured output path in settings
        output_path = getattr(settings, "MUSIC_OUTPUT_PATH", None)
        if output_path:
            return Path(output_path)

        # Fall back to default from download settings
        from downloader.default_download_settings import DEFAULT_DOWNLOAD_SETTINGS

        output_template: str = str(
            DEFAULT_DOWNLOAD_SETTINGS.get(
                "output",
                "/mnt/music_spotify/{artist}/{album}/{artists} - {title}.{output-ext}",
            )
        )
        # Extract base directory from template
        base_dir = output_template.split("{", maxsplit=1)[0].rstrip("/")
        return Path(base_dir) if base_dir else Path("/mnt/music_spotify")

    @staticmethod
    def check_storage_status() -> "StorageStatus":
        """
        Check storage health for the music output directory.

        Performs:
        1. Directory existence check
        2. Write permission test (creates and deletes a temp file)
        3. Disk space analysis

        Returns:
            StorageStatus with current storage state
        """
        output_dir = SystemHealthService.get_output_directory()

        # Check if directory exists
        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created output directory: {output_dir}")
            except (OSError, PermissionError) as e:
                return StorageStatus(
                    path=str(output_dir),
                    exists=False,
                    is_writable=False,
                    error_message=f"Cannot create directory: {e}",
                )

        # Test write permissions by creating a temp file
        is_writable = False
        write_error = None
        try:
            test_file = output_dir / f".tunestash_write_test_{os.getpid()}"
            test_file.write_text("test")
            test_file.unlink()
            is_writable = True
        except (OSError, PermissionError) as e:
            write_error = f"Cannot write to directory: {e}"
            logger.warning(f"Storage write test failed for {output_dir}: {e}")

        # Get disk space info
        try:
            disk_usage = shutil.disk_usage(output_dir)
            total_gb = disk_usage.total / (1024**3)
            used_gb = disk_usage.used / (1024**3)
            available_gb = disk_usage.free / (1024**3)
            usage_percent = (disk_usage.used / disk_usage.total) * 100
        except OSError as e:
            logger.error(f"Failed to get disk usage for {output_dir}: {e}")
            return StorageStatus(
                path=str(output_dir),
                exists=output_dir.exists(),
                is_writable=is_writable,
                error_message=write_error or f"Cannot read disk usage: {e}",
            )

        # Thresholds for storage warnings
        warning_threshold_percent = 90
        critical_threshold_percent = 95
        critical_threshold_gb = 5  # Less than 5GB free is critical

        is_low = usage_percent >= warning_threshold_percent
        is_critically_low = (
            usage_percent >= critical_threshold_percent
            or available_gb < critical_threshold_gb
        )

        return StorageStatus(
            path=str(output_dir),
            exists=True,
            is_writable=is_writable,
            total_gb=total_gb,
            used_gb=used_gb,
            available_gb=available_gb,
            usage_percent=usage_percent,
            is_low=is_low,
            is_critically_low=is_critically_low,
            error_message=write_error,
        )

    @staticmethod
    def is_storage_healthy() -> tuple[bool, Optional[str]]:
        """
        Quick check if storage is healthy enough for downloads.

        Returns:
            Tuple of (is_healthy, reason_if_not)
        """
        status = SystemHealthService.check_storage_status()

        if not status.is_writable:
            return False, status.error_message or "Storage is not writable"

        if status.is_critically_low:
            return (
                False,
                f"Storage critically low: {status.available_gb:.1f}GB available",
            )

        return True, None


@dataclass
class StorageStatus:  # pylint: disable=too-many-instance-attributes
    """Storage health status for the music output directory."""

    path: str
    exists: bool
    is_writable: bool
    total_gb: Optional[float] = None
    used_gb: Optional[float] = None
    available_gb: Optional[float] = None
    usage_percent: Optional[float] = None
    is_low: bool = False  # Warning threshold (90%+)
    is_critically_low: bool = False  # Critical threshold (95%+ or <5GB)
    error_message: Optional[str] = None
