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
from strawberry.types.execution import ExecutionContext

from ..errors import (
    AuthRequiredError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from .mutation import Mutation
from .query import Query

logger = logging.getLogger(__name__)

# Errors whose messages are safe to pass through to the client unchanged.
_PASS_THROUGH_ERRORS = (AuthRequiredError, ValidationError)

# Errors that reveal existence side-channels — message is replaced at the
# GraphQL boundary with a single unified string so callers cannot distinguish
# "not found" from "forbidden". The original message is preserved in logs.
_EXISTENCE_DISCLOSURE_ERRORS = (NotFoundError, PermissionDeniedError)
_UNIFIED_MESSAGE = "Not found or not allowed."


def _should_mask_error(error: GraphQLError) -> bool:
    """Return True for unexpected exceptions that must be hidden from clients."""
    original = error.original_error
    if original is None:
        # Validation/syntax errors from graphql-core — safe to surface as-is.
        return False
    if isinstance(original, (*_PASS_THROUGH_ERRORS, *_EXISTENCE_DISCLOSURE_ERRORS)):
        return False
    # Unknown exception: mask the message and log the original for diagnosis.
    logger.exception("Unhandled exception in GraphQL resolver", exc_info=original)
    return True


class QueuetipSchema(strawberry.Schema):
    """Schema subclass that replaces existence-disclosure error messages.

    NotFoundError and PermissionDeniedError are unified into a single message
    so callers cannot probe for resource existence via error text. The original
    informative message is preserved server-side in the exception object and
    standard logging.
    """

    def process_errors(
        self,
        errors: list[GraphQLError],
        execution_context: ExecutionContext | None = None,
    ) -> None:
        for error in errors:
            original = error.original_error
            if isinstance(original, _EXISTENCE_DISCLOSURE_ERRORS):
                # graphql-core stores message in __slots__ — direct assignment works.
                error.message = _UNIFIED_MESSAGE
        super().process_errors(errors, execution_context)


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

schema = QueuetipSchema(query=Query, mutation=Mutation, extensions=_extensions)
