from src.queuetip.resolution.candidate import TrackCandidate
from src.services.catalog_search import CatalogSearchTrack


def test_track_candidate_defaults():
    c = TrackCandidate(track_name="Maps", artist_name="Maroon 5", source="spotify")
    assert c.isrc is None
    assert c.source_id is None
    assert c.all_artists == []


def test_track_candidate_from_deezer_catalog_track():
    track = CatalogSearchTrack(
        provider_id="123",
        name="Maps",
        external_url=None,
        artist_name="Maroon 5",
        artist_provider_id="a1",
        album_name="V",
        album_provider_id="b1",
        duration_ms=200000,
        in_library=False,
        local_id=None,
    )
    c = TrackCandidate.from_deezer_catalog_track(track)
    assert c.track_name == "Maps"
    assert c.artist_name == "Maroon 5"
    assert c.source == "deezer"
    assert c.source_id == "123"
    assert c.all_artists == ["Maroon 5"]
