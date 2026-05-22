"""Async service for casting / clearing votes on contributions."""

from __future__ import annotations

from typing import cast

from django.db import IntegrityError, transaction

from asgiref.sync import sync_to_async

from queuetip.models import Account, Contribution, Playlist, Vote
from queuetip.permissions import require_member

from ..errors import NotFoundError, ValidationError


class VoteService:
    """Stateless namespace for vote operations."""

    @staticmethod
    async def cast_vote(account: Account, contribution_id: int, value: int) -> Vote:
        if value not in (-1, 1):
            raise ValidationError("Vote value must be +1 or -1.")

        def _cast() -> Vote:
            contribution = (
                Contribution.objects.select_related("playlist")
                .filter(id=contribution_id)
                .first()
            )
            if contribution is None:
                raise NotFoundError(f"No contribution with id={contribution_id}")
            require_member(account, cast(Playlist, contribution.playlist))
            try:
                with transaction.atomic():
                    vote, _ = Vote.objects.update_or_create(
                        contribution=contribution,
                        account=account,
                        defaults={"value": value},
                    )
            except IntegrityError:
                # Two simultaneous first-votes from the same account both saw
                # "no row" and raced the insert; the loser re-reads the winner's
                # row and applies its own value.
                vote = Vote.objects.get(contribution=contribution, account=account)
                vote.value = value
                vote.save(update_fields=["value"])
            return vote

        return await sync_to_async(_cast)()

    @staticmethod
    async def clear_vote(account: Account, contribution_id: int) -> None:
        def _clear() -> None:
            contribution = (
                Contribution.objects.select_related("playlist")
                .filter(id=contribution_id)
                .first()
            )
            if contribution is None:
                raise NotFoundError(f"No contribution with id={contribution_id}")
            require_member(account, cast(Playlist, contribution.playlist))
            Vote.objects.filter(contribution=contribution, account=account).delete()

        await sync_to_async(_clear)()
