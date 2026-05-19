"""Queuetip GraphQL Mutation type."""

import re

from django.db import IntegrityError, transaction

import strawberry
from asgiref.sync import sync_to_async

from queuetip.models import Account, AuthIdentity

from ..auth import make_magic_link_token
from ..email import send_magic_link_email

# Pragmatic email shape check — rejects obvious garbage before we create a row
# or hand the address to the mail backend. Not a full RFC 5322 validation.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Matches Account.display_name max_length; a longer value would raise a
# DataError from the DB layer rather than a friendly result.
_DISPLAY_NAME_MAX = 120


@strawberry.type
class RequestMagicLinkResult:
    """Outcome of a magic-link request."""

    sent: bool
    message: str


async def _request_magic_link(
    email: str, display_name: str | None
) -> RequestMagicLinkResult:
    """Find or create an account for `email` and email it a sign-in link.

    An unknown email with no display name cannot sign up — it gets a result
    with `sent=False` asking for a name. Known emails ignore `display_name`.
    """
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        return RequestMagicLinkResult(
            sent=False, message="That doesn't look like a valid email address."
        )

    def find_identity() -> AuthIdentity | None:
        return (
            AuthIdentity.objects.filter(
                provider=AuthIdentity.PROVIDER_MAGIC_LINK, identifier=email
            )
            .select_related("account")
            .first()
        )

    identity = await sync_to_async(find_identity)()

    if identity is None:
        clean_name = display_name.strip() if display_name else ""
        if not clean_name:
            return RequestMagicLinkResult(
                sent=False,
                message="No account exists for that email. "
                "Provide a display name to sign up.",
            )
        if len(clean_name) > _DISPLAY_NAME_MAX:
            return RequestMagicLinkResult(
                sent=False,
                message=f"Display name is too long "
                f"(max {_DISPLAY_NAME_MAX} characters).",
            )

        def create_account() -> Account | None:
            # Account + AuthIdentity must land together: an Account with no
            # identity can never be signed into. atomic() rolls back both if
            # the second insert fails. A concurrent signup for the same email
            # loses the unique-constraint race — return None and re-query.
            try:
                with transaction.atomic():
                    account = Account.objects.create(display_name=clean_name)
                    AuthIdentity.objects.create(
                        account=account,
                        provider=AuthIdentity.PROVIDER_MAGIC_LINK,
                        identifier=email,
                    )
                return account
            except IntegrityError:
                return None

        account = await sync_to_async(create_account)()
        if account is None:
            identity = await sync_to_async(find_identity)()
            if identity is None:
                return RequestMagicLinkResult(
                    sent=False,
                    message="Something went wrong signing up. Please try again.",
                )
            account = identity.account
    else:
        account = identity.account

    token = make_magic_link_token(account.id)
    await sync_to_async(send_magic_link_email)(email, token)
    return RequestMagicLinkResult(
        sent=True, message="Check your email for a sign-in link."
    )


@strawberry.type
class Mutation:
    """Root mutation for the Queuetip public API."""

    @strawberry.mutation
    async def request_magic_link(
        self, email: str, display_name: str | None = None
    ) -> RequestMagicLinkResult:
        """Request a magic-link sign-in email. Creates an account if needed."""
        return await _request_magic_link(email, display_name)
