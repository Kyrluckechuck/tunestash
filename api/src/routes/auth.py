"""
Authentication routes for Spotify OAuth.

Provides endpoints for initiating OAuth flow, handling callbacks, and managing tokens.
"""

import html
import threading
import time
from collections import OrderedDict
from typing import Optional

from asgiref.sync import sync_to_async
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.app_settings.registry import get_setting_with_default
from src.services.spotify_oauth import SpotifyOAuthService

router = APIRouter(prefix="/auth/spotify", tags=["authentication"])

# OAuth state is kept in-process. The shipped topology runs a single uvicorn
# process, so an in-memory store is shared by every request. Entries are
# single-use, expire after a short TTL, and the store is bounded so an
# unauthenticated caller cannot grow it without limit. The state is bound to
# the canonical redirect URI, so a code/state pair issued for one redirect
# cannot be exchanged for another.
_OAUTH_STATE_TTL = 300
_OAUTH_STATE_MAX = 256
_DEFAULT_REDIRECT_URI = "http://127.0.0.1:5000/auth/spotify/callback"
_oauth_states: "OrderedDict[str, tuple[float, str]]" = OrderedDict()
_states_lock = threading.Lock()


def _prune_states(now: float) -> None:
    while _oauth_states:
        issued_at, _ = next(iter(_oauth_states.values()))
        if now - issued_at < _OAUTH_STATE_TTL:
            break
        _oauth_states.popitem(last=False)


def _store_state(state: str, redirect_uri: str) -> None:
    with _states_lock:
        now = time.monotonic()
        _prune_states(now)
        _oauth_states[state] = (now, redirect_uri)
        while len(_oauth_states) > _OAUTH_STATE_MAX:
            _oauth_states.popitem(last=False)


def _consume_state(state: str, redirect_uri: str) -> bool:
    with _states_lock:
        entry = _oauth_states.pop(state, None)
        if entry is None:
            return False
        issued_at, stored_uri = entry
        return (
            time.monotonic() - issued_at < _OAUTH_STATE_TTL
            and stored_uri == redirect_uri
        )


def _configured_redirect_uri() -> str:
    """Canonical OAuth callback URI from settings, never from request headers.

    The bundled nginx forwards ``Host $host``, which drops a nonstandard port,
    and a client can supply arbitrary ``X-Forwarded-*`` values. Building the
    redirect URI from either breaks Spotify's byte-for-byte redirect match.
    Reading the configured value also fixes this when a browser reaches the
    app through the nginx front end on 127.0.0.1:5000.
    """
    value = get_setting_with_default("spotify_redirect_uri", _DEFAULT_REDIRECT_URI)
    if not isinstance(value, str) or not value:
        return _DEFAULT_REDIRECT_URI
    return str(value).rstrip("/")


async def _redirect_uri() -> str:
    # get_setting_with_default reads the DB synchronously; keep it off the
    # event loop so Django does not raise SynchronousOnlyOperation (which the
    # settings helper would swallow and turn into a silent default).
    return await sync_to_async(_configured_redirect_uri)()


_ERROR_STYLE = """
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        display: flex; justify-content: center; align-items: center;
        min-height: 100vh; margin: 0;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }
    .container {
        background: white; padding: 3rem; border-radius: 1rem;
        box-shadow: 0 20px 60px rgba(0,0,0,0.3); text-align: center;
        max-width: 400px;
    }
    h1 { color: #e74c3c; margin-bottom: 1rem; font-size: 2rem; }
    p { color: #666; line-height: 1.6; }
    .error-icon {
        width: 80px; height: 80px; margin: 0 auto 1.5rem;
        background: #e74c3c; border-radius: 50%; display: flex;
        align-items: center; justify-content: center; font-size: 3rem; color: white;
    }
"""

# Error pages never need scripts or remote resources. A restrictive CSP is
# defence in depth around the escaped interpolation below.
_ERROR_CSP = (
    "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; "
    "img-src 'none'; base-uri 'none'; form-action 'none'"
)


