"""Tasks for upgrading low-quality songs to higher quality versions."""

import asyncio
from typing import Any

from celery_app import app as celery_app

from .core import logger


@celery_app.task(
    bind=True,
    name="library_manager.tasks.upgrade_low_quality_songs",
)
def upgrade_low_quality_songs(
    self: Any,
    max_songs: int = 50,
    max_bitrate: int = 220,
) -> dict:
    """
    One-off task to upgrade low-quality songs using Tidal/Qobuz.

    Finds songs below the bitrate threshold and attempts to download
    higher quality versions from fallback providers.

    Args:
        max_songs: Maximum number of songs to process in this run
        max_bitrate: Only upgrade songs below this bitrate (default 220kbps)

    Returns:
        Dict with statistics about the upgrade run
    """
    from src.services.song_upgrade import SongUpgradeService

    logger.info(
        f"[UPGRADE] Starting upgrade task: max_songs={max_songs}, "
        f"max_bitrate={max_bitrate}"
    )

    service = SongUpgradeService(max_bitrate=max_bitrate)

    # Get songs to upgrade
    songs = asyncio.get_event_loop().run_until_complete(
        service.get_low_quality_songs(limit=max_songs)
    )

    if not songs:
        logger.info("[UPGRADE] No songs eligible for upgrade")
        return {
            "processed": 0,
            "upgraded": 0,
            "failed": 0,
            "api_errors": 0,
        }

    logger.info(f"[UPGRADE] Found {len(songs)} songs to attempt upgrade")

    # Track statistics
    stats = {
        "processed": 0,
        "upgraded": 0,
        "failed": 0,
        "api_errors": 0,
    }

    for song in songs:
        try:
            result = asyncio.get_event_loop().run_until_complete(
                service.attempt_upgrade(song.id)
            )

            stats["processed"] += 1

            if result.success:
                stats["upgraded"] += 1
                logger.info(
                    f"[UPGRADE] ✓ Upgraded song {song.id}: "
                    f"{result.original_bitrate}kbps -> {result.new_bitrate}kbps"
                )
            elif result.error_message and "API error" in result.error_message:
                stats["api_errors"] += 1
                logger.warning(
                    f"[UPGRADE] API error for song {song.id}, "
                    f"stopping to allow retry later: {result.error_message}"
                )
                # Stop processing on API errors to allow retry later
                break
            else:
                stats["failed"] += 1
                logger.info(
                    f"[UPGRADE] Song {song.id} not upgradeable: {result.error_message}"
                )

        except Exception as e:
            logger.error(f"[UPGRADE] Exception processing song {song.id}: {e}")
            stats["api_errors"] += 1
            # Stop on exceptions to avoid hammering a broken API
            break

    logger.info(
        f"[UPGRADE] Task complete: {stats['upgraded']}/{stats['processed']} upgraded, "
        f"{stats['failed']} failed, {stats['api_errors']} API errors"
    )

    return stats
