"""FastAPI auth routes for the Queuetip public process.

`/auth/verify` consumes a magic-link token and sets the session cookie.
Phase 1 returns a plain success page; Phase 2 will redirect to the frontend.
"""

import datetime as dt

from django.conf import settings
from django.utils import timezone

from asgiref.sync import sync_to_async
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.requests import Request

from .auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    InvalidTokenError,
    make_session_token,
    read_magic_link_token,
    read_session_token,
)
from .spotify_oauth import (
    InvalidStateError,
    SpotifyOAuthError,
    build_authorize_url,
    exchange_code_for_tokens,
    get_spotify_user_id,
    make_state_token,
    read_state_token,
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


def _queuetip_callback_uri() -> str:
    base = getattr(settings, "QUEUETIP_PUBLIC_URL", "http://localhost:5050").rstrip("/")
    return f"{base}/auth/spotify/callback"


@router.get("/auth/spotify/start")
async def spotify_start(request: Request) -> Response:
    """Redirect a signed-in user to Spotify's OAuth authorize URL."""
    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        return Response(status_code=401)
    try:
        account_id = read_session_token(session_token)
    except InvalidTokenError:
        return Response(status_code=401)

    try:
        state = make_state_token(account_id)
        url = build_authorize_url(state=state, redirect_uri=_queuetip_callback_uri())
    except SpotifyOAuthError as exc:
        return HTMLResponse(
            f"<h1>Spotify is not configured</h1><p>{exc}</p>", status_code=503
        )
    return RedirectResponse(url, status_code=302)


@router.get("/auth/spotify/callback")
async def spotify_callback(request: Request) -> Response:
    """Handle the Spotify OAuth redirect: exchange the code for tokens, persist."""
    from queuetip.models import Account, ExternalServiceLink

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return HTMLResponse(
            f"<h1>Spotify authorization failed</h1><p>{error}</p>", status_code=400
        )
    if not code or not state:
        return Response(status_code=400)

    try:
        account_id = read_state_token(state)
    except InvalidStateError:
        return HTMLResponse(
            "<h1>Sign-in link expired or tampered. Try again.</h1>", status_code=400
        )

    try:
        tokens = await sync_to_async(exchange_code_for_tokens)(
            code, _queuetip_callback_uri()
        )
        spotify_user_id = await sync_to_async(get_spotify_user_id)(
            tokens["access_token"]
        )
    except SpotifyOAuthError as exc:
        return HTMLResponse(f"<h1>OAuth failed</h1><p>{exc}</p>", status_code=502)

    expires_at = timezone.now() + dt.timedelta(seconds=int(tokens["expires_in"]))

    def upsert() -> None:
        account = Account.objects.filter(id=account_id).first()
        if account is None:
            raise SpotifyOAuthError(f"Unknown account_id {account_id}")
        ExternalServiceLink.objects.update_or_create(
            account=account,
            service=ExternalServiceLink.SERVICE_SPOTIFY,
            defaults={
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "expires_at": expires_at,
                "scope": tokens.get("scope", ""),
                "service_user_id": spotify_user_id,
            },
        )

    try:
        await sync_to_async(upsert)()
    except SpotifyOAuthError as exc:
        return HTMLResponse(f"<h1>{exc}</h1>", status_code=400)

    frontend = getattr(
        settings, "QUEUETIP_FRONTEND_URL", "http://localhost:3001"
    ).rstrip("/")
    return RedirectResponse(f"{frontend}/?spotify_linked=1", status_code=302)
