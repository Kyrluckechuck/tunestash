from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import strawberry


def _serialize_datetime(value: Any) -> str:
    """Serialize datetime to ISO 8601 string."""
    if isinstance(value, datetime):
        return value.isoformat()
    raise ValueError(f"Cannot serialize {value} as DateTime")


def _parse_datetime(value: Any) -> datetime:
    """Parse ISO 8601 string to datetime."""
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"Cannot parse {value} as DateTime")


if TYPE_CHECKING:
    DateTime = datetime
else:
    DateTime = strawberry.scalar(
        datetime,
        name="DateTime",
        description=(
            "The `DateTime` scalar type represents a date and time following the "
            "ISO 8601 standard."
        ),
        serialize=_serialize_datetime,
        parse_value=_parse_datetime,
    )
