"""GraphQL request context for the Queuetip public process.

Resolves the current Account from the signed session cookie. Resolvers read
`info.context.account`; it is None for anonymous requests.
"""

from asgiref.sync import sync_to_async
from starlette.requests import Request
from strawberry.fastapi import BaseContext

from queuetip.models import Account

from .auth import SESSION_COOKIE, InvalidTokenError, read_session_token


class QueuetipContext(BaseContext):
    """Per-request GraphQL context.

    Inherits from BaseContext so Strawberry's FastAPI router accepts it and
    injects request/response/background_tasks automatically.
    """

    def __init__(self, account: Account | None) -> None:
        super().__init__()
        self.account = account


async def get_context(request: Request) -> QueuetipContext:
    """Build the GraphQL context, resolving the session cookie to an Account.

    Validates the session epoch in the token against Account.session_epoch.
    A mismatch (e.g. after signOutEverywhere bumped the epoch) treats the
    request as anonymous.
    """
    account: Account | None = None
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            payload = read_session_token(token)
        except InvalidTokenError:
            payload = None
        if payload is not None:
            db_account = await sync_to_async(
                Account.objects.filter(id=payload.account_id).first
            )()
            if (
                db_account is not None
                and db_account.session_epoch == payload.session_epoch
            ):
                account = db_account
    return QueuetipContext(account=account)
