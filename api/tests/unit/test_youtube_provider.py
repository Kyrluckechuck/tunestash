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


def test_search_accepts_punctuation_artist_alias():
    with patch("ytmusicapi.YTMusic") as ytmusic:
        ytmusic.return_value.search.return_value = [
            {
                "videoId": "acdc",
                "title": "Thunderstruck",
                "artists": [{"name": "ACDC"}],
                "duration_seconds": 292,
            }
        ]
        match = YouTubeMusicProvider()._search_track_sync(
            title="Thunderstruck",
            artist="AC/DC",
            duration_ms=292_000,
        )

    assert match is not None
    assert match.provider_track_id == "acdc"


def test_search_rejects_pink_floyd_for_pink():
    with patch("ytmusicapi.YTMusic") as ytmusic:
        ytmusic.return_value.search.return_value = [
            {
                "videoId": "pink-floyd",
                "title": "So What",
                "artists": [{"name": "Pink Floyd"}],
            }
        ]
        match = YouTubeMusicProvider()._search_track_sync(
            title="So What",
            artist="Pink",
        )

    assert match is None


def test_search_rejects_unrelated_artist_without_duration():
    # Production regression: CHEZ "Avoidant" matched Detz "Avoidance".
    with patch("ytmusicapi.YTMusic") as ytmusic:
        ytmusic.return_value.search.return_value = [
            {
                "videoId": "wrong-artist",
                "title": "Avoidance",
                "artists": [{"name": "Detz"}],
            }
        ]
        match = YouTubeMusicProvider()._search_track_sync(
            title="Avoidant",
            artist="CHEZ",
        )

    assert match is None


def test_search_rejects_piano_version_cover_without_duration():
    # Production regression: Jon Pumper "Change (Piano Version)" matched jame.
    with patch("ytmusicapi.YTMusic") as ytmusic:
        ytmusic.return_value.search.return_value = [
            {
                "videoId": "wrong-version",
                "title": "Change",
                "artists": [{"name": "jame"}],
            }
        ]
        match = YouTubeMusicProvider()._search_track_sync(
            title="Change (Piano Version)",
            artist="Jon Pumper",
        )

    assert match is None


def test_search_retains_collaborator_credit():
    with patch("ytmusicapi.YTMusic") as ytmusic:
        ytmusic.return_value.search.return_value = [
            {
                "videoId": "collab",
                "title": "Levitating",
                "artists": [{"name": "Dua Lipa"}, {"name": "DaBaby"}],
                "duration_seconds": 203,
            }
        ]
        match = YouTubeMusicProvider()._search_track_sync(
            title="Levitating",
            artist="Dua Lipa",
            duration_ms=203_000,
        )

    assert match is not None
    assert match.provider_track_id == "collab"
    assert match.artist == "Dua Lipa • DaBaby"


def test_search_rejects_mix_cut_variant():
    with patch("ytmusicapi.YTMusic") as ytmusic:
        ytmusic.return_value.search.return_value = [
            {
                "videoId": "mix-cut",
                "title": "Mix Cut",
                "artists": [{"name": "Fatum"}],
            }
        ]
        match = YouTubeMusicProvider()._search_track_sync(
            title="Mixed",
            artist="Fatum",
        )

    assert match is None


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
