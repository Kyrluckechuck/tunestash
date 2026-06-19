# pylint: disable=protected-access

from unittest.mock import patch

from downloader.providers.youtube import YouTubeMusicProvider


def test_search_uses_youtube_music_song_catalog():
    catalog_audio = {
        "videoId": "jjMu-5XI1dY",
        "title": "Oh...Canada (Dirty version)",
        "artists": [{"name": "Classified"}],
        "album": {"name": "Self Explanatory"},
        "duration_seconds": 203,
    }

    with patch("ytmusicapi.YTMusic") as ytmusic:
        ytmusic.return_value.search.return_value = [catalog_audio]
        match = YouTubeMusicProvider()._search_track_sync(
            title="Oh...Canada",
            artist="Classified",
            album="Self Explanatory",
            duration_ms=202_000,
        )

    ytmusic.return_value.search.assert_called_once_with(
        "Classified Oh...Canada", filter="songs", limit=10
    )
    assert match is not None
    assert match.provider_track_id == "jjMu-5XI1dY"
    assert match.title == "Oh...Canada (Dirty version)"
    assert match.artist == "Classified"
    assert match.duration_ms == 203_000


def test_search_rejects_wrong_duration_catalog_song():
    with patch("ytmusicapi.YTMusic") as ytmusic:
        ytmusic.return_value.search.return_value = [
            {
                "videoId": "official-video",
                "title": "Oh...Canada",
                "artists": [{"name": "Classified"}],
                "duration_seconds": 230,
            }
        ]
        match = YouTubeMusicProvider()._search_track_sync(
            title="Oh...Canada",
            artist="Classified",
            duration_ms=202_000,
        )

    assert match is None
