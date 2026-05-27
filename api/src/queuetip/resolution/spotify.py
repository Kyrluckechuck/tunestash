"""Spotify resolution — client-credentials reads of public tracks and playlists.

Uses TuneStash's existing registered Spotify app (DB settings spotipy_client_id /
spotipy_client_secret). Verified: client-credentials reads public USER playlists;
editorial/owner-`spotify` playlists return HTTP 404.
"""

from __future__ import annotations

import re

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from src.app_settings.registry import get_setting
from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import (
    EditorialPlaylistError,
    PlaylistNotFoundError,
    ResolutionError,
    TrackNotFoundError,
)

_PLAYLIST_ID_RE = re.compile(r"(?:playlist[:/])([A-Za-z0-9]+)")
_ALBUM_ID_RE = re.compile(r"(?:album[:/])([A-Za-z0-9]+)")
_TRACK_ID_RE = re.compile(r"(?:track[:/])([A-Za-z0-9]+)")


def _build_client() -> spotipy.Spotify:
    client_id = get_setting("spotipy_client_id")
    client_secret = get_setting("spotipy_client_secret")
    if not client_id or not client_secret:
        raise ResolutionError("Spotify app credentials are not configured")
    auth = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
    return spotipy.Spotify(auth_manager=auth)


def _candidate_from_spotify_track(track: dict) -> TrackCandidate:
    artists = [a["name"] for a in track.get("artists", []) if a.get("name")]
    return TrackCandidate(
        track_name=track.get("name", "Unknown Track"),
        artist_name=artists[0] if artists else "Unknown Artist",
        source="spotify",
        isrc=(track.get("external_ids") or {}).get("isrc"),
        source_id=track.get("id"),
        all_artists=artists,
    )


def resolve_spotify_playlist(url: str) -> list[TrackCandidate]:
    match = _PLAYLIST_ID_RE.search(url)
    if not match:
        raise PlaylistNotFoundError(f"Not a Spotify playlist URL: {url}")
    playlist_id = match.group(1)
    sp = _build_client()
    try:
        page = sp.playlist_items(playlist_id, limit=100)
    except spotipy.SpotifyException as exc:
        if exc.http_status == 404:
            raise EditorialPlaylistError(
                "This Spotify playlist is not readable — Spotify blocks API access "
                "to editorial playlists. Use a user-created public playlist."
            ) from exc
        raise PlaylistNotFoundError(str(exc)) from exc

    candidates: list[TrackCandidate] = []
    while page:
        for item in page.get("items", []):
            track = item.get("track")
            if track and track.get("id"):
                candidates.append(_candidate_from_spotify_track(track))
        page = sp.next(page) if page.get("next") else None
    return candidates


def resolve_spotify_album(url: str) -> list[TrackCandidate]:
    match = _ALBUM_ID_RE.search(url)
    if not match:
        raise PlaylistNotFoundError(f"Not a Spotify album URL: {url}")
    album_id = match.group(1)
    sp = _build_client()
    try:
        page = sp.album_tracks(album_id, limit=50)
    except spotipy.SpotifyException as exc:
        raise PlaylistNotFoundError(str(exc)) from exc

    candidates: list[TrackCandidate] = []
    while page:
        candidates.extend(
            _candidate_from_spotify_track(track)
            for track in page.get("items", [])
            if track.get("id")
        )
        page = sp.next(page) if page.get("next") else None
    return candidates


def resolve_spotify_track(url: str) -> TrackCandidate:
    match = _TRACK_ID_RE.search(url)
    if not match:
        raise TrackNotFoundError(f"Not a Spotify track URL: {url}")
    sp = _build_client()
    try:
        track = sp.track(match.group(1))
    except spotipy.SpotifyException as exc:
        raise TrackNotFoundError(str(exc)) from exc
    return _candidate_from_spotify_track(track)
