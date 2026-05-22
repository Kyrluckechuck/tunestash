"""Exception hierarchy for Queuetip resolution."""


class ResolutionError(Exception):
    """Base for all Queuetip resolution failures."""


class UnsupportedURLError(ResolutionError):
    """The pasted URL is not a supported provider or resource type."""


class TrackNotFoundError(ResolutionError):
    """A URL or candidate was parsed but no track could be resolved."""


class PlaylistNotFoundError(ResolutionError):
    """A playlist URL is invalid, private, or does not exist."""


class EditorialPlaylistError(ResolutionError):
    """A Spotify editorial/algorithmic playlist — not readable via client credentials."""


class AppleResolverError(ResolutionError):
    """The Apple Music scrape resolver failed (page/bundle/token structure changed)."""
