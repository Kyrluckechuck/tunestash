"""
Download provider chain orchestrator.

This module provides a DownloadProviderChain (formerly FallbackDownloader) that
tries multiple download providers in sequence until one succeeds.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from downloader.filesystem_safety import (
    UnsafePathError,
    is_within,
    sanitize_component,
)

from .audio_converter import AudioConversionError, convert_flac_to_m4a
from .base import DownloadProvider, QualityPreference, TrackMatch, TrackMetadata
from .metadata import MetadataEmbedder
from .monochrome import MonochromeProvider
from .qobuz import QobuzProvider
from .tidal import TidalProvider
from .tidal_endpoints import TidalEndpointManager
from .validation import AudioValidator, ValidationResult
from .youtube import YouTubeMusicProvider

logger = logging.getLogger(__name__)

# Bounds for diagnostics so a single noisy provider cannot flood task history
# or file logs. Credentials and signed URLs must never be persisted.
MAX_OUTCOME_DETAIL_LENGTH = 300
MAX_OUTCOMES = 8

# Fail-closed URL handling: keep only the host. Userinfo, opaque path segments,
# query strings and fragments can all carry signed tokens, so they are dropped
# for every scheme (http, socks5, ftp, ...).
_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^\s\"'<>]+", re.IGNORECASE)
_URL_AUTHORITY_RE = re.compile(r"^[a-z][a-z0-9+.-]*://([^/?#]*)(.*)$", re.IGNORECASE)


def _credential_key(words: str) -> str:
    return rf"[\"']?[\w-]*(?:{words})[\w-]*[\"']?\s*[:=]\s*"


# Credential assignments: JSON keys, token-style keys with any prefix
# (access_token, refresh_token, X-Api-Key). Quoted values are consumed whole.
_QUOTED_VALUE = r"\"(?:\\.|[^\"\\])*(?:\"|$)|'(?:\\.|[^'\\])*(?:'|$)"
_CREDENTIAL_KV_RE = re.compile(
    r"(?i)("
    + _credential_key(
        r"token|secret|password|passwd|pwd|api[_-]?key|apikey|auth|credential|cookie"
    )
    + r")(?:"
    + _QUOTED_VALUE
    + r"|[^,;&}\s]+)"
)
# Unquoted cookie/password-style values cannot be bounded reliably (spaces,
# "a=b; c=d"), so everything after the key is dropped.
_GREEDY_CREDENTIAL_RE = re.compile(
    r"(?i)(" + _credential_key(r"cookie|passw(?:or)?d|pwd|secret") + r")(?![\"'])(.*)$"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(authorization|cookie|set-cookie|proxy-authorization)\s*:\s*.*$"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[^\s,;]+")

# Typed literals shared across the chain and download task; no enum framework.
OutcomeStage = Literal[
    "init",
    "search",
    "download",
    "conversion",
    "metadata",
    "validation",
    "lyrics",
    "summary",
    "chain",
]
OutcomeKind = Literal[
    "unavailable",
    "error",
    "no_result_unknown",
    "warning",
    "success",
    "omitted",
]


def _safe_url(match: re.Match[str]) -> str:
    parsed = _URL_AUTHORITY_RE.match(match.group(0))
    if not parsed:
        return "[url redacted]"
    authority, rest = parsed.groups()
    # An '@' outside the authority means userinfo containing a raw '/', '?' or
    # '#', so the authority cannot be trusted.
    if "@" in rest:
        return "[url redacted]"
    host = authority.rsplit("@", 1)[-1].split(":", 1)[0]
    return f"url:{host}" if host else "[url redacted]"


def sanitize_provider_detail(detail: object) -> str:
    """Return a short, credential-free diagnostic string for a provider error.

    URLs are reduced to their host and credential assignments are removed in
    full. Plain prose containing words like "key" or "session" without a value
    is preserved.
    """
    text = str(detail) if detail is not None else ""
    # Escaped payloads have ambiguous quote boundaries; omit them rather than
    # unescaping values and accidentally exposing the rest of a secret.
    if "\\" in text and _CREDENTIAL_KV_RE.search(text.replace("\\", "")):
        return "[redacted]"
    text = text.replace("\n", " ").replace("\r", " ")
    text = _URL_RE.sub(_safe_url, text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    text = _AUTH_HEADER_RE.sub(r"\1=[redacted]", text)
    text = _GREEDY_CREDENTIAL_RE.sub(r"\1[redacted]", text)
    text = _CREDENTIAL_KV_RE.sub(r"\1[redacted]", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) > MAX_OUTCOME_DETAIL_LENGTH:
        text = text[: MAX_OUTCOME_DETAIL_LENGTH - 3] + "..."
    return text


@dataclass
class ProviderOutcome:
    """A bounded, sanitized record of one provider attempt in the chain.

    ``truncated`` records the number of outcomes omitted by chain truncation.
    """

    provider: str
    stage: OutcomeStage
    outcome: OutcomeKind
    detail: str = ""
    truncated: int = 0


@dataclass
class DownloadChainResult:
    """Result of a download chain attempt.

    ``provider_outcomes`` is additive and defaulted, so existing callers that
    construct the six original fields continue to work unchanged.
    """

    success: bool
    file_path: Optional[Path]
    provider_used: Optional[str]
    error_message: Optional[str]
    track_match: Optional[TrackMatch]
    validation_result: Optional[ValidationResult]
    provider_outcomes: list[ProviderOutcome] = field(default_factory=list)


# Backward-compatible alias
FallbackDownloadResult = DownloadChainResult


class DownloadProviderChain:
    """
    Orchestrates downloads across multiple providers with fallback.

    Tries download providers in order until one succeeds.

    The download process for each provider:
    1. Search for the track using ISRC (most reliable) or metadata
    2. Download from the matching track
    3. Convert FLAC to M4A if needed (for HIGH quality preference)
    4. Embed metadata (providers don't include proper tags)
    5. Validate the downloaded file
    6. Fetch lyrics if enabled
    """

    SUPPORTED_PROVIDERS = {"youtube", "tidal", "qobuz", "monochrome"}

    def __init__(
        self,
        quality_preference: QualityPreference = QualityPreference.HIGH,
        output_dir: Optional[Path] = None,
        provider_order: Optional[list[str]] = None,
        qobuz_use_mp3: bool = False,
    ):
        self._quality_preference = quality_preference
        if output_dir:
            self._output_dir = output_dir
        else:
            from django.conf import settings as django_settings

            self._output_dir = Path(
                getattr(django_settings, "OUTPUT_PATH", "/mnt/music_spotify")
            )
        self._qobuz_use_mp3 = qobuz_use_mp3

        if provider_order is not None:
            self._provider_order = [
                p for p in provider_order if p in self.SUPPORTED_PROVIDERS
            ]
        else:
            self._provider_order = ["youtube", "tidal", "qobuz", "monochrome"]

        self._tidal_endpoint_manager = TidalEndpointManager()
        self._providers: dict[str, DownloadProvider] = {}
        self._metadata_embedder = MetadataEmbedder()
        self._audio_validator = AudioValidator()

        self._initialized: set[str] = set()

    async def _ensure_provider_initialized(self, provider_name: str) -> bool:
        """Ensure a provider is initialized and available.

        Re-checks availability each time for providers that previously failed,
        since endpoint health can recover quickly. Per-endpoint cooldowns are
        handled internally by each provider's endpoint manager.
        """
        if provider_name in self._initialized:
            return True

        try:
            provider: DownloadProvider
            if provider_name == "youtube":
                provider = YouTubeMusicProvider()
                if not await provider.is_available():
                    logger.warning("YouTube Music provider is not available")
                    return False
                self._providers["youtube"] = provider

            elif provider_name == "tidal":
                provider = TidalProvider(
                    endpoint_manager=self._tidal_endpoint_manager,
                )
                if not await provider.is_available():
                    logger.warning("Tidal API is not available")
                    return False
                self._providers["tidal"] = provider

            elif provider_name == "qobuz":
                provider = QobuzProvider(use_mp3=self._qobuz_use_mp3)
                if not await provider.is_available():
                    logger.warning("Qobuz API is not available")
                    return False
                self._providers["qobuz"] = provider

            elif provider_name == "monochrome":
                provider = MonochromeProvider()
                if not await provider.is_available():
                    logger.warning("Monochrome provider is not available")
                    return False
                self._providers["monochrome"] = provider

            else:
                logger.warning(f"Unknown provider: {provider_name}")
                return False

            self._initialized.add(provider_name)
            return True

        except Exception as e:
            logger.error(
                f"Failed to initialize {provider_name}: "
                f"{sanitize_provider_detail(e)}"
            )
            return False

    async def download_track(
        self,
        track_metadata: TrackMetadata,
        output_filename: Optional[str] = None,
    ) -> DownloadChainResult:
        """
        Attempt to download a track using providers in order.

        Tries each provider in the configured order until one succeeds.
        """
        if not self._provider_order:
            return DownloadChainResult(
                success=False,
                file_path=None,
                provider_used=None,
                error_message="No fallback providers configured",
                track_match=None,
                validation_result=None,
                provider_outcomes=[
                    ProviderOutcome(
                        provider="none",
                        stage="init",
                        outcome="unavailable",
                        detail="No fallback providers configured",
                    )
                ],
            )

        last_error = "All providers failed"
        outcomes: list[ProviderOutcome] = []

        for provider_name in self._provider_order:
            logger.info(
                f"[{provider_name}] Trying to download: "
                f"'{track_metadata.artist} - {track_metadata.title}'"
            )

            if not await self._ensure_provider_initialized(provider_name):
                logger.warning(f"[{provider_name}] Provider not available, skipping")
                outcomes.append(
                    ProviderOutcome(
                        provider=provider_name,
                        stage="init",
                        outcome="unavailable",
                        detail="Provider unavailable during initialization",
                    )
                )
                continue

            provider = self._providers.get(provider_name)
            if not provider:
                outcomes.append(
                    ProviderOutcome(
                        provider=provider_name,
                        stage="init",
                        outcome="unavailable",
                        detail="Provider instance missing after initialization",
                    )
                )
                continue

            result = await self._try_provider(
                provider=provider,
                track_metadata=track_metadata,
                output_filename=output_filename,
            )
            outcomes.extend(result.provider_outcomes)
            if len(outcomes) > MAX_OUTCOMES:
                # Keep first and most recent attempts and record how many were
                # dropped. Silent truncation hides provider failures.
                kept = outcomes[:1] + outcomes[-(MAX_OUTCOMES - 1) :]
                omitted = len(outcomes) - len(kept)
                kept.append(
                    ProviderOutcome(
                        provider="chain",
                        stage="summary",
                        outcome="omitted",
                        detail=f"{omitted} provider outcomes omitted",
                        truncated=omitted,
                    )
                )
                outcomes = kept

            if result.success:
                # Retain earlier failures alongside the success so diagnostics
                # do not discard useful context about a recovered chain.
                return DownloadChainResult(
                    success=True,
                    file_path=result.file_path,
                    provider_used=result.provider_used,
                    error_message=result.error_message,
                    track_match=result.track_match,
                    validation_result=result.validation_result,
                    provider_outcomes=outcomes,
                )

            last_error = result.error_message or f"{provider_name} failed"
            logger.info(
                f"[{provider_name}] Failed: {sanitize_provider_detail(last_error)}"
            )

        return DownloadChainResult(
            success=False,
            file_path=None,
            provider_used=None,
            error_message=last_error,
            track_match=None,
            validation_result=None,
            provider_outcomes=outcomes,
        )

    @staticmethod
    def _outcome(
        provider: str,
        stage: OutcomeStage,
        outcome: OutcomeKind,
        detail: object = "",
    ) -> ProviderOutcome:
        return ProviderOutcome(
            provider=provider,
            stage=stage,
            outcome=outcome,
            detail=sanitize_provider_detail(detail),
        )

    async def _try_provider(
        self,
        provider: DownloadProvider,
        track_metadata: TrackMetadata,
        output_filename: Optional[str],
    ) -> DownloadChainResult:
        provider_name = provider.name

        # Step 1: Search for the track
        try:
            match = await provider.search_track(
                title=track_metadata.title,
                artist=track_metadata.artist,
                album=track_metadata.album,
                isrc=track_metadata.isrc,
                duration_ms=track_metadata.duration_ms,
            )
            if match is None:
                # Providers commonly return None for network failures as well
                # as a genuine empty result, so this is not a catalog verdict.
                detail = "Search returned no result (no match or provider failure)"
                logger.info(
                    f"[{provider_name}] {detail} for "
                    f"'{track_metadata.artist} - {track_metadata.title}'"
                )
                return DownloadChainResult(
                    success=False,
                    file_path=None,
                    provider_used=provider_name,
                    error_message=detail,
                    track_match=None,
                    validation_result=None,
                    provider_outcomes=[
                        self._outcome(
                            provider_name,
                            "search",
                            "no_result_unknown",
                            detail,
                        )
                    ],
                )

            logger.info(
                f"[{provider_name}] Found match: '{match.artist} - {match.title}' "
                f"(confidence: {match.confidence:.2f})"
            )
        except Exception as e:
            logger.error(
                f"[{provider_name}] Search failed: {sanitize_provider_detail(e)}"
            )
            return DownloadChainResult(
                success=False,
                file_path=None,
                provider_used=provider_name,
                error_message=f"Search failed: {sanitize_provider_detail(e)}",
                track_match=None,
                validation_result=None,
                provider_outcomes=[self._outcome(provider_name, "search", "error", e)],
            )

        # Step 2: Download the track
        try:
            safe_artist = self._sanitize_filename(track_metadata.artist)
            safe_album = self._sanitize_filename(
                track_metadata.album or "Unknown Album"
            )
            if output_filename:
                base_filename = output_filename
            else:
                safe_title = self._sanitize_filename(track_metadata.title)
                base_filename = f"{safe_artist} - {safe_title}"

            ext = self._get_expected_extension(provider_name)
            album_dir = self._output_dir / safe_artist / safe_album
            output_path = album_dir / f"{base_filename}.{ext}"
            # Fail closed if a sanitized name or a symlinked directory would
            # place the download outside the configured output root.
            if not is_within(output_path, self._output_dir):
                raise UnsafePathError(
                    f"Refusing download destination outside library: {output_path}"
                )
            album_dir.mkdir(parents=True, exist_ok=True)
            if not is_within(output_path, self._output_dir):
                raise UnsafePathError(
                    f"Download destination escaped library: {output_path}"
                )

            download_result = await provider.download_track(
                track_match=match,
                output_path=output_path,
                quality=self._quality_preference,
            )

            if not download_result.success or download_result.file_path is None:
                logger.error(
                    f"[{provider_name}] Download failed: "
                    f"{sanitize_provider_detail(download_result.error)}"
                )
                return DownloadChainResult(
                    success=False,
                    file_path=None,
                    provider_used=provider_name,
                    error_message=sanitize_provider_detail(
                        download_result.error or "Download failed"
                    ),
                    track_match=match,
                    validation_result=None,
                    provider_outcomes=[
                        self._outcome(
                            provider_name,
                            "download",
                            "error",
                            download_result.error or "Download failed",
                        )
                    ],
                )

            file_path = download_result.file_path
            logger.info(f"[{provider_name}] Downloaded to: {file_path}")
        except Exception as e:
            logger.error(
                f"[{provider_name}] Download failed with exception: "
                f"{sanitize_provider_detail(e)}"
            )
            return DownloadChainResult(
                success=False,
                file_path=None,
                provider_used=provider_name,
                error_message=f"Download failed: {sanitize_provider_detail(e)}",
                track_match=match,
                validation_result=None,
                provider_outcomes=[
                    self._outcome(provider_name, "download", "error", e)
                ],
            )

        # Step 3: Convert FLAC to M4A if user requested HIGH quality
        if (
            self._quality_preference == QualityPreference.HIGH
            and file_path.suffix.lower() == ".flac"
        ):
            try:
                logger.info(
                    f"[{provider_name}] Converting FLAC to M4A for HIGH quality"
                )
                file_path = convert_flac_to_m4a(
                    input_path=file_path,
                    bitrate_kbps=256,
                    delete_original=True,
                )
                logger.info(f"[{provider_name}] Converted to: {file_path}")
            except AudioConversionError as e:
                logger.error(
                    f"[{provider_name}] FLAC to M4A conversion failed: "
                    f"{sanitize_provider_detail(e)}"
                )
                return DownloadChainResult(
                    success=False,
                    file_path=None,
                    provider_used=provider_name,
                    error_message=f"Format conversion failed: {sanitize_provider_detail(e)}",
                    track_match=match,
                    validation_result=None,
                    provider_outcomes=[
                        self._outcome(provider_name, "conversion", "error", e)
                    ],
                )

        # Non-fatal problems still deserve diagnostics, but must not turn a
        # downloaded file into a failure.
        warnings: list[ProviderOutcome] = []

        # Step 4: Embed metadata
        try:
            metadata_success = self._metadata_embedder.embed_metadata(
                file_path=file_path,
                track_metadata=track_metadata,
                track_match=match,
            )
            if not metadata_success:
                detail = "Metadata embedding returned false; file may lack tags"
                logger.warning(f"[{provider_name}] {detail}")
                warnings.append(
                    self._outcome(provider_name, "metadata", "warning", detail)
                )
        except Exception as e:
            detail = f"Metadata embedding failed: {sanitize_provider_detail(e)}"
            logger.warning(f"[{provider_name}] {detail}")
            warnings.append(self._outcome(provider_name, "metadata", "warning", detail))

        # Step 5: Validate the downloaded file
        validation_result: Optional[ValidationResult] = None
        try:
            validation_result = self._audio_validator.validate(
                file_path=file_path,
                expected_duration_ms=track_metadata.duration_ms or None,  # 0 = unknown
            )

            if not validation_result.is_valid:
                detail = f"Validation failed: {sanitize_provider_detail(validation_result.errors)}"
                logger.warning(f"[{provider_name}] {detail}")
                warnings.append(
                    self._outcome(provider_name, "validation", "warning", detail)
                )
        except Exception as e:
            detail = f"Validation failed with exception: {sanitize_provider_detail(e)}"
            logger.warning(f"[{provider_name}] {detail}")
            warnings.append(
                self._outcome(provider_name, "validation", "warning", detail)
            )

        # Step 6: Clean up old .lrc files and fetch fresh lyrics (non-blocking)
        try:
            from downloader.lyrics import (
                cleanup_misnamed_lrc,
                fetch_and_save_lyrics_if_enabled,
            )

            cleanup_misnamed_lrc(file_path)
            fetch_and_save_lyrics_if_enabled(
                file_path=file_path,
                track_name=track_metadata.title,
                artist_name=track_metadata.artist,
                album_name=track_metadata.album,
                duration_seconds=(
                    track_metadata.duration_ms // 1000
                    if track_metadata.duration_ms
                    else None
                ),
            )
        except Exception as e:
            detail = f"Lyrics fetch failed (non-fatal): {sanitize_provider_detail(e)}"
            logger.debug(f"[{provider_name}] {detail}")
            warnings.append(self._outcome(provider_name, "lyrics", "warning", detail))

        logger.info(
            f"[{provider_name}] Successfully downloaded and processed: "
            f"'{track_metadata.artist} - {track_metadata.title}'"
        )

        return DownloadChainResult(
            success=True,
            file_path=file_path,
            provider_used=provider_name,
            error_message=None,
            track_match=match,
            validation_result=validation_result,
            provider_outcomes=[
                self._outcome(provider_name, "download", "success"),
                *warnings,
            ],
        )

    def _get_expected_extension(self, provider_name: str) -> str:
        """Get expected file extension based on provider and quality."""
        if self._quality_preference in (
            QualityPreference.LOSSLESS,
            QualityPreference.HI_RES,
        ):
            return "flac"

        if provider_name == "qobuz":
            return "mp3" if self._qobuz_use_mp3 else "flac"
        elif provider_name == "youtube":
            return "m4a"
        elif provider_name == "monochrome":
            # Monochrome always returns FLAC (converted to M4A in step 3 for HIGH)
            return "flac"
        else:
            return "m4a"

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a provider-supplied filename component.

        Shares the metadata migration sanitizer so dot-only components cannot
        turn a download directory into a ``..`` traversal segment.
        """
        return sanitize_component(name)

    async def close(self) -> None:
        """Clean up resources."""
        self._providers.clear()
        self._initialized.clear()


# Backward-compatible alias
FallbackDownloader = DownloadProviderChain
