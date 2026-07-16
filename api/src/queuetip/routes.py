"""FastAPI auth routes for the Queuetip public process.

`/auth/verify` consumes a magic-link token and sets the session cookie.
Phase 1 returns a plain success page; Phase 2 will redirect to the frontend.
"""

import datetime as dt
import urllib.parse

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.utils import timezone

from asgiref.sync import sync_to_async
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.requests import Request

from queuetip.models import Account

from .auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    InvalidTokenError,
    make_session_token,
    read_magic_link_token,
    read_session_token,
)
from .auth_flows import (
    create_password_reset_challenge,
    reset_password_from_token,
    set_account_password,
    verify_login_code,
    verify_password_sign_in,
)
from .client_ip import get_client_ip
from .email import send_password_reset_email
from .errors import ValidationError
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


def _set_auth_cookie(response: Response, account: Account) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(account.id, session_epoch=account.session_epoch),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=not settings.DEBUG,
    )


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
    if account is None:
        # Account deleted between link issuance and verification — issuing a
        # session here would set a 30-day cookie that silently resolves to
        # anonymous. Surface the failure instead.
        return HTMLResponse(
            _VERIFY_ERROR_HTML.format(frontend_url=frontend_url),
            status_code=400,
        )
    # Persistent record that this account has actually clicked a magic link.
    # We use .update() (not save) to avoid touching auto_now-style fields
    # and to keep the write to a single column.
    _Account.objects.filter(id=account_id).update(last_signed_in_at=timezone.now())

    response = HTMLResponse(_VERIFY_SUCCESS_HTML.format(frontend_url=frontend_url))
    _set_auth_cookie(response, account)
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


@router.post("/auth/code-login")
async def code_login(request: Request) -> Response:
    """Sign in by email + one-time code and set the auth cookie."""
    payload = await request.json()
    email = str(payload.get("email") or "")
    code = str(payload.get("code") or "")
    ip = get_client_ip(request)
    account = await sync_to_async(verify_login_code)(email, code, ip)
    if account is None:
        return Response(status_code=401)
    await sync_to_async(Account.objects.filter(id=account.id).update)(
        last_signed_in_at=timezone.now()
    )
    response = Response(status_code=204)
    _set_auth_cookie(response, account)
    return response


@router.post("/auth/password-login")
async def password_login(request: Request) -> Response:
    """Sign in by email + password and set the auth cookie."""
    payload = await request.json()
    email = str(payload.get("email") or "")
    password = str(payload.get("password") or "")
    ip = get_client_ip(request)
    account = await sync_to_async(verify_password_sign_in)(email, password, ip)
    if account is None:
        return Response(status_code=401)
    await sync_to_async(Account.objects.filter(id=account.id).update)(
        last_signed_in_at=timezone.now()
    )
    response = Response(status_code=204)
    _set_auth_cookie(response, account)
    return response


@router.post("/auth/password/set")
async def set_password(request: Request) -> Response:
    """Set or update password for the currently signed-in account."""
    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        return Response(status_code=401)
    try:
        payload = read_session_token(session_token)
    except InvalidTokenError:
        return Response(status_code=401)
    account = await sync_to_async(Account.objects.filter(id=payload.account_id).first)()
    if account is None or account.session_epoch != payload.session_epoch:
        return Response(status_code=401)
    body = await request.json()
    new_password = str(body.get("newPassword") or "")
    current_password = str(body.get("currentPassword") or "")
    if account.password_hash and not await sync_to_async(check_password)(
        current_password, account.password_hash
    ):
        return Response(status_code=401)
    try:
        await sync_to_async(set_account_password)(account, new_password)
    except ValidationError as exc:
        return HTMLResponse(str(exc), status_code=400)
    return Response(status_code=204)


@router.post("/auth/password/request-reset")
async def request_password_reset(request: Request) -> Response:
    """Request a reset email; always return 204 to avoid account enumeration."""
    payload = await request.json()
    email = str(payload.get("email") or "")
    ip = get_client_ip(request)
    token = await sync_to_async(create_password_reset_challenge)(email, ip)
    if token:
        await sync_to_async(send_password_reset_email)(email.strip().lower(), token)
    return Response(status_code=204)


