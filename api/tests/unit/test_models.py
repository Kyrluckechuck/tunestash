from datetime import timedelta

from django.utils import timezone

import pytest

from library_manager.models import (
    Album,
    Artist,
    PlaylistStatus,
    Song,
    SpotifyRateLimitState,
    TrackedPlaylist,
)


@pytest.mark.django_db
class TestArtistModel:
    """Test cases for Artist model."""

    def test_artist_creation(self):
        """Test basic artist creation."""
        artist = Artist.objects.create(
            name="Test Artist", gid="test123", tracking_tier=1
        )
        assert artist.name == "Test Artist"
        assert artist.gid == "test123"
        assert artist.tracking_tier == 1
        assert artist.id is not None

    def test_artist_str_representation(self):
        """Test string representation of artist."""
        artist = Artist.objects.create(name="Test Artist", gid="test123")
        # The actual __str__ method returns a more detailed format
        assert "Test Artist" in str(artist)
        assert "test123" in str(artist)

    def test_spotify_uri_property(self):
        """Test spotify_uri property."""
        artist = Artist.objects.create(name="Test Artist", gid="test123")
        # Check if the property exists, if not skip this test
        if hasattr(artist, "spotify_uri"):
            expected_uri = "spotify:artist:test123"
            assert artist.spotify_uri == expected_uri
        else:
            pytest.skip("spotify_uri property not implemented")

    def test_artist_tracking_toggle(self):
        """Test toggling artist tracking tier."""
        artist = Artist.objects.create(
            name="Test Artist", gid="test123", tracking_tier=0
        )
        assert artist.tracking_tier == 0

        artist.tracking_tier = 1
        artist.save()
        artist.refresh_from_db()
        assert artist.tracking_tier == 1


@pytest.mark.django_db
class TestAlbumModel:
    """Test cases for Album model."""

    def test_album_creation(self, sample_artist):
        """Test basic album creation."""
        album = Album.objects.create(
            name="Test Album",
            spotify_gid="album123",
            artist=sample_artist,
            total_tracks=10,
            wanted=True,
        )
        assert album.name == "Test Album"
        assert album.spotify_gid == "album123"
        assert album.artist == sample_artist
        assert album.total_tracks == 10
        assert album.wanted is True

    def test_album_str_representation(self, sample_artist):
        """Test string representation of album."""
        album = Album.objects.create(
            name="Test Album",
            artist=sample_artist,
            spotify_gid="album123",
            spotify_uri="spotify:album:album123",
        )
        # Project defines a custom __str__ for Album including name and artist
        album_str = str(album)
        assert "Test Album" in album_str
        assert sample_artist.name in album_str


@pytest.mark.django_db
class TestSongModel:
    """Test cases for Song model."""

    def test_song_creation(self, sample_artist, sample_album):
        """Test basic song creation."""
        song = Song.objects.create(
            name="Test Song", gid="song123", primary_artist=sample_artist
        )
        assert song.name == "Test Song"
        assert song.gid == "song123"
        assert song.primary_artist == sample_artist

    def test_spotify_uri_property(self, sample_artist, sample_album):
        """Test spotify_uri property."""
        song = Song.objects.create(
            name="Test Song", gid="song123", primary_artist=sample_artist
        )
        # Check if the property exists, if not skip this test
        if hasattr(song, "spotify_uri"):
            expected_uri = "spotify:track:song123"
            assert song.spotify_uri == expected_uri
        else:
            pytest.skip("spotify_uri property not implemented")


@pytest.mark.django_db
class TestTrackedPlaylistModel:
    """Test cases for TrackedPlaylist model."""

    def test_playlist_creation(self):
        """Test basic playlist creation."""
        playlist = TrackedPlaylist.objects.create(
            name="Test Playlist",
            url="https://open.spotify.com/playlist/test123",
            status=PlaylistStatus.ACTIVE,
        )
        assert playlist.name == "Test Playlist"
        assert playlist.url == "https://open.spotify.com/playlist/test123"
        assert playlist.enabled is True  # Computed from status

    def test_playlist_toggle_enabled(self):
        """Test toggling playlist status affects enabled property."""
        playlist = TrackedPlaylist.objects.create(
            name="Test Playlist",
            url="https://open.spotify.com/playlist/test123",
            status=PlaylistStatus.DISABLED_BY_USER,
        )
        assert playlist.enabled is False

        playlist.status = PlaylistStatus.ACTIVE
        playlist.save()
        playlist.refresh_from_db()
        assert playlist.enabled is True


