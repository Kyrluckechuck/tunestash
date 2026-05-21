# Queuetip

## Overview

Queuetip is the collaborative playlist feature built into TuneStash. It lets multiple users contribute songs to a shared playlist, vote on contributions, and export a probabilistically-selected tracklist to a file or their personal Spotify account. Queuetip runs as its own public-facing ASGI process (`src/queuetip/app.py`) — completely separate from the TuneStash admin API — so only the Queuetip surface is reachable over the network. The selection engine, OAuth linking, and bulk import all run on the shared Celery worker alongside TuneStash's own background tasks.

## Architecture Diagram

```
              Internet
                 |
       +---------+----------+
       |                    |
       v                    v
   queuetip-frontend    queuetip
   (React static)       (FastAPI ASGI)
                            |
                            v
               shared internal network
                            |
       +----------+---------+---------+
       |          |         |         |
       v          v         v         v
      web      worker    postgres   valkey
      (admin,  (Celery)  (DB)       (broker)
       internal)
```

Only `queuetip-frontend` and `queuetip` are exposed to the internet. The admin `web` service, worker, beat, postgres, and valkey remain internal. This is enforced by construction: the Queuetip app never imports TuneStash's admin schema.

## Local Dev Setup

Start the full stack:

```bash
make dev-container
```

Services that auto-start in dev:

| Service | Port | Purpose |
|---------|------|---------|
| `web` | internal | TuneStash admin API (not exposed) |
| `queuetip` | internal (5000 in container) | Queuetip GraphQL API |
| `queuetip-frontend-dev` | `:3001` | Queuetip Vite dev server |
| `postgres` | `:5432` | Shared database |
| `valkey` | internal | Celery broker |

- **Queuetip frontend**: http://127.0.0.1:3001 (use `127.0.0.1`, not `localhost` — Spotify OAuth rejects `localhost` for redirect URIs and the cookie origin must match)
- **Queuetip GraphQL playground**: http://127.0.0.1:3001/graphql (proxied via the frontend dev server)

## Magic-Link in Dev

The dev environment uses Django's console email backend — magic-link URLs print to the `queuetip` container logs instead of being sent via SMTP. This is controlled by the `DJANGO_EMAIL_BACKEND` env var set in `docker-compose.override.yml`:

```yaml
- DJANGO_EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

To retrieve a sign-in link:

```bash
docker compose logs queuetip --since 30s | grep verify
```

Copy the full `http://...` URL from the log output and open it in your browser.

## Sign-Up Allowlist (Invite-Only Rollout)

By default, new account creation is gated by an operator-managed allowlist. Only emails with a row in `QueuetipSignupAllowlist` can sign up. Existing accounts (those with an `AuthIdentity` row) sign in normally regardless of the allowlist — the gate only applies to new signups.

Clients receive a neutral message on rejection to avoid email enumeration.

### Managing the allowlist

**Via Django admin** (preferred for UI access):

```
http://localhost:5000/admin/queuetip/queuetipsignupallowlist/
```

**Via management command** (useful from the command line or CI):

```bash
docker compose exec web python manage.py queuetip_allow_email alice@example.com
docker compose exec web python manage.py queuetip_allow_email alice@example.com --note "Cousin"
```

The command is idempotent — running it again for the same email updates the note.

### Disabling the gate (open sign-ups)

Set the `QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST` env var to `false` on the `queuetip` container:

```yaml
- QUEUETIP_REQUIRE_SIGNUP_ALLOWLIST=false
```

This is the escape hatch for personal or local-only deployments where open sign-ups are acceptable.

### Frontend signal

The gate state is also exposed to the frontend via the public `publicSettings.signupAllowlistEnforced` GraphQL field (no auth required). When `signupAllowlistEnforced` is `true`, the UI:

- removes the "Sign up" button from the landing page and shows an "invite-only" notice,
- adds a note next to the sign-up link on /sign-in, and
- renders an informational alert at the top of /sign-up so invited users know to check their approval status before submitting.

The `/sign-up` form stays usable — allowlisted users still need it to register. Only the env var toggle controls both backend enforcement and the UI signal in one place.

## Required Environment Variables for Production

### Application settings (`config/settings.yaml`)

```yaml
queuetip_public_url: "https://queuetip.example.com"   # Public URL for the queuetip service
queuetip_frontend_url: "https://app.queuetip.example.com"  # Frontend origin for CORS

# Email backend (required for magic-link delivery)
email_host: smtp.example.com
email_port: 587
email_use_tls: true
email_host_user: noreply@example.com
email_host_password: "..."
default_from_email: "Queuetip <noreply@example.com>"
```

### Frontend build-time variable

The Queuetip frontend must be built with the GraphQL API URL baked in:

```bash
VITE_QUEUETIP_GRAPHQL_URL=https://queuetip.example.com/graphql yarn build
```

## Spotify Dev Console Setup

Queuetip reuses TuneStash's existing Spotify Dev App for user-level OAuth (linking a Queuetip account to its personal Spotify). No new app is needed.

Add the following to the existing Spotify Dev App's **Redirect URIs** list:

```
<QUEUETIP_PUBLIC_URL>/auth/spotify/callback
```

**Local development**: `http://127.0.0.1:5050/auth/spotify/callback` — Spotify hard-rejects `localhost` for new app registrations (matches TuneStash's `spotify_redirect_uri` convention).

**Production**: `https://queuetip.example.com/auth/spotify/callback`

The required scopes (`playlist-modify-private`, `playlist-modify-public`) are requested at runtime and do not need to be pre-configured in the dashboard.

## Deployment Architecture

| Service | Exposed | Notes |
|---------|---------|-------|
| `queuetip-frontend` | Yes (port 80/443) | Nginx serving the React build, proxies `/graphql` to `queuetip` |
| `queuetip` | Yes (port 5050 or behind reverse proxy) | FastAPI ASGI — the only GraphQL surface guests reach |
| `web` | No | TuneStash admin — internal only |
| `worker` | No | Celery — internal only |
| `beat` | No | Celery Beat — internal only |
| `postgres` | No | Database — internal only |
| `valkey` | No | Broker — internal only |

The fail-safe property: even if `queuetip` were compromised, it cannot access TuneStash's admin schema because the import is never present in its process. Access control is by construction, not configuration.

## GraphQL Schema

The committed schema file is the source of truth for type generation:

```
queuetip-frontend/src/types/generated/queuetip-schema.graphql
```

To regenerate TypeScript types after schema changes:

```bash
# Fetch schema from running queuetip container and regenerate
make queuetip-graphql-schema-fetch

# Or regenerate from the local schema file (no server needed)
make queuetip-graphql-generate
```

## Design and Spec Files

Phase design documents live in `docs/specs/` and are prefixed `queuetip-*`:

- `2026-05-19-queuetip-collaborative-playlist-design.md` — top-level design
- `2026-05-19-queuetip-phase-0-*.md` — resolution and link ingestion
- `2026-05-19-queuetip-phase-1-*.md` — core playlist, membership, contributions
- `2026-05-19-queuetip-phase-2-*.md` — selection engine and frontend
- `2026-05-19-queuetip-phase-3-*.md` — Spotify export

Implementation notes for the active codebase are in `api/src/queuetip/` (backend) and `queuetip-frontend/src/` (frontend).