@router.post("/auth/password/reset")
async def password_reset(request: Request) -> Response:
    """Reset password via single-use token."""
    payload = await request.json()
    token = str(payload.get("token") or "")
    new_password = str(payload.get("newPassword") or "")
    ip = get_client_ip(request)
    try:
        account = await sync_to_async(reset_password_from_token)(
            token, new_password, ip
        )
    except ValidationError as exc:
        return HTMLResponse(str(exc), status_code=400)
    if account is None:
        return Response(status_code=400)
    response = Response(status_code=204)
    _set_auth_cookie(response, account)
    return response


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
            # 127.0.0.1. Mirrors the swap in `src/routes/auth.py:37`. The user
            # may have signed in on `localhost`, so the resulting redirect_uri
            # will not match their cookie's origin — that's intentional. The
            # callback no longer requires the session cookie (see comment on
            # the cookie-less branch below) so this works regardless.
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

    # Capture the browser-facing origin so the callback can redirect the user
    # back to it after token-exchange. We embed it in the signed state token
    # (not a query param) so it can't be tampered with mid-flight. Without
    # this, post-OAuth always lands on QUEUETIP_FRONTEND_URL (127.0.0.1) even
    # when the user started on localhost — different origin, no cookie, looks
    # like a silent sign-out.
    return_origin = _safe_return_origin(_request_origin(request))

    try:
        state = make_state_token(start_payload.account_id, return_origin=return_origin)
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

    from .crypto import encrypt_token

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return HTMLResponse(
            f"<h1>Spotify authorization failed</h1><p>{error}</p>", status_code=400
        )
    if not code or not state:
        return Response(status_code=400)

    # No session-cookie check at callback: Spotify may redirect the user to
    # 127.0.0.1 (loopback OAuth requirement) even when they signed in on
    # localhost, putting the cookie out of reach of this origin. The signed
    # state token + single-use guard in read_state_token() provide CSRF
    # protection without requiring same-origin cookies. Mirrors TuneStash's
    # `src/routes/auth.py` pattern.
    try:
        state_payload = await sync_to_async(read_state_token)(state)
    except InvalidStateError:
        return HTMLResponse(
            "<h1>Sign-in link expired or tampered. Try again.</h1>", status_code=400
        )
    account_id = state_payload.account_id

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
                "access_token": encrypt_token(tokens["access_token"]),
                "refresh_token": encrypt_token(tokens["refresh_token"]),
                "expires_at": expires_at,
                "scope": tokens.get("scope", ""),
                "service_user_id": spotify_user_id,
            },
        )

    try:
        await sync_to_async(upsert)()
    except SpotifyOAuthError as exc:
        return HTMLResponse(f"<h1>{exc}</h1>", status_code=400)

    # Prefer the origin the user was on when they started the flow (carried
    # in the signed state token). Re-validate it here as a defense-in-depth
    # check — even though it's signed, treating it as untrusted input avoids
    # any future bug becoming an open-redirect.
    return_origin = _safe_return_origin(state_payload.return_origin)
    if return_origin is None:
        return_origin = getattr(
            settings, "QUEUETIP_FRONTEND_URL", "http://127.0.0.1:3001"
        ).rstrip("/")
    return RedirectResponse(f"{return_origin}/?spotify_linked=1", status_code=302)


# ── Origin helpers ──────────────────────────────────────────────────────────


def _request_origin(request: Request) -> str | None:
    """Build the browser-facing origin (scheme://host[:port]) from the request.

    Mirrors `_queuetip_callback_uri`'s precedence: X-Forwarded-Host (set by
    Vite proxy / nginx) wins over the direct Host header. Returns None when
    no host can be determined.
    """
    forwarded_host = request.headers.get("x-forwarded-host")
    host = forwarded_host or request.headers.get("host")
    if not host:
        return None
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{host}"


def _safe_return_origin(origin: str | None) -> str | None:
    """Validate that `origin` is one we're willing to redirect back to.

    Allowlist: the configured QUEUETIP_FRONTEND_URL origin plus its loopback
    variants. Even though the value comes from a *signed* state token (so an
    attacker can't forge one), treating it as untrusted means a future signing-
    key leak can't be exploited to turn the callback into an open redirect.

    Returns the trimmed origin string on success, or None to signal the
    caller should fall back to QUEUETIP_FRONTEND_URL.
    """
    if not origin:
        return None
    origin = origin.rstrip("/")
    try:
        parts = urllib.parse.urlsplit(origin)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None

    configured = getattr(
        settings, "QUEUETIP_FRONTEND_URL", "http://127.0.0.1:3001"
    ).rstrip("/")
    configured_parts = urllib.parse.urlsplit(configured)

    # Same origin as configured frontend → trivially safe.
    if (
        parts.scheme == configured_parts.scheme
        and parts.netloc == configured_parts.netloc
    ):
        return origin

    # Loopback equivalence: 'localhost' and '127.0.0.1' on the same port are
    # the same machine. Allowing both means the boot-redirect from one to the
    # other still works for users who bookmarked the older URL.
    def _loopback_swap(host: str) -> str:
        if host.startswith("localhost"):
            return host.replace("localhost", "127.0.0.1", 1)
        if host.startswith("127.0.0.1"):
            return host.replace("127.0.0.1", "localhost", 1)
        return host

    if (
        parts.scheme == configured_parts.scheme
        and _loopback_swap(parts.netloc) == configured_parts.netloc
    ):
        return origin

    return None
