"""Factory Boy factories for test data creation."""

import random
from datetime import timezone

from factory import Faker, LazyFunction, Sequence, SubFactory
from factory.django import DjangoModelFactory

from library_manager.models import (
    Album,
    Artist,
    ExternalList,
    ExternalListSource,
    ExternalListStatus,
    ExternalListType,
    PlaylistStatus,
    Song,
    TaskHistory,
    TrackedPlaylist,
)


class ArtistFactory(DjangoModelFactory):
    """Factory for creating Artist instances."""

    class Meta:
        model = Artist

    name = Faker("name")
    gid = Sequence(lambda n: f"{n:032x}")  # Generate proper hexadecimal GIDs
    tracking_tier = 0
    added_at = Faker("date_time", tzinfo=timezone.utc)
    last_synced_at = Faker("date_time", tzinfo=timezone.utc)


class AlbumFactory(DjangoModelFactory):
    """Factory for creating Album instances."""

    class Meta:
        model = Album

    name = Faker("sentence", nb_words=3)
    spotify_gid = Sequence(lambda n: f"album_{n}")
    spotify_uri = Sequence(lambda n: f"spotify:album:album_{n}")
    total_tracks = Faker("random_int", min=1, max=20)
    downloaded = Faker("boolean")
    wanted = Faker("boolean")
    album_type = Faker("random_element", elements=["album", "single", "compilation"])
    album_group = Faker("random_element", elements=["album", "single", "compilation"])
    artist = SubFactory(ArtistFactory)


class SongFactory(DjangoModelFactory):
    """Factory for creating Song instances."""

    class Meta:
        model = Song

    name = Faker("sentence", nb_words=4)
    gid = Sequence(lambda n: f"song_{n}")
    created_at = Faker("date_time", tzinfo=timezone.utc)
    failed_count = Faker("random_int", min=0, max=5)
    bitrate = Faker("random_int", min=128, max=320)
    unavailable = Faker("boolean")
    file_path = Faker("file_path")
    downloaded = Faker("boolean")
    primary_artist = SubFactory(ArtistFactory)


class TrackedPlaylistFactory(DjangoModelFactory):
    """Factory for creating TrackedPlaylist instances."""

    class Meta:
        model = TrackedPlaylist

    name = Faker("sentence", nb_words=3)
    url = Sequence(lambda n: f"https://open.spotify.com/playlist/playlist_{n}")
    status = Faker(
        "random_element",
        elements=[
            PlaylistStatus.ACTIVE,
            PlaylistStatus.DISABLED_BY_USER,
        ],
    )
    auto_track_tier = LazyFunction(lambda: random.choice([None, 1, 2]))
    last_synced_at = Faker("date_time", tzinfo=timezone.utc)


class TaskHistoryFactory(DjangoModelFactory):
    """Factory for creating TaskHistory instances."""

    class Meta:
        model = TaskHistory

    task_id = Sequence(lambda n: f"task_{n}")
    type = Faker("random_element", elements=["SYNC", "DOWNLOAD", "FETCH"])
    entity_id = Sequence(lambda n: f"entity_{n}")
    entity_type = Faker("random_element", elements=["ARTIST", "ALBUM", "PLAYLIST"])
    status = Faker(
        "random_element", elements=["RUNNING", "COMPLETED", "FAILED", "PENDING"]
    )
    started_at = Faker("date_time", tzinfo=timezone.utc)
    completed_at = Faker("date_time", tzinfo=timezone.utc)
    error_message = Faker("sentence")
    duration_seconds = Faker("random_int", min=1, max=3600)
    progress_percentage = Faker("random_int", min=0, max=100)
    log_messages = Faker("sentences", nb=3)


# Specialized factories for common test scenarios
class TrackedArtistFactory(ArtistFactory):
    """Factory for creating tracked artists."""

    tracking_tier = 1


class UntrackedArtistFactory(ArtistFactory):
    """Factory for creating untracked artists."""

    tracking_tier = 0


class DownloadedAlbumFactory(AlbumFactory):
    """Factory for creating downloaded albums."""

    downloaded = True
    wanted = True


class WantedAlbumFactory(AlbumFactory):
    """Factory for creating wanted but not downloaded albums."""

    downloaded = False
    wanted = True


class EnabledPlaylistFactory(TrackedPlaylistFactory):
    """Factory for creating enabled (active) playlists."""

    status = PlaylistStatus.ACTIVE
    auto_track_tier = 1


class DisabledPlaylistFactory(TrackedPlaylistFactory):
    """Factory for creating disabled playlists."""

    status = PlaylistStatus.DISABLED_BY_USER


class CompletedTaskFactory(TaskHistoryFactory):
    """Factory for creating completed tasks."""

    status = "COMPLETED"
    completed_at = Faker("date_time", tzinfo=timezone.utc)
    duration_seconds = Faker("random_int", min=1, max=300)
    progress_percentage = 100


class FailedTaskFactory(TaskHistoryFactory):
    """Factory for creating failed tasks."""

    status = "FAILED"
    completed_at = Faker("date_time", tzinfo=timezone.utc)
    error_message = Faker("sentence")


class ExternalListFactory(DjangoModelFactory):
    """Factory for creating ExternalList instances."""

    class Meta:
        model = ExternalList

    name = Sequence(lambda n: f"External List {n}")
    source = ExternalListSource.LASTFM
    list_type = ExternalListType.LOVED_TRACKS
    username = Faker("user_name")
    status = ExternalListStatus.ACTIVE


class ActiveExternalListFactory(ExternalListFactory):
    """Factory for creating active external lists."""

    status = ExternalListStatus.ACTIVE


class DisabledExternalListFactory(ExternalListFactory):
    """Factory for creating disabled external lists."""

    status = ExternalListStatus.DISABLED_BY_USER
