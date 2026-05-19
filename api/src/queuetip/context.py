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
    """Build the GraphQL context, resolving the session cookie to an Account."""
    account: Account | None = None
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            account_id = read_session_token(token)
        except InvalidTokenError:
            account_id = None
        if account_id is not None:
            account = await sync_to_async(Account.objects.filter(id=account_id).first)()
    return QueuetipContext(account=account)
