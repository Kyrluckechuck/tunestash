"""Service-layer error types for Queuetip's public API.

The Django app re-uses some of these (PermissionDeniedError) — see
`queuetip/permissions.py`. Resolvers translate these to GraphQL errors via
Strawberry's exception handling.
"""

from queuetip.permissions import PermissionDeniedError  # re-export


class AuthRequiredError(Exception):
    """Caller is anonymous; operation requires a signed-in account."""


class NotFoundError(Exception):
    """A referenced playlist / account / contribution does not exist."""


class ValidationError(Exception):
    """Caller-supplied input is malformed or violates a domain rule."""


__all__ = [
    "AuthRequiredError",
    "NotFoundError",
    "PermissionDeniedError",
    "ValidationError",
]
