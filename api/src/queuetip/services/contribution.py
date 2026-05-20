"""Async service for song contributions: add via search or link, remove."""

from __future__ import annotations

from django.db import IntegrityError, transaction

from asgiref.sync import sync_to_async

from queuetip.models import Account, Contribution, Playlist, PlaylistMembership
from queuetip.permissions import (
    PermissionDeniedError,
    get_membership,
    require_member,
)
from src.queuetip.resolution.ingest import ingest_track
from src.queuetip.resolution.links import resolve_link

from ..errors import NotFoundError


def _deezer_track_url(deezer_id: str) -> str:
    return f"https://www.deezer.com/track/{deezer_id}"


class ContributionService:
    """Stateless namespace for contribution operations."""

    @staticmethod
    async def contribute_from_link(
        account: Account, playlist_id: int, url: str
    ) -> tuple[Contribution, bool]:
        """Resolve a track URL, ingest a Song, create a Contribution.

        Returns (contribution, already_present). If the song is already
        contributed to this playlist, returns the existing contribution with
        already_present=True (no duplicate insert).
        """

        def _contribute() -> tuple[Contribution, bool]:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_member(account, playlist)
            candidate = resolve_link(url)
            song = ingest_track(candidate)
            existing = (
                Contribution.objects.filter(playlist=playlist, song=song)
                .select_related("contributed_by", "song", "song__primary_artist")
                .first()
            )
            if existing is not None:
                return existing, True
            try:
                with transaction.atomic():
                    contribution = Contribution.objects.create(
                        playlist=playlist, song=song, contributed_by=account
                    )
            except IntegrityError:
                contribution = Contribution.objects.get(playlist=playlist, song=song)
                return contribution, True
            return contribution, False

        return await sync_to_async(_contribute)()

    @staticmethod
    async def contribute_from_search(
        account: Account, playlist_id: int, deezer_id: str
    ) -> tuple[Contribution, bool]:
        """Contribute by Deezer track id (e.g. picked from catalog_search)."""
        return await ContributionService.contribute_from_link(
            account, playlist_id, _deezer_track_url(deezer_id)
        )

    @staticmethod
    async def list_for_playlist(
        account: Account, playlist_id: int
    ) -> list[Contribution]:
        """Return all contributions for a playlist, ordered by net score desc.

        Caller must be a member. Prefetches song, primary_artist, and votes so
        callers can safely iterate without additional DB queries.
        """

        def _list() -> list[Contribution]:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_member(account, playlist)
            return list(
                Contribution.objects.filter(playlist=playlist)
                .select_related("contributed_by", "song", "song__primary_artist")
                .prefetch_related("votes", "votes__account")
                .order_by("-id")
            )

        return await sync_to_async(_list)()

    @staticmethod
    async def remove_contribution(account: Account, contribution_id: int) -> None:
        """Owner may remove any contribution; member may remove their own only."""

        def _remove() -> None:
            contribution = (
                Contribution.objects.select_related("playlist")
                .filter(id=contribution_id)
                .first()
            )
            if contribution is None:
                raise NotFoundError(f"No contribution with id={contribution_id}")
            membership = get_membership(account, contribution.playlist)
            if membership is None:
                raise PermissionDeniedError("You must be a member of this playlist.")
            is_owner = membership.role == PlaylistMembership.ROLE_OWNER
            is_self = contribution.contributed_by_id == account.id
            if not (is_owner or is_self):
                raise PermissionDeniedError(
                    "Only the contributor or a playlist owner may remove this."
                )
            contribution.delete()

        await sync_to_async(_remove)()
