"""Base classes for metadata providers (search + lookup)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ArtistResult:
    """Artist metadata from an external provider."""

    name: str
    deezer_id: int | None = None
    youtube_id: str | None = None
    image_url: str | None = None
    genres: list[str] = field(default_factory=list)


@dataclass
class AlbumResult:
    """Album metadata from an external provider."""

    name: str
    artist_name: str
    deezer_id: int | None = None
    youtube_id: str | None = None
    image_url: str | None = None
    total_tracks: int | None = None
    release_date: str | None = None
    album_type: str | None = None
    album_group: str | None = None
    artist_deezer_id: int | None = None
    label: str | None = None
    genres: list[str] = field(default_factory=list)


@dataclass
class TrackResult:
    """Track metadata from an external provider."""

    name: str
    artist_name: str
    album_name: str | None = None
    deezer_id: int | None = None
    youtube_id: str | None = None
    isrc: str | None = None
    duration_ms: int = 0
    track_number: int | None = None
    disc_number: int | None = None
    artist_deezer_id: int | None = None
    album_deezer_id: int | None = None


@dataclass
class PlaylistResult:
    """Playlist metadata from an external provider."""

    name: str
    deezer_id: int | None = None
    description: str | None = None
    creator_name: str | None = None
    track_count: int = 0
    checksum: str | None = None
    image_url: str | None = None


class MetadataProvider(ABC):
    """Abstract base for metadata providers (Deezer, YouTube Music, etc.).

    All methods are synchronous — async wrapping is done by MetadataService.
    Returns simple dataclasses, not Django models.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider display name."""

    @abstractmethod
    def search_artists(self, query: str, limit: int = 10) -> list[ArtistResult]:
        """Search for artists by name."""

    @abstractmethod
    def search_albums(self, query: str, limit: int = 10) -> list[AlbumResult]:
        """Search for albums by name."""

    @abstractmethod
    def search_tracks(self, query: str, limit: int = 10) -> list[TrackResult]:
        """Search for tracks by name."""

    @abstractmethod
    def get_artist(self, provider_id: int | str) -> ArtistResult | None:
        """Get artist details by provider-specific ID."""

    @abstractmethod
    def get_artist_albums(
        self, provider_id: int | str, limit: int = 100
    ) -> list[AlbumResult]:
        """Get all albums for an artist."""

    @abstractmethod
    def get_album(self, provider_id: int | str) -> AlbumResult | None:
        """Get album details by provider-specific ID."""

    @abstractmethod
    def get_album_tracks(self, provider_id: int | str) -> list[TrackResult]:
        """Get all tracks for an album."""

    @abstractmethod
    def get_track(self, provider_id: int | str) -> TrackResult | None:
        """Get track details by provider-specific ID."""

    @abstractmethod
    def get_track_by_isrc(self, isrc: str) -> TrackResult | None:
        """Look up a track by ISRC code."""

    @abstractmethod
    def get_playlist(self, playlist_id: int | str) -> PlaylistResult | None:
        """Get playlist details by provider-specific ID."""

    @abstractmethod
    def get_playlist_tracks(self, playlist_id: int | str) -> list[TrackResult]:
        """Get all tracks for a playlist."""
