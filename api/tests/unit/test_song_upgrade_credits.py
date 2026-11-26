"""The upgrade download path sends the matcher the song's full source credit.

All names and ids in this module are synthetic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from library_manager.artist_credits import record_contributors
from library_manager.models import Artist, Song
from src.services.song_upgrade import SongUpgradeService


@pytest.mark.unit
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upgrade_passes_full_credit_lead_first() -> None:
    from asgiref.sync import sync_to_async

    def setup() -> int:
        lead = Artist.objects.create(name="Upgrade Lead", deezer_id=71)
        guest = Artist.objects.create(name="Upgrade Guest", deezer_id=72)
        song = Song.objects.create(
            name="Synthetic",
            gid="u" * 22,
            deezer_id=7300,
            primary_artist=lead,
            downloaded=True,
            bitrate=128,
        )
        record_contributors(song, [guest, lead])
        return int(song.pk)

    song_id = await sync_to_async(setup)()
    failed = MagicMock(success=False, file_path=None, error_message="stop")
    downloader = MagicMock()
    downloader.download_track = AsyncMock(return_value=failed)

    with patch(
        "downloader.providers.fallback.FallbackDownloader", return_value=downloader
    ):
        await SongUpgradeService().attempt_upgrade(song_id)

    metadata = downloader.download_track.await_args.args[0]
    assert metadata.artist == "Upgrade Lead, Upgrade Guest"
    assert metadata.album_artist == "Upgrade Lead"
