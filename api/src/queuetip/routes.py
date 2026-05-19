"""FastAPI auth routes for the Queuetip public process.

`/auth/verify` consumes a magic-link token and sets the session cookie.
Phase 1 returns a plain success page; Phase 2 will redirect to the frontend.
"""

from django.conf import settings

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

from .auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    InvalidTokenError,
    make_session_token,
    read_magic_link_token,
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
