"""Tests for LRClib lyrics fetching and .lrc file matching."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from downloader.lyrics import (
    cleanup_misnamed_lrc,
    extract_title,
    fetch_and_save_lyrics,
    fetch_and_save_lyrics_if_enabled,
    find_existing_lrc,
    normalize_filename,
)


class TestNormalizeFilename:
    """Test accent-stripping and normalization for fuzzy .lrc matching."""

    def test_strips_accents(self):
        assert normalize_filename("Beyoncé") == "beyonce"

    def test_preserves_alphanumeric(self):
        assert normalize_filename("Track 01") == "track 01"

    def test_preserves_hyphens(self):
        assert normalize_filename("My-Song") == "my-song"

    def test_removes_special_chars(self):
        assert normalize_filename("Song (feat. Artist)") == "song feat artist"

    def test_handles_unicode(self):
        assert normalize_filename("Ñoño") == "nono"
        assert normalize_filename("naïve") == "naive"

    def test_empty_string(self):
        assert normalize_filename("") == ""


class TestFindExistingLrc:
    """Test .lrc file discovery with exact and fuzzy matching."""

    def test_exact_match(self, tmp_path):
        audio = tmp_path / "Artist - Song.m4a"
        lrc = tmp_path / "Artist - Song.lrc"
        audio.touch()
        lrc.write_text("[00:00.00] lyrics")

        assert find_existing_lrc(audio) == lrc

    def test_fuzzy_match_accent_stripped(self, tmp_path):
        audio = tmp_path / "Beyoncé - Halo.flac"
        lrc = tmp_path / "Beyonce - Halo.lrc"
        audio.touch()
        lrc.write_text("[00:00.00] lyrics")

        assert find_existing_lrc(audio) == lrc

    def test_no_match(self, tmp_path):
        audio = tmp_path / "Artist - Song.m4a"
        audio.touch()

        assert find_existing_lrc(audio) is None

    def test_no_match_different_song(self, tmp_path):
        audio = tmp_path / "Artist - Song A.m4a"
        lrc = tmp_path / "Artist - Song B.lrc"
        audio.touch()
        lrc.write_text("[00:00.00] lyrics")

        assert find_existing_lrc(audio) is None

    def test_title_match_old_tracknum_convention(self, tmp_path):
        """Old spotdl: '15 Still Learning.lrc' matches 'Halsey - Still Learning.m4a'."""
        audio = tmp_path / "Halsey - Still Learning.m4a"
        lrc = tmp_path / "15 Still Learning.lrc"
        audio.touch()
        lrc.write_text("[00:00.00] lyrics")

        assert find_existing_lrc(audio) == lrc

    def test_title_match_disc_track_convention(self, tmp_path):
        """Old spotdl: '1-08 All The Small Things.lrc' matches audio."""
        audio = tmp_path / "blink-182 - All The Small Things.m4a"
        lrc = tmp_path / "1-08 All The Small Things.lrc"
        audio.touch()
        lrc.write_text("[00:00.00] lyrics")

        assert find_existing_lrc(audio) == lrc

    def test_title_match_skipped_when_ambiguous(self, tmp_path):
        """Multiple .lrc files matching the same title → no match (safety)."""
        audio = tmp_path / "Artist - Song.m4a"
        lrc1 = tmp_path / "01 Song.lrc"
        lrc2 = tmp_path / "05 Song.lrc"
        audio.touch()
        lrc1.write_text("[00:00.00] lyrics v1")
        lrc2.write_text("[00:00.00] lyrics v2")

        assert find_existing_lrc(audio) is None

    def test_nonexistent_directory(self):
        audio = Path("/nonexistent/dir/song.m4a")
        assert find_existing_lrc(audio) is None


class TestExtractTitle:
    """Test title extraction from different naming conventions."""

    def test_strips_track_number(self):
        assert extract_title("15 Still Learning") == "still learning"

    def test_strips_disc_track_number(self):
        assert extract_title("1-08 All The Small Things") == "all the small things"

    def test_strips_artist_prefix(self):
        assert extract_title("Halsey - Still Learning") == "still learning"

    def test_strips_multi_artist_prefix(self):
        assert extract_title("ARMNHMR, Convex, Jex - Title") == "title"

    def test_no_prefix(self):
        assert extract_title("Just A Title") == "just a title"

    def test_both_tracknum_and_artist(self):
        # Edge case: "01 Artist - Title" → strips "01 " → "Artist - Title" → "Title"
        assert extract_title("01 Artist - Title") == "title"


class TestCleanupMisnamedLrc:
    """Test cleanup of old .lrc files with mismatched naming."""

    def test_removes_old_tracknum_lrc(self, tmp_path):
        audio = tmp_path / "Halsey - Still Learning.m4a"
        old_lrc = tmp_path / "15 Still Learning.lrc"
        audio.touch()
        old_lrc.write_text("[00:00.00] lyrics")

        cleanup_misnamed_lrc(audio)

        assert not old_lrc.exists()

    def test_preserves_correctly_named_lrc(self, tmp_path):
        audio = tmp_path / "Halsey - Still Learning.m4a"
        correct_lrc = tmp_path / "Halsey - Still Learning.lrc"
        audio.touch()
        correct_lrc.write_text("[00:00.00] lyrics")

        cleanup_misnamed_lrc(audio)

        assert correct_lrc.exists()

    def test_ignores_unrelated_lrc(self, tmp_path):
        audio = tmp_path / "Halsey - Still Learning.m4a"
        other_lrc = tmp_path / "08 3am.lrc"
        audio.touch()
        other_lrc.write_text("[00:00.00] lyrics")

        cleanup_misnamed_lrc(audio)

        assert other_lrc.exists()

    def test_nonexistent_directory(self):
        audio = Path("/nonexistent/dir/song.m4a")
        cleanup_misnamed_lrc(audio)  # should not raise


class TestFetchAndSaveLyrics:
    """Test LRClib API integration."""

    @patch("downloader.lyrics.requests.get")
    def test_saves_synced_lyrics(self, mock_get, tmp_path):
        audio = tmp_path / "Artist - Song.m4a"
        audio.touch()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "syncedLyrics": "[00:10.00] Hello world",
            "plainLyrics": "Hello world",
        }
        mock_get.return_value = mock_response

        result = fetch_and_save_lyrics(audio, "Song", "Artist")
        assert result is True

        lrc = audio.with_suffix(".lrc")
        assert lrc.exists()
        assert "[00:10.00] Hello world" in lrc.read_text()

    @patch("downloader.lyrics.requests.get")
    def test_falls_back_to_plain_lyrics(self, mock_get, tmp_path):
        audio = tmp_path / "song.m4a"
        audio.touch()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "syncedLyrics": None,
            "plainLyrics": "Just plain text",
        }
        mock_get.return_value = mock_response

        result = fetch_and_save_lyrics(audio, "Song", "Artist")
        assert result is True
        assert "Just plain text" in audio.with_suffix(".lrc").read_text()

    @patch("downloader.lyrics.requests.get")
    def test_returns_false_on_404(self, mock_get, tmp_path):
        audio = tmp_path / "song.m4a"
        audio.touch()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = fetch_and_save_lyrics(audio, "Song", "Artist")
        assert result is False
        assert not audio.with_suffix(".lrc").exists()

    @patch("downloader.lyrics.requests.get")
    def test_returns_false_on_empty_lyrics(self, mock_get, tmp_path):
        audio = tmp_path / "song.m4a"
        audio.touch()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "syncedLyrics": None,
            "plainLyrics": None,
        }
        mock_get.return_value = mock_response

        result = fetch_and_save_lyrics(audio, "Song", "Artist")
        assert result is False

    @patch("downloader.lyrics.requests.get")
    def test_returns_false_on_network_error(self, mock_get, tmp_path):
        import requests

        audio = tmp_path / "song.m4a"
        audio.touch()

        mock_get.side_effect = requests.ConnectionError("timeout")

        result = fetch_and_save_lyrics(audio, "Song", "Artist")
        assert result is False


class TestFetchAndSaveLyricsIfEnabled:
    """Test the settings-gated wrapper."""

    @patch("downloader.lyrics.fetch_and_save_lyrics")
    def test_skips_when_disabled(self, mock_fetch, tmp_path, settings):
        settings.LYRICS_ENABLED = False
        result = fetch_and_save_lyrics_if_enabled(
            tmp_path / "song.m4a", "Song", "Artist"
        )
        assert result is False
        mock_fetch.assert_not_called()

    @patch("downloader.lyrics.fetch_and_save_lyrics", return_value=True)
    def test_calls_when_enabled(self, mock_fetch, tmp_path, settings):
        settings.LYRICS_ENABLED = True
        result = fetch_and_save_lyrics_if_enabled(
            tmp_path / "song.m4a", "Song", "Artist"
        )
        assert result is True
        mock_fetch.assert_called_once()
