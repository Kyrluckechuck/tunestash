"""Async service for creating + reading ExportSnapshots."""

from __future__ import annotations

import secrets
from typing import cast

from django.db import transaction

from asgiref.sync import sync_to_async

from queuetip.models import (
    Account,
    Contribution,
    ExportSnapshot,
    ExportSnapshotTrack,
    Playlist,
)
from queuetip.permissions import require_member

from ..errors import NotFoundError
from ..selection import CurveKnobs, SongInput, materialize


class ExportService:
    """Stateless namespace for export operations."""

    @staticmethod
    async def create(
        account: Account,
        playlist_id: int,
        *,
        exclude_my_downvotes: bool = False,
    ) -> ExportSnapshot:
        def _create() -> ExportSnapshot:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_member(account, playlist)

            contributions = list(
                Contribution.objects.filter(playlist=playlist)
                .select_related("song")
                .prefetch_related("votes")
            )

            if exclude_my_downvotes:
                contributions = [
                    c
                    for c in contributions
                    if not any(
                        v.account_id == account.id and v.value == -1
                        for v in c.votes.all()
                    )
                ]

            song_inputs = [
                SongInput(
                    song_id=c.song_id,
                    net=sum(v.value for v in c.votes.all()),
                )
                for c in contributions
            ]

            knobs = CurveKnobs(
                base=playlist.base,
                p_floor=playlist.p_floor,
                t_high=playlist.t_high,
                t_low=playlist.t_low,
            )
            seed = secrets.randbits(63)
            result = materialize(
                song_inputs,
                knobs=knobs,
                min_size=playlist.min_size,
                max_size=playlist.max_size,
                seed=seed,
            )

            with transaction.atomic():
                snapshot = ExportSnapshot.objects.create(
                    playlist=playlist,
                    requested_by=account,
                    rng_seed=seed,
                    parameters={"exclude_my_downvotes": exclude_my_downvotes},
                    warning_message=result.warning_message,
                )
                ExportSnapshotTrack.objects.bulk_create(
                    [
                        ExportSnapshotTrack(
                            snapshot=snapshot,
                            song_id=t.song_id,
                            position=t.position,
                            inclusion_reason=t.inclusion_reason.value,
                            roll_probability=t.roll_probability,
                        )
                        for t in result.tracks
                    ]
                )
            return snapshot

        return await sync_to_async(_create)()

    @staticmethod
    async def get(account: Account, snapshot_id: int) -> ExportSnapshot:
        def _get() -> ExportSnapshot:
            snap = (
                ExportSnapshot.objects.select_related("playlist", "requested_by")
                .filter(id=snapshot_id)
                .first()
            )
            if snap is None:
                raise NotFoundError(f"No snapshot with id={snapshot_id}")
            require_member(account, cast(Playlist, snap.playlist))
            return snap

        return await sync_to_async(_get)()

    @staticmethod
    async def list_for_playlist(
        account: Account, playlist_id: int
    ) -> list[ExportSnapshot]:
        def _list() -> list[ExportSnapshot]:
            playlist = Playlist.objects.filter(id=playlist_id).first()
            if playlist is None:
                raise NotFoundError(f"No playlist with id={playlist_id}")
            require_member(account, playlist)
            return list(
                ExportSnapshot.objects.filter(playlist=playlist)
                .select_related("requested_by")
                .order_by("-created_at")
            )

        return await sync_to_async(_list)()
