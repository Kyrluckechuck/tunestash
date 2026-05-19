"""FastAPI auth routes for the Queuetip public process.

`/auth/verify` consumes a magic-link token and sets the session cookie.
Phase 1 returns a plain success page; Phase 2 will redirect to the frontend.
"""

from django.conf import settings

from asgiref.sync import sync_to_async
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse
from starlette.requests import Request

from .auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    InvalidTokenError,
    make_session_token,
    read_magic_link_token,
    read_session_token,
)

router = APIRouter()


@router.get("/auth/verify")
def verify(token: str) -> Response:
    """Verify a magic-link token, set the session cookie, confirm sign-in."""
    try:
        account_id = read_magic_link_token(token)
    except InvalidTokenError:
        return HTMLResponse(
            "<h1>This sign-in link is invalid or has expired.</h1>"
            "<p>Request a new one to sign in.</p>",
            status_code=400,
        )

    response = HTMLResponse(
        "<h1>You're signed in to Queuetip.</h1>"
        "<p>You can close this tab and return to the app.</p>"
    )
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(account_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=not settings.DEBUG,
    )
    return response


@router.post("/auth/logout")
def logout() -> Response:
    """Clear the session cookie."""
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE,
        samesite="lax",
        secure=not settings.DEBUG,
    )
    return response


@router.get("/exports/{snapshot_id}.m3u")
async def export_m3u(snapshot_id: int, request: Request) -> Response:
    """Stream the m3u for a snapshot. Member-only, session-cookie auth.

    401 if no/invalid session cookie. 403 if the caller is not a member of
    the snapshot's playlist. 404 if no such snapshot.
    """
    from queuetip.models import Account, ExportSnapshot
    from queuetip.permissions import PermissionDeniedError, require_member

    from .m3u import render_m3u

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return Response(status_code=401)
    try:
        account_id = read_session_token(token)
    except InvalidTokenError:
        return Response(status_code=401)

    def _load_and_render() -> tuple[int, str | None]:
        account = Account.objects.filter(id=account_id).first()
        if account is None:
            return 401, None
        snap = (
            ExportSnapshot.objects.select_related("playlist")
            .filter(id=snapshot_id)
            .first()
        )
        if snap is None:
            return 404, None
        try:
            require_member(account, snap.playlist)
        except PermissionDeniedError:
            return 403, None
        return 200, render_m3u(snap)

    status, body = await sync_to_async(_load_and_render)()
    if status != 200:
        return Response(status_code=status)
    return Response(
        content=body,
        media_type="audio/x-mpegurl",
        headers={
            "Content-Disposition": f'attachment; filename="snapshot-{snapshot_id}.m3u"'
        },
    )
