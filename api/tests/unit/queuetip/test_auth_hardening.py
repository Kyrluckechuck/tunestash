"""Session invalidation on password change and XSS escaping in OAuth pages."""

import asyncio
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from queuetip.models import Account
from src.queuetip import routes
from src.queuetip.auth import SESSION_COOKIE, make_session_token, read_session_token
from src.queuetip.auth_flows import set_account_password


class _Http:
    """Sync wrapper over an ASGI client (Starlette's TestClient needs an older
    httpx than the one installed)."""

    def __init__(self) -> None:
        app = FastAPI()
        app.include_router(routes.router)
        self._app = app

    def _call(self, method: str, url: str, **kwargs) -> httpx.Response:
        async def go() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(go())

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self._call("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self._call("POST", url, **kwargs)


@pytest.fixture
def http() -> _Http:
    return _Http()


@pytest.mark.django_db
def test_set_account_password_bumps_session_epoch():
    account = Account.objects.create(display_name="t")
    before = account.session_epoch
    set_account_password(account, "a-Long-Unusual-Passphrase-77")
    assert account.session_epoch == before + 1
    account.refresh_from_db()
    assert account.session_epoch == before + 1


@pytest.mark.django_db(transaction=True)
def test_password_set_invalidates_old_cookie_and_reissues_current(http):
    account = Account.objects.create(display_name="t")
    old = make_session_token(account.id, session_epoch=account.session_epoch)
    resp = http.post(
        "/auth/password/set",
        json={"newPassword": "a-Long-Unusual-Passphrase-77", "currentPassword": ""},
        headers={"Cookie": f"{SESSION_COOKIE}={old}"},
    )
    assert resp.status_code == 204
    account.refresh_from_db()
    assert account.session_epoch == 1

    # Fresh cookie reflects the new epoch; the stolen/old one no longer works.
    fresh = resp.cookies[SESSION_COOKIE]
    assert read_session_token(fresh).session_epoch == account.session_epoch
    again = http.post(
        "/auth/password/set",
        json={"newPassword": "another-Long-Passphrase-88", "currentPassword": "x"},
        headers={"Cookie": f"{SESSION_COOKIE}={old}"},
    )
    assert again.status_code == 401


def test_spotify_callback_error_is_escaped(http):
    resp = http.get(
        "/auth/spotify/callback", params={"error": "<script>alert(1)</script>"}
    )
    assert resp.status_code == 400
    assert "<script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


def test_spotify_callback_oauth_failure_is_escaped(http):
    from src.queuetip.spotify_oauth import SpotifyOAuthError

    with (
        patch.object(routes, "read_state_token") as rst,
        patch.object(
            routes,
            "exchange_code_for_tokens",
            side_effect=SpotifyOAuthError("<img src=x onerror=alert(1)>"),
        ),
    ):
        rst.return_value.account_id = 1
        resp = http.get("/auth/spotify/callback", params={"code": "c", "state": "s"})
    assert resp.status_code == 502
    assert "<img" not in resp.text


def test_trusted_proxies_env_parsed_by_settings():
    api_dir = Path(__file__).resolve().parents[3]
    code = "import settings; print(repr(settings.QUEUETIP_TRUSTED_PROXIES))"
    env_base = {"DJANGO_SETTINGS_MODULE": "settings", "DEV_MODE": "true"}

    def run(value: str | None) -> str:
        import os

        env = {**os.environ, **env_base}
        env.pop("QUEUETIP_TRUSTED_PROXIES", None)
        if value is not None:
            env["QUEUETIP_TRUSTED_PROXIES"] = value
        out = subprocess.run(  # nosec B603
            [sys.executable, "-c", code],
            cwd=api_dir,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip().splitlines()[-1]

    assert run(None) == "[]"
    assert run("") == "[]"
    assert run("172.18.0.0/16, 10.0.0.5") == "['172.18.0.0/16', '10.0.0.5']"