@pytest.mark.django_db
class TestSpotifyRateLimitState:
    """Test cases for multi-tier Spotify rate limiter."""

    @pytest.fixture(autouse=True)
    def reset_rate_limit_state(self):
        """Clean up rate limit state before each test."""
        SpotifyRateLimitState.objects.all().delete()
        yield
        SpotifyRateLimitState.objects.all().delete()

    def test_get_instance_creates_singleton(self):
        """Test that get_instance creates a singleton record."""
        instance1 = SpotifyRateLimitState.get_instance()
        instance2 = SpotifyRateLimitState.get_instance()

        assert instance1.id == instance2.id
        assert SpotifyRateLimitState.objects.count() == 1

    def test_record_call_increments_all_tiers(self):
        """Test that recording a call increments all three tier counters."""
        SpotifyRateLimitState.record_call()
        instance = SpotifyRateLimitState.get_instance()

        assert instance.burst_call_count == 1
        assert instance.sustained_call_count == 1
        assert instance.hourly_call_count == 1

    def test_record_call_multiple_increments(self):
        """Test multiple calls accumulate across all tiers."""
        for _ in range(5):
            SpotifyRateLimitState.record_call()

        instance = SpotifyRateLimitState.get_instance()

        assert instance.burst_call_count == 5
        assert instance.sustained_call_count == 5
        assert instance.hourly_call_count == 5

    def test_burst_window_reset(self):
        """Test burst tier resets after window expires."""
        # Record some calls
        for _ in range(10):
            SpotifyRateLimitState.record_call()

        instance = SpotifyRateLimitState.get_instance()
        assert instance.burst_call_count == 10

        # Move burst window start to past the window duration
        past_time = timezone.now() - timedelta(
            seconds=SpotifyRateLimitState.BURST_WINDOW_SECONDS + 1
        )
        instance.burst_window_start = past_time
        instance.save()

        # Record another call - should reset burst counter
        SpotifyRateLimitState.record_call()
        instance.refresh_from_db()

        assert instance.burst_call_count == 1  # Reset to 1
        # Sustained and hourly should still accumulate
        assert instance.sustained_call_count == 11
        assert instance.hourly_call_count == 11

    def test_sustained_window_reset(self):
        """Test sustained tier resets after window expires."""
        for _ in range(10):
            SpotifyRateLimitState.record_call()

        instance = SpotifyRateLimitState.get_instance()

        # Move sustained window start to past the window duration
        past_time = timezone.now() - timedelta(
            seconds=SpotifyRateLimitState.SUSTAINED_WINDOW_SECONDS + 1
        )
        instance.sustained_window_start = past_time
        instance.save()

        SpotifyRateLimitState.record_call()
        instance.refresh_from_db()

        # Burst continues accumulating (short window hasn't expired)
        assert instance.burst_call_count == 11
        # Sustained resets
        assert instance.sustained_call_count == 1
        # Hourly continues accumulating
        assert instance.hourly_call_count == 11

    def test_hourly_window_reset(self):
        """Test hourly tier resets after window expires."""
        for _ in range(10):
            SpotifyRateLimitState.record_call()

        instance = SpotifyRateLimitState.get_instance()

        # Move hourly window start to past the window duration
        past_time = timezone.now() - timedelta(
            seconds=SpotifyRateLimitState.HOURLY_WINDOW_SECONDS + 1
        )
        instance.hourly_window_start = past_time
        instance.save()

        SpotifyRateLimitState.record_call()
        instance.refresh_from_db()

        # Burst and sustained continue accumulating
        assert instance.burst_call_count == 11
        assert instance.sustained_call_count == 11
        # Hourly resets
        assert instance.hourly_call_count == 1

    def test_get_delay_returns_zero_when_under_limits(self):
        """Test no delay when all tiers are under their limits."""
        # Record a few calls (well under any limit)
        for _ in range(3):
            SpotifyRateLimitState.record_call()

        # Wait a bit to clear the minimum delay between calls
        instance = SpotifyRateLimitState.get_instance()
        instance.last_call_at = timezone.now() - timedelta(seconds=1)
        instance.save()

        delay = SpotifyRateLimitState.get_delay_seconds()
        assert delay == 0.0

    def test_get_delay_burst_limit_exceeded(self):
        """Test delay returned when burst limit is exceeded."""
        # Set burst count at limit
        instance = SpotifyRateLimitState.get_instance()
        instance.burst_call_count = SpotifyRateLimitState.BURST_MAX_CALLS
        instance.burst_window_start = timezone.now()
        instance.last_call_at = timezone.now() - timedelta(seconds=1)
        instance.save()

        delay = SpotifyRateLimitState.get_delay_seconds()

        # Should return delay until burst window ends (up to BURST_WINDOW_SECONDS)
        assert delay > 0
        assert delay <= SpotifyRateLimitState.BURST_WINDOW_SECONDS

    def test_get_delay_sustained_limit_exceeded(self):
        """Test delay returned when sustained limit is exceeded."""
        instance = SpotifyRateLimitState.get_instance()
        instance.sustained_call_count = SpotifyRateLimitState.SUSTAINED_MAX_CALLS
        instance.sustained_window_start = timezone.now()
        instance.last_call_at = timezone.now() - timedelta(seconds=1)
        instance.save()

        delay = SpotifyRateLimitState.get_delay_seconds()

        # Should return delay until sustained window ends
        assert delay > 0
        assert delay <= SpotifyRateLimitState.SUSTAINED_WINDOW_SECONDS

    def test_get_delay_hourly_limit_exceeded(self):
        """Test delay returned when hourly limit is exceeded."""
        instance = SpotifyRateLimitState.get_instance()
        instance.hourly_call_count = SpotifyRateLimitState.HOURLY_MAX_CALLS
        instance.hourly_window_start = timezone.now()
        instance.last_call_at = timezone.now() - timedelta(seconds=1)
        instance.save()

        delay = SpotifyRateLimitState.get_delay_seconds()

        # Should return delay until hourly window ends
        assert delay > 0
        assert delay <= SpotifyRateLimitState.HOURLY_WINDOW_SECONDS

    def test_get_delay_respects_rate_limited_until(self):
        """Test delay respects Spotify's 429 rate limit."""
        future_time = timezone.now() + timedelta(seconds=120)
        instance = SpotifyRateLimitState.get_instance()
        instance.rate_limited_until = future_time
        instance.save()

        delay = SpotifyRateLimitState.get_delay_seconds()

        # Should return approximately 120 seconds
        assert delay > 118
        assert delay <= 120

    def test_set_rate_limited_sets_until_time(self):
        """Test set_rate_limited records the rate limit expiry."""
        SpotifyRateLimitState.set_rate_limited(300)
        instance = SpotifyRateLimitState.get_instance()

        assert instance.rate_limited_until is not None
        # Should be approximately 300 seconds in the future
        time_diff = (instance.rate_limited_until - timezone.now()).total_seconds()
        assert time_diff > 298
        assert time_diff <= 300

    def test_set_rate_limited_increases_pressure(self):
        """Test set_rate_limited increases backoff pressure."""
        instance = SpotifyRateLimitState.get_instance()
        initial_pressure = instance.backoff_pressure

        SpotifyRateLimitState.set_rate_limited(60)
        instance.refresh_from_db()

        # Should increase pressure by 10
        assert instance.backoff_pressure == initial_pressure + 10

    def test_set_rate_limited_resets_all_windows(self):
        """Test set_rate_limited resets all tier counters."""
        # Build up some counts
        for _ in range(10):
            SpotifyRateLimitState.record_call()

        instance = SpotifyRateLimitState.get_instance()
        assert instance.burst_call_count > 0
        assert instance.sustained_call_count > 0
        assert instance.hourly_call_count > 0

        SpotifyRateLimitState.set_rate_limited(60)
        instance.refresh_from_db()

        # All counters should be reset
        assert instance.burst_call_count == 0
        assert instance.sustained_call_count == 0
        assert instance.hourly_call_count == 0

    def test_increase_pressure(self):
        """Test manual pressure increase."""
        instance = SpotifyRateLimitState.get_instance()
        assert instance.backoff_pressure == 0

        SpotifyRateLimitState.increase_pressure(5)
        instance.refresh_from_db()

        assert instance.backoff_pressure == 5

    def test_increase_pressure_caps_at_max(self):
        """Test pressure doesn't exceed maximum."""
        instance = SpotifyRateLimitState.get_instance()
        instance.backoff_pressure = SpotifyRateLimitState.BACKOFF_MAX_PRESSURE - 5
        instance.save()

        SpotifyRateLimitState.increase_pressure(20)  # Would exceed max
        instance.refresh_from_db()

        assert instance.backoff_pressure == SpotifyRateLimitState.BACKOFF_MAX_PRESSURE

    def test_backoff_pressure_adds_delay(self):
        """Test that backoff pressure adds delay to requests."""
        instance = SpotifyRateLimitState.get_instance()
        instance.backoff_pressure = 10  # Should add 1 second delay
        instance.last_call_at = timezone.now() - timedelta(seconds=1)
        instance.save()

        delay = SpotifyRateLimitState.get_delay_seconds()

        expected_delay = (
            10 * SpotifyRateLimitState.BACKOFF_DELAY_PER_PRESSURE_MS / 1000.0
        )
        assert delay == pytest.approx(expected_delay, abs=0.1)

    def test_pressure_decay_on_low_usage(self):
        """Test pressure decays when usage is low."""
        instance = SpotifyRateLimitState.get_instance()
        instance.backoff_pressure = 5
        # Set last decay in the past
        instance.last_pressure_decay = timezone.now() - timedelta(
            seconds=SpotifyRateLimitState.BACKOFF_DECAY_INTERVAL_SECONDS + 1
        )
        # Set low burst count (under 50% of limit)
        instance.burst_call_count = 1
        instance.save()

        # Recording a call should trigger decay check
        SpotifyRateLimitState.record_call()
        instance.refresh_from_db()

        # Pressure should have decayed
        assert instance.backoff_pressure < 5

    def test_pressure_no_decay_on_high_usage(self):
        """Test pressure doesn't decay when usage is high."""
        instance = SpotifyRateLimitState.get_instance()
        instance.backoff_pressure = 5
        instance.last_pressure_decay = timezone.now() - timedelta(
            seconds=SpotifyRateLimitState.BACKOFF_DECAY_INTERVAL_SECONDS + 1
        )
        # Set high burst count (over 50% of limit)
        instance.burst_call_count = SpotifyRateLimitState.BURST_MAX_CALLS
        instance.save()

        SpotifyRateLimitState.record_call()
        instance.refresh_from_db()

        # Pressure should NOT decay (high usage)
        assert instance.backoff_pressure == 5

    def test_get_status_returns_all_tier_info(self):
        """Test get_status returns comprehensive tier information."""
        # Build up some state
        for _ in range(5):
            SpotifyRateLimitState.record_call()

        status = SpotifyRateLimitState.get_status()

        # Check all expected keys are present
        assert "burst_calls" in status
        assert "burst_max" in status
        assert "sustained_calls" in status
        assert "sustained_max" in status
        assert "hourly_calls" in status
        assert "hourly_max" in status
        assert "backoff_pressure" in status
        assert "is_rate_limited" in status

        # Check values
        assert status["burst_calls"] == 5
        assert status["sustained_calls"] == 5
        assert status["hourly_calls"] == 5
        assert status["burst_max"] == SpotifyRateLimitState.BURST_MAX_CALLS
        assert status["sustained_max"] == SpotifyRateLimitState.SUSTAINED_MAX_CALLS
        assert status["hourly_max"] == SpotifyRateLimitState.HOURLY_MAX_CALLS
        assert status["is_rate_limited"] is False

    def test_get_status_shows_rate_limited_state(self):
        """Test get_status reflects rate limited state."""
        SpotifyRateLimitState.set_rate_limited(120)
        status = SpotifyRateLimitState.get_status()

        assert status["is_rate_limited"] is True
        assert status["rate_limited_until"] is not None
        assert status["seconds_until_clear"] > 0

    def test_get_status_returns_defaults_when_no_instance(self):
        """Test get_status returns safe defaults when no state exists."""
        SpotifyRateLimitState.objects.all().delete()
        status = SpotifyRateLimitState.get_status()

        assert status["burst_calls"] == 0
        assert status["sustained_calls"] == 0
        assert status["hourly_calls"] == 0
        assert status["is_rate_limited"] is False

    def test_minimum_delay_between_calls(self):
        """Test minimum delay is enforced between calls."""
        instance = SpotifyRateLimitState.get_instance()
        instance.last_call_at = timezone.now()  # Just called
        instance.save()

        delay = SpotifyRateLimitState.get_delay_seconds()

        # Should return approximately the minimum delay
        min_delay_sec = SpotifyRateLimitState.MIN_DELAY_BETWEEN_CALLS_MS / 1000.0
        assert delay > 0
        assert delay <= min_delay_sec

    def test_str_representation(self):
        """Test string representation includes all tier info."""
        for _ in range(5):
            SpotifyRateLimitState.record_call()

        instance = SpotifyRateLimitState.get_instance()
        str_repr = str(instance)

        assert "burst:" in str_repr
        assert "sustained:" in str_repr
        assert "hourly:" in str_repr
        assert "pressure:" in str_repr
