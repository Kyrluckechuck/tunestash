"""Queuetip GraphQL Mutation type."""

import strawberry
from asgiref.sync import sync_to_async

from queuetip.models import Account, AuthIdentity

from ..auth import make_magic_link_token
from ..email import send_magic_link_email


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
        if not display_name or not display_name.strip():
            return RequestMagicLinkResult(
                sent=False,
                message="No account exists for that email. "
                "Provide a display name to sign up.",
            )

        def create_account() -> Account:
            account = Account.objects.create(display_name=display_name.strip())
            AuthIdentity.objects.create(
                account=account,
                provider=AuthIdentity.PROVIDER_MAGIC_LINK,
                identifier=email,
            )
            return account

        account = await sync_to_async(create_account)()
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
