"""GraphQL types for cached statistics."""

import strawberry

from .scalars import DateTime


@strawberry.type
class CachedStatType:
    key: str
    display_name: str
    value: strawberry.scalars.JSON
    category: str
    updated_at: DateTime
