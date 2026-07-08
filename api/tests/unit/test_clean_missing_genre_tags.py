"""Tests for the missing genre tag cleanup command."""

from unittest.mock import MagicMock

import pytest

from library_manager.management.commands import clean_missing_genre_tags


class TestCleanMissingGenreTags:
    """Tests for audio genre tag cleanup helpers."""

    @pytest.mark.unit
    def test_clean_audio_tags_removes_missing_mp4_genre(self):
        """MP4 missing genre placeholders are removed and saved when applying."""
        tags = {"\xa9gen": ["[Missing Genre]"]}
        audio = MagicMock()
        audio.__contains__ = lambda self, key: key in tags
        audio.__getitem__ = lambda self, key: tags[key]
        audio.__delitem__ = lambda self, key: tags.__delitem__(key)

        result = clean_missing_genre_tags.Command().clean_audio_tags(
            audio, ".m4a", apply=True
        )

        assert result == clean_missing_genre_tags.TagCleanupResult(
            affected=True,
            changed=True,
            removed_keys=("\xa9gen",),
        )
        assert "\xa9gen" not in tags
        audio.save.assert_called_once()

    @pytest.mark.unit
    def test_clean_audio_tags_replaces_missing_genre_when_genres_are_available(self):
        """Placeholder genres are replaced when resolved genre data exists."""
        tags = {"GENRE": ["[Missing Genre]"]}
        audio = MagicMock()
        audio.__contains__ = lambda self, key: key in tags
        audio.__getitem__ = lambda self, key: tags[key]
        audio.__setitem__ = lambda self, key, value: tags.__setitem__(key, value)
        audio.__delitem__ = lambda self, key: tags.__delitem__(key)

        result = clean_missing_genre_tags.Command().clean_audio_tags(
            audio,
            ".flac",
            apply=True,
            replacement_genres=("Pop", "Films/Games"),
        )

        assert result == clean_missing_genre_tags.TagCleanupResult(
            affected=True,
            changed=True,
            removed_keys=("GENRE",),
            replacement_genres=("Pop", "Films/Games"),
        )
        assert tags["GENRE"] == ["Pop", "Films/Games"]
        audio.save.assert_called_once()

    @pytest.mark.unit
    def test_clean_audio_tags_dry_run_does_not_mutate(self):
        """Dry-run reports affected files without changing tags."""
        tags = {"GENRE": ["[Missing Genre]"]}
        audio = MagicMock()
        audio.__contains__ = lambda self, key: key in tags
        audio.__getitem__ = lambda self, key: tags[key]
        audio.__delitem__ = lambda self, key: tags.__delitem__(key)

        result = clean_missing_genre_tags.Command().clean_audio_tags(
            audio, ".flac", apply=False
        )

        assert result == clean_missing_genre_tags.TagCleanupResult(
            affected=True,
            changed=False,
            removed_keys=("GENRE",),
        )
        assert tags["GENRE"] == ["[Missing Genre]"]
        audio.save.assert_not_called()

    @pytest.mark.unit
    def test_clean_audio_tags_ignores_real_genre(self):
        """Normal genres are left alone."""
        tags = {"GENRE": ["Pop"]}
        audio = MagicMock()
        audio.__contains__ = lambda self, key: key in tags
        audio.__getitem__ = lambda self, key: tags[key]

        result = clean_missing_genre_tags.Command().clean_audio_tags(
            audio, ".flac", apply=True
        )

        assert result == clean_missing_genre_tags.TagCleanupResult(
            affected=False,
            changed=False,
            removed_keys=(),
        )
        assert tags["GENRE"] == ["Pop"]
        audio.save.assert_not_called()
