"""Queuetip GraphQL Query type."""

import strawberry
from strawberry.types import Info

from ..context import QueuetipContext
from ..graphql_types import AccountType


@strawberry.type
class Query:
    """Root query for the Queuetip public API."""

    @strawberry.field
    def me(self, info: Info) -> AccountType | None:
        """Return the currently signed-in account, or null if anonymous."""
        ctx: QueuetipContext = info.context
        if ctx.account is None:
            return None
        return AccountType.from_model(ctx.account)
