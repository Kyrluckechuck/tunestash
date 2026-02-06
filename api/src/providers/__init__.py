"""External music list provider factory."""

from .base import ExternalListProvider, ExternalListResult, ExternalTrack
from .lastfm import LastFMProvider
from .listenbrainz import ListenBrainzProvider
from .youtube_music import YouTubeMusicProvider

_PROVIDERS: dict[str, type[ExternalListProvider]] = {
    "lastfm": LastFMProvider,
    "listenbrainz": ListenBrainzProvider,
    "youtube_music": YouTubeMusicProvider,
}


def get_provider(source: str) -> ExternalListProvider:
    """Get a provider instance for the given source.

    Args:
        source: "lastfm" or "listenbrainz"

    Returns:
        An instance of the appropriate provider.

    Raises:
        ValueError: If the source is not supported.
    """
    provider_cls = _PROVIDERS.get(source)
    if provider_cls is None:
        raise ValueError(
            f"Unknown external list source: '{source}'. "
            f"Supported: {', '.join(_PROVIDERS.keys())}"
        )
    return provider_cls()


__all__ = [
    "ExternalListProvider",
    "ExternalListResult",
    "ExternalTrack",
    "LastFMProvider",
    "ListenBrainzProvider",
    "YouTubeMusicProvider",
    "get_provider",
]
