"""Strawberry GraphQL types for Queuetip."""

import datetime

import strawberry

from queuetip.models import Account


@strawberry.type
class AccountType:
    """A Queuetip user account."""

    id: strawberry.ID
    display_name: str
    created_at: datetime.datetime

    @classmethod
    def from_model(cls, account: Account) -> "AccountType":
        """Build an AccountType from a Django Account row."""
        return cls(
            id=strawberry.ID(str(account.id)),
            display_name=account.display_name,
            created_at=account.created_at,
        )
