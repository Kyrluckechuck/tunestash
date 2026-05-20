"""Queuetip public GraphQL schema."""

import logging
from typing import Any

from django.conf import settings as dj_settings

import strawberry
from graphql import GraphQLError
from strawberry.extensions import (
    DisableIntrospection,
    MaskErrors,
    MaxAliasesLimiter,
    QueryDepthLimiter,
)

from ..errors import (
    AuthRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from .mutation import Mutation
from .query import Query

logger = logging.getLogger(__name__)

# Exceptions whose messages are intentionally user-facing and must pass through.
_USER_FACING_ERRORS = (
    AuthRequiredError,
    PermissionDeniedError,
    ValidationError,
    NotFoundError,
)


def _should_mask_error(error: GraphQLError) -> bool:
    """Return True for unexpected exceptions that must be hidden from clients."""
    original = error.original_error
    if original is None:
        # Validation/syntax errors from graphql-core — safe to surface as-is.
        return False
    if isinstance(original, _USER_FACING_ERRORS):
        return False
    # Unknown exception: mask the message and log the original for diagnosis.
    logger.exception("Unhandled exception in GraphQL resolver", exc_info=original)
    return True


_extensions: list[Any] = [
    QueryDepthLimiter(max_depth=10),
    MaxAliasesLimiter(max_alias_count=15),
    MaskErrors(
        should_mask_error=_should_mask_error,
        error_message="Internal server error.",
    ),
]

if not getattr(dj_settings, "DEBUG", True):
    _extensions.append(DisableIntrospection())

schema = strawberry.Schema(query=Query, mutation=Mutation, extensions=_extensions)
