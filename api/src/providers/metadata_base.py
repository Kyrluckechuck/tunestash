"""Base classes for metadata providers (search + lookup)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class ArtistResult:
    """Artist metadata from an external provider."""

    name: str
    deezer_id: Optional[int] = None
    youtube_id: Optional[str] = None
    image_url: Optional[str] = None
    genres: list[str] = field(default_factory=list)


@dataclass
class AlbumResult:
    """Album metadata from an external provider."""

    name: str
    artist_name: str
    deezer_id: Optional[int] = None
    youtube_id: Optional[str] = None
    image_url: Optional[str] = None
    total_tracks: int = 0
    release_date: Optional[str] = None
    album_type: Optional[str] = None
    album_group: Optional[str] = None
    artist_deezer_id: Optional[int] = None


@dataclass
class TrackResult:
    """Track metadata from an external provider."""

    name: str
    artist_name: str
    album_name: Optional[str] = None
    deezer_id: Optional[int] = None
    youtube_id: Optional[str] = None
    isrc: Optional[str] = None
    duration_ms: int = 0
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    artist_deezer_id: Optional[int] = None
    album_deezer_id: Optional[int] = None


@dataclass
class PlaylistResult:
    """Playlist metadata from an external provider."""

    name: str
    deezer_id: Optional[int] = None
    description: Optional[str] = None
    creator_name: Optional[str] = None
    track_count: int = 0
    checksum: Optional[str] = None
    image_url: Optional[str] = None


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
    def get_artist(self, provider_id: Union[int, str]) -> Optional[ArtistResult]:
        """Get artist details by provider-specific ID."""

    @abstractmethod
    def get_artist_albums(
        self, provider_id: Union[int, str], limit: int = 100
    ) -> list[AlbumResult]:
        """Get all albums for an artist."""

    @abstractmethod
    def get_album(self, provider_id: Union[int, str]) -> Optional[AlbumResult]:
        """Get album details by provider-specific ID."""

    @abstractmethod
    def get_album_tracks(self, provider_id: Union[int, str]) -> list[TrackResult]:
        """Get all tracks for an album."""

    @abstractmethod
    def get_track(self, provider_id: Union[int, str]) -> Optional[TrackResult]:
        """Get track details by provider-specific ID."""

    @abstractmethod
    def get_track_by_isrc(self, isrc: str) -> Optional[TrackResult]:
        """Look up a track by ISRC code."""
