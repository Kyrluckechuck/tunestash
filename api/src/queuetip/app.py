"""Public-facing Queuetip ASGI application.

Mounts ONLY Queuetip's GraphQL schema and magic-link auth routes. It never
imports TuneStash's admin schema (`src.schema`) — the admin surface is
unreachable from this process by construction (fail-safe).
"""

# pylint: disable=wrong-import-position

import os
import sys
from pathlib import Path

import django

# api/ is three parents up from api/src/queuetip/app.py.
API_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(API_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()

from django.conf import settings as dj_settings  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import PlainTextResponse, Response  # noqa: E402
from starlette.middleware.base import RequestResponseEndpoint  # noqa: E402
from strawberry.fastapi import GraphQLRouter  # noqa: E402


def create_queuetip_app() -> FastAPI:
    """Build the public Queuetip FastAPI app."""
    app = FastAPI(title="Queuetip API", version="1.0.0")

    frontend_origin = getattr(
        dj_settings, "QUEUETIP_FRONTEND_URL", "http://localhost:3001"
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from django.db import close_old_connections  # noqa: E402

    @app.middleware("http")
    async def _close_stale_db_connections(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # The long-lived ASGI process has no Django request cycle, so
        # CONN_HEALTH_CHECKS never fires. Reap stale connections per request,
        # mirroring celery_app.py's task_prerun hook.
        close_old_connections()
        try:
            response = await call_next(request)
        finally:
            close_old_connections()
        return response

    from .context import get_context
    from .routes import router as auth_router
    from .schema import schema

    app.include_router(
        GraphQLRouter(schema, context_getter=get_context),  # type: ignore[arg-type]
        prefix="/graphql",
    )
    app.include_router(auth_router)

    @app.get("/health")
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    return app


app = create_queuetip_app()