def _error_page(title: str, message: str, status_code: int) -> HTMLResponse:
    content = f"""
    <html>
        <head><style>{_ERROR_STYLE}</style></head>
        <body>
            <div class="container">
                <div class="error-icon">✕</div>
                <h1>{html.escape(title)}</h1>
                <p>{html.escape(message)}</p>
                <p style="font-size: 0.875rem; color: #999; margin-top: 2rem;">You can close this window.</p>
            </div>
        </body>
    </html>
    """
    return HTMLResponse(
        content=content,
        status_code=status_code,
        headers={"Content-Security-Policy": _ERROR_CSP},
    )


@router.get("/authorize")
async def initiate_oauth(request: Request) -> RedirectResponse:
    """Redirect the operator to Spotify's authorization page."""
    redirect_uri = await _redirect_uri()

    auth_url, state = await sync_to_async(SpotifyOAuthService.get_authorization_url)(
        redirect_uri=redirect_uri
    )

    _store_state(state, redirect_uri)

    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/callback")
async def oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
) -> HTMLResponse:
    """Exchange the authorization code for tokens and store them."""
    if error:
        return _error_page("Authorization Failed", f"Error: {error}", 400)

    if not code or not state:
        raise HTTPException(
            status_code=400, detail="Missing authorization code or state"
        )

    redirect_uri = await _redirect_uri()

    if not _consume_state(state, redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    try:
        token_data = await sync_to_async(SpotifyOAuthService.exchange_code_for_tokens)(
            code, redirect_uri
        )
        await sync_to_async(SpotifyOAuthService.save_tokens)(token_data)
    except Exception:  # pylint: disable=broad-except
        # Upstream exception bodies can contain Spotify's raw response and must
        # never be reflected into the admin origin's HTML.
        return _error_page(
            "Connection Failed",
            "Failed to connect Spotify. Please try again.",
            500,
        )

    return HTMLResponse(
        content="""
        <html>
            <head>
                <style>
                    body {
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                        display: flex; justify-content: center; align-items: center;
                        min-height: 100vh; margin: 0;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    }
                    .container {
                        background: white; padding: 3rem; border-radius: 1rem;
                        box-shadow: 0 20px 60px rgba(0,0,0,0.3); text-align: center;
                        max-width: 400px;
                    }
                    h1 { color: #1DB954; margin-bottom: 1rem; font-size: 2rem; }
                    p { color: #666; margin-bottom: 2rem; line-height: 1.6; }
                    .checkmark {
                        width: 80px; height: 80px; margin: 0 auto 1.5rem;
                        background: #1DB954; border-radius: 50%; display: flex;
                        align-items: center; justify-content: center;
                    }
                    .checkmark svg { width: 50px; height: 50px; fill: white; }
                </style>
                <script>
                    window.close();
                    setTimeout(() => {
                        if (!window.closed) {
                            document.getElementById('auto-close-msg').style.display = 'none';
                            document.getElementById('manual-close-msg').style.display = 'block';
                        }
                    }, 100);
                </script>
            </head>
            <body>
                <div class="container">
                    <div class="checkmark">
                        <svg viewBox="0 0 24 24">
                            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                        </svg>
                    </div>
                    <h1>Successfully Connected!</h1>
                    <p>Your Spotify account has been linked. You can now access private playlists.</p>
                    <p id="auto-close-msg" style="font-size: 0.875rem; color: #999;">Closing window...</p>
                    <p id="manual-close-msg" style="font-size: 0.875rem; color: #999; display: none;">You can close this window now.</p>
                </div>
            </body>
        </html>
        """
    )


@router.delete("/disconnect")
async def disconnect_spotify() -> dict[str, str]:
    """Disconnect Spotify account by removing stored tokens."""
    await sync_to_async(SpotifyOAuthService.revoke_tokens)()
    return {"message": "Spotify account disconnected successfully"}


@router.get("/status")
async def oauth_status() -> dict[str, bool]:
    """Check if the operator has authenticated with Spotify OAuth."""
    is_authenticated = await SpotifyOAuthService.is_authenticated()
    return {"authenticated": is_authenticated}
