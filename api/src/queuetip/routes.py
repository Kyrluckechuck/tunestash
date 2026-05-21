"""FastAPI auth routes for the Queuetip public process.

`/auth/verify` consumes a magic-link token and sets the session cookie.
Phase 1 returns a plain success page; Phase 2 will redirect to the frontend.
"""

import datetime as dt
import uuid
from typing import cast

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
    _derive_nonce,
    build_authorize_url,
    exchange_code_for_tokens,
    get_spotify_user_id,
    make_state_token,
    read_state_token,
)

router = APIRouter()

_VERIFY_SUCCESS_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Signed in — Queuetip</title>
<style>
  :root {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  body {{ margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #fafafa; color: #0a0a0a; }}
  .card {{ max-width: 28rem; padding: 2rem; background: white; border: 1px solid #e5e5e5; border-radius: 0.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); text-align: center; }}
  .check {{ width: 3rem; height: 3rem; margin: 0 auto 1rem; color: #16a34a; }}
  h1 {{ font-size: 1.5rem; font-weight: 600; margin: 0 0 0.5rem; }}
  p {{ color: #525252; margin: 0 0 1.5rem; }}
  a.btn {{ display: inline-block; background: #0a0a0a; color: white; text-decoration: none; padding: 0.5rem 1rem; border-radius: 0.375rem; font-weight: 500; font-size: 0.875rem; }}
  a.btn:hover {{ background: #262626; }}
</style></head><body>
  <div class="card">
    <svg class="check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="9 12 12 15 17 10"/></svg>
    <h1>You're signed in to Queuetip</h1>
    <p>You can close this tab and head back to the app.</p>
    <a class="btn" href="{frontend_url}">Open Queuetip</a>
  </div>
</body></html>"""

_VERIFY_ERROR_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sign-in failed — Queuetip</title>
<style>
  :root {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  body {{ margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #fafafa; color: #0a0a0a; }}
  .card {{ max-width: 28rem; padding: 2rem; background: white; border: 1px solid #e5e5e5; border-radius: 0.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); text-align: center; }}
  .x-icon {{ width: 3rem; height: 3rem; margin: 0 auto 1rem; color: #dc2626; }}
  h1 {{ font-size: 1.5rem; font-weight: 600; margin: 0 0 0.5rem; }}
  p {{ color: #525252; margin: 0 0 1.5rem; }}
  a.btn {{ display: inline-block; background: #0a0a0a; color: white; text-decoration: none; padding: 0.5rem 1rem; border-radius: 0.375rem; font-weight: 500; font-size: 0.875rem; }}
  a.btn:hover {{ background: #262626; }}
</style></head><body>
  <div class="card">
    <svg class="x-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
    <h1>Sign-in link expired</h1>
    <p>This link is invalid or has expired. Request a new one to sign in.</p>
    <a class="btn" href="{frontend_url}/sign-in">Back to sign-in</a>
  </div>
</body></html>"""


@router.get("/auth/verify")
def verify(token: str) -> Response:
    """Verify a magic-link token, set the session cookie, confirm sign-in."""
    from queuetip.models import Account as _Account

    frontend_url = getattr(
        settings, "QUEUETIP_FRONTEND_URL", "http://127.0.0.1:3001"
    ).rstrip("/")

    try:
        account_id = read_magic_link_token(token)
    except InvalidTokenError:
        return HTMLResponse(
            _VERIFY_ERROR_HTML.format(frontend_url=frontend_url),
            status_code=400,
        )

    account = _Account.objects.filter(id=account_id).first()
    session_epoch = account.session_epoch if account is not None else 0

    response = HTMLResponse(_VERIFY_SUCCESS_HTML.format(frontend_url=frontend_url))
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(account_id, session_epoch=session_epoch),
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
async def export_m3u(snapshot_id: str, request: Request) -> Response:
    """Stream the m3u for a snapshot. Member-only, session-cookie auth.

    400 if snapshot_id is not a valid UUID.
    401 if no/invalid session cookie. 403 if the caller is not a member of
    the snapshot's playlist. 404 if no such snapshot.
    """
    from queuetip.models import Account, ExportSnapshot, Playlist
    from queuetip.permissions import PermissionDeniedError, require_member

    from .m3u import render_m3u

    try:
        snapshot_uuid = uuid.UUID(snapshot_id)
    except ValueError:
        return Response(status_code=400)

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return Response(status_code=401)
    try:
        session_payload = read_session_token(token)
    except InvalidTokenError:
        return Response(status_code=401)

    def _load_and_render() -> tuple[int, str | None]:
        account = Account.objects.filter(id=session_payload.account_id).first()
        if account is None:
            return 401, None
        snap = (
            ExportSnapshot.objects.select_related("playlist")
            .filter(id=snapshot_uuid)
            .first()
        )
        if snap is None:
            return 404, None
        try:
            require_member(account, cast(Playlist, snap.playlist))
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


def _queuetip_callback_uri(request: Request | None = None) -> str:
    """Build the Spotify OAuth callback URI for this request.

    Mirrors TuneStash's pattern in `src/routes/auth.py`: prefer the
    X-Forwarded-Host set by the Vite dev proxy / nginx in production, so the
    URI matches the origin the browser is actually on (and therefore the URI
    whitelisted in the Spotify dashboard). Falls back to QUEUETIP_PUBLIC_URL
    for callers without a request (e.g. tests, background tasks).

    The same URI is sent on the authorize step AND on the token-exchange step;
    Spotify requires byte-equality between them, so both code paths must
    derive the URI the same way for the same request.
    """
    if request is not None:
        forwarded_host = request.headers.get("x-forwarded-host")
        host = forwarded_host or request.headers.get("host")
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        if host:
            # Spotify rejects `localhost` for loopback redirect URIs — must be
            # 127.0.0.1. Mirrors the swap in `src/routes/auth.py:37`. The
            # frontend ALSO redirects browsers from localhost → 127.0.0.1 at
            # boot (see queuetip-frontend/src/main.tsx) so this is mostly a
            # backstop for non-browser callers / direct API hits.
            host = host.replace("localhost", "127.0.0.1")
            # Force HTTPS for non-loopback hosts (Spotify OAuth requirement).
            if not (host.startswith("127.0.0.1") or host.startswith("localhost")):
                scheme = "https"
            return f"{scheme}://{host}/auth/spotify/callback"
    base = getattr(settings, "QUEUETIP_PUBLIC_URL", "http://127.0.0.1:3001").rstrip("/")
    return f"{base}/auth/spotify/callback"


@router.get("/auth/spotify/start")
async def spotify_start(request: Request) -> Response:
    """Redirect a signed-in user to Spotify's OAuth authorize URL."""
    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        return Response(status_code=401)
    try:
        start_payload = read_session_token(session_token)
    except InvalidTokenError:
        return Response(status_code=401)

    try:
        nonce = _derive_nonce(session_token)
        state = make_state_token(start_payload.account_id, session_nonce=nonce)
        # build_authorize_url reads Spotify creds from the app_settings registry,
        # which queries the DB synchronously. Must be wrapped in sync_to_async
        # from this async route, or Django raises SynchronousOnlyOperation that
        # the registry silently swallows, returning empty strings → false
        # "not configured" error.
        url = await sync_to_async(build_authorize_url)(
            state=state, redirect_uri=_queuetip_callback_uri(request)
        )
    except SpotifyOAuthError as exc:
        return HTMLResponse(
            f"<h1>Spotify is not configured</h1><p>{exc}</p>", status_code=503
        )
    return RedirectResponse(url, status_code=302)


@router.get("/auth/spotify/callback")
async def spotify_callback(  # pylint: disable=too-many-return-statements
    request: Request,
) -> Response:
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

    # Reject callback if the caller has no session — the state token was
    # issued for a specific session, so no session means it can't match.
    callback_session_token = request.cookies.get(SESSION_COOKIE)
    if not callback_session_token:
        return HTMLResponse(
            "<h1>Session expired. Please sign in again.</h1>", status_code=400
        )
    expected_nonce = _derive_nonce(callback_session_token)

    try:
        account_id = read_state_token(state, expected_nonce=expected_nonce)
    except InvalidStateError:
        return HTMLResponse(
            "<h1>Sign-in link expired or tampered. Try again.</h1>", status_code=400
        )

    try:
        tokens = await sync_to_async(exchange_code_for_tokens)(
            code, _queuetip_callback_uri(request)
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
        settings, "QUEUETIP_FRONTEND_URL", "http://127.0.0.1:3001"
    ).rstrip("/")
    return RedirectResponse(f"{frontend}/?spotify_linked=1", status_code=302)
