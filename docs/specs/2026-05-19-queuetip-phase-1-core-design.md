# Queuetip — Phase 1: Core App Design

**Status:** Design — autonomous execution (decisions made and documented here per the
program owner's directive to churn without per-section approval).
**Date:** 2026-05-19
**Program spec:** `2026-05-19-queuetip-collaborative-playlist-design.md`
**Phase 0 spec:** `2026-05-19-queuetip-phase-0-resolution-design.md`

## Scope

Phase 1 delivers the **Queuetip core backend**: a new Django app, the public-facing
ASGI process, magic-link authentication, and the GraphQL surface for playlists,
membership, contributions, voting, and bulk import.

Phase 1 is **backend-only** — it ships a tested, deployable GraphQL API and the public
container, but **no frontend**. The frontend arrives in Phase 2 alongside the selection
engine, which is the "first end-to-end usable product" milestone in the program spec.

**In scope:** Django app + models + migrations; the separate public ASGI container;
magic-link auth + email delivery; public GraphQL schema; playlist/membership/
contribution/voting operations; async bulk import.

**Out of scope (later phases):** selection engine + `ExportSnapshot` models (Phase 2),
m3u/Spotify/Apple export (Phases 2–4), any frontend (Phase 2), GraphQL subscriptions /
real-time updates (Phase 2+), OAuth login (Phase 3).

## Package Layout

Queuetip straddles two locations, by necessity:

- **`api/queuetip/`** — the Django **app** (`apps.py`, `models.py`, `migrations/`,
  `tasks.py`, `permissions.py`). Django apps live at the project root (`api/`), beside
  `library_manager/`. Imported as `queuetip`.
- **`api/src/queuetip/`** — the **FastAPI/Strawberry layer**. Already holds the Phase 0
  `resolution/` package. Phase 1 adds `app.py` (the public ASGI app), `schema/`
  (Queuetip GraphQL), `auth.py` (magic-link + session), and `context.py`. Imported as
  `src.queuetip`.

This split mirrors TuneStash itself (`library_manager/` Django app vs `src/` FastAPI
layer). The two `queuetip` packages never import circularly: `src.queuetip` imports the
Django app's models; the Django app never imports `src.queuetip`.

## Data Model

New Django app `queuetip`, same PostgreSQL database. Seven models. `ExportSnapshot` /
`ExportSnapshotTrack` are deliberately **deferred to Phase 2** (they belong with the
selection engine).

### `Account`
A Queuetip user — unrelated to TuneStash's operator and **not** Django's
`AUTH_USER_MODEL` (see "Auth" for why).
- `display_name` — `CharField`
- `created_at` — `DateTimeField(auto_now_add=True)`

### `AuthIdentity`
- `account` — FK → `Account`, `on_delete=CASCADE`, `related_name="identities"`
- `provider` — `CharField` choices: `magic_link` (later `google`, `spotify`)
- `identifier` — `CharField` — the email for `magic_link`
- `created_at`
- `unique_together = (provider, identifier)`

Splitting identity into its own table makes adding OAuth providers a row insert, not a
schema change.

### `Playlist`
- `name` — `CharField`
- `description` — `TextField(blank=True)`
- `created_by` — FK → `Account`, `on_delete=PROTECT`, `related_name="created_playlists"`
- `invite_token` — `CharField(unique=True)` (the unique constraint already
  indexes it), default
  `secrets.token_urlsafe(16)`
- `created_at`
- Engine knobs (used by the Phase 2 selection engine; stored now so Phase 2 needs no
  migration): `min_size` `PositiveSmallIntegerField(default=0)`, `max_size`
  `PositiveSmallIntegerField(null=True, blank=True)`, `t_high`
  `PositiveSmallIntegerField(default=3)`, `t_low` `PositiveSmallIntegerField(default=3)`,
  `base` `FloatField(default=0.85)`, `p_floor` `FloatField(default=0.15)`.

### `PlaylistMembership`
- `playlist` — FK → `Playlist`, `on_delete=CASCADE`, `related_name="memberships"`
- `account` — FK → `Account`, `on_delete=CASCADE`, `related_name="memberships"`
- `role` — `CharField` choices: `owner`, `member`
- `joined_at`
- `unique_together = (playlist, account)`

### `Contribution`
- `playlist` — FK → `Playlist`, `on_delete=CASCADE`, `related_name="contributions"`
- `song` — FK → `library_manager.Song`, **`on_delete=PROTECT`** — TuneStash cannot
  delete a `Song` a playlist references
- `contributed_by` — FK → `Account`, `on_delete=PROTECT` — attribution survives a member
  leaving (leaving deletes only the `PlaylistMembership`, never the `Account`)
- `created_at`
- `unique_together = (playlist, song)`

### `Vote`
- `contribution` — FK → `Contribution`, `on_delete=CASCADE`, `related_name="votes"`
- `account` — FK → `Account`, `on_delete=CASCADE`
- `value` — `SmallIntegerField` constrained to `{-1, +1}` (CheckConstraint)
- `created_at`
- `unique_together = (contribution, account)` — "no vote" is the absence of a row

### `BulkImportJob`
Tracks one async bulk-import run so the importer can poll for the result.
- `playlist` — FK → `Playlist`, `on_delete=CASCADE`
- `requested_by` — FK → `Account`, `on_delete=PROTECT`
- `source_url` — `URLField`
- `status` — `CharField` choices: `pending`, `running`, `succeeded`, `failed`
- `added_count`, `skipped_count`, `unresolved_count` — `PositiveIntegerField(default=0)`
- `unresolved_titles` — `JSONField(default=list)`
- `error` — `TextField(blank=True)` — set when `status=failed` (bad/non-public URL)
- `created_at`, `finished_at` (`null=True`)

## Auth

### Why not `django-sesame`

The program spec suggested `django-sesame`. On inspection it is **coupled to
`AUTH_USER_MODEL`** — it issues and parses tokens for the project's user model.
TuneStash already runs `django.contrib.auth` with the **default `auth.User`** and has
migration history against it; `AUTH_USER_MODEL` cannot be safely repointed at
`queuetip.Account` after the fact. Making `Account` the project user model is therefore
off the table.

**Decision:** use Django's own **`django.core.signing`** framework (a maintained, vetted
part of Django — not hand-rolled crypto) for both the magic-link token and the session
token. This gives the one-time, expiring-link guarantee against the standalone
`Account` model with no `AUTH_USER_MODEL` coupling.

### Magic-link flow

1. `requestMagicLink(email, displayName)` mutation. If an `AuthIdentity`
   (`provider=magic_link`, `identifier=email`) exists → use its `Account`. If not and
   `displayName` is provided → create `Account` + `AuthIdentity`. If not and no
   `displayName` → error asking for a display name (sign-up needs a name).
2. The server emails a link: `<public-base-url>/auth/verify?token=<t>` where `t =
   signing.dumps({"aid": account_id}, salt="queuetip.magic-link")`.
3. `GET /auth/verify` (a route on the public ASGI app) calls `signing.loads(t,
   salt="queuetip.magic-link", max_age=900)` (15-minute validity). On success it sets the
   session cookie and 302-redirects to the frontend; on failure it renders a friendly
   "link expired" page.

### Session

After verification the public process issues a **stateless signed session cookie** —
`queuetip_session = signing.dumps({"aid": account_id}, salt="queuetip.session")`,
`HttpOnly`, `SameSite=Lax`, `Secure` in production, `max_age` 30 days. No server-side
session table. `logout` simply clears the cookie. Revocation is not a v1 requirement
(small trusted friend group); a future `Account.session_epoch` int folded into the
payload would add it without schema churn.

The GraphQL context (`src/queuetip/context.py`) reads the cookie, verifies it, and
exposes `current_account: Account | None`. Resolvers needing auth raise a GraphQL error
when it is `None`.

### Email delivery

TuneStash configures no email backend today. Phase 1 adds, via dynaconf in
`api/settings.py`:
- `EMAIL_BACKEND` — defaults to `console.EmailBackend` (magic links print to logs) so
  dev works with zero config.
- When `email_host` is set in `settings.yaml`, switch to `smtp.EmailBackend` and read
  `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
  `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` from dynaconf.

### CSRF posture

Cookie auth + GraphQL POST is CSRF-exposed. v1 mitigation, documented and sufficient for
a friend-group app: `SameSite=Lax` on the session cookie + the API accepts only
`application/json` (browsers cannot forge a cross-site JSON POST without CORS consent) +
a restrictive CORS allowlist of the Queuetip frontend origin. No CSRF token in v1.

## Public ASGI Process

`api/src/queuetip/app.py` builds a **separate FastAPI app** that mounts **only**:
- `GraphQLRouter(queuetip_schema)` at `/graphql`
- the magic-link routes `GET /auth/verify`, `POST /auth/logout`
- a `/health` endpoint

It does **not** import `src.schema` (TuneStash's admin schema) — fail-safe by
construction. CORS is restricted to the configured Queuetip frontend origin.

New Docker service `queuetip` in `docker-compose.yml` / `docker-compose.override.yml`:
same image as `web`, `command: uvicorn src.queuetip.app:app --host 0.0.0.0 --port 5000`,
`TUNESTASH_SERVICE=queuetip`, `depends_on: postgres`. This is the **only** publicly
exposed backend service; `web` stays internal. Dev maps it to a host port (e.g. 5050).

## GraphQL Surface

Strawberry schema in `api/src/queuetip/schema/` (`query.py`, `mutation.py`,
`__init__.py`), types in `api/src/queuetip/graphql_types.py`. All ORM / Celery / signing
calls are wrapped in `sync_to_async` per the repo's async-boundary rules. Business logic
lives in a service layer (`api/src/queuetip/services/`) mirroring TuneStash's pattern;
resolvers stay thin.

### Queries
- `me` — the current `Account` or `null`
- `myPlaylists` — playlists the current account is a member of
- `playlist(inviteToken | id)` — one playlist with members + contributions + vote
  tallies; `inviteToken` lookup is the unauthenticated "preview before joining" path
- `catalogSearch(query, limit)` — wraps Phase 0 `catalog_search`

### Mutations
Auth: `requestMagicLink(email, displayName)`.
Playlists: `createPlaylist(name, description)`, `updatePlaylistSettings(id, …knobs…)`
(owner), `regenerateInviteToken(id)` (owner), `deletePlaylist(id)` (owner).
Membership: `joinPlaylist(inviteToken)`, `leavePlaylist(id)`,
`kickMember(playlistId, accountId)` (owner), `promoteMember(playlistId, accountId)`
(owner → co-owner).
Contributions: `contributeFromSearch(playlistId, deezerTrackId)`,
`contributeFromLink(playlistId, url)` — both resolve a `TrackCandidate` via the Phase 0
layer, call `ingest_track`, then create the `Contribution`. On a duplicate
(`playlist`+`song` already present) they return a `DuplicateContributionResult`
carrying the existing contribution so the client can offer "upvote instead?".
`removeContribution(id)` — owner removes any, member removes own.
Voting: `castVote(contributionId, value)` (upserts the `Vote` row),
`clearVote(contributionId)` (deletes it). The client calls `clearVote` when the user
clicks their already-active vote button again.
Bulk import: `bulkImportPlaylist(playlistId, url)` → creates a `BulkImportJob`, queues
the Celery task, returns the job id. Polled via the `playlist`/a `bulkImportJob(id)`
query.

## Permissions

`api/queuetip/permissions.py` — pure helpers over `(account, playlist)`:
`require_member`, `require_owner`, `can_remove_contribution(account, contribution)`.
Resolvers call these and raise a GraphQL error on failure. Owner = rename/delete, knobs,
regenerate invite, remove any contribution, kick, promote. Member = contribute, vote,
remove own contribution, leave. Export is Phase 2.

## Bulk Import

Celery task `queuetip.tasks.bulk_import_playlist(job_id)` (`@shared_task`, in
`api/queuetip/tasks.py`, autodiscovered):
1. Mark the `BulkImportJob` `running`.
2. `resolve_playlist(url)` (Phase 0). A bad/non-public URL → `status=failed`, `error`
   set, return.
3. For each track: `ingest_track` → `Song`; create a `Contribution` attributed to
   `requested_by` if absent, else count as skipped; unresolvable tracks → record the
   title in `unresolved_titles`.
4. Each track handled independently — one failure never aborts the run.
5. On completion set the counts, `status=succeeded`, `finished_at`.

The GraphQL mutation queues this via `sync_to_async`. A large import can queue hundreds
of TuneStash downloads — Phase 0 already flagged a dedicated queue / rate limit as a
future hardening; not blocking for Phase 1.

## Error Handling

- Provider search / link resolution failure → recoverable GraphQL error, contribution
  flow never crashes.
- Ingest failure → no `Contribution` created, error returned, no partial state.
- Bulk-import per-track failure → recorded in the summary, never aborts; invalid
  playlist URL fails the whole job up front with a clear `error`.
- Expired magic link / invalid invite token → friendly error page / GraphQL error.
- Permission failure → GraphQL error naming the missing role.

## Testing Strategy

pytest, matching TuneStash conventions, under `api/tests/unit/queuetip/` and
`api/tests/integration/queuetip/`:
- **Models / constraints:** uniqueness, the `Vote.value` check constraint, `PROTECT`
  behavior.
- **Auth:** magic-link token round-trip, expiry (`max_age`), session cookie
  verification, unknown-email/no-display-name branch.
- **Permissions:** each role can / cannot perform each action.
- **GraphQL:** each query/mutation — happy path + auth-required + permission-denied.
- **Contributions:** duplicate detection returns the existing contribution; self-voting
  allowed; re-casting the same vote value.
- **Bulk import:** mocked `resolve_playlist` — correct added/skipped/unresolved
  partitioning, importer attribution on every added track, accurate summary, bad-URL
  failure path.
- Provider/network calls mocked throughout.

## Decisions Made (no approval gate, per owner directive)

1. Phase 1 is backend-only; frontend is Phase 2.
2. `Account` is a standalone model, **not** `AUTH_USER_MODEL`.
3. Magic-link + session use `django.core.signing`, **not** `django-sesame` (which is
   `AUTH_USER_MODEL`-coupled).
4. Stateless signed session cookie; no server-side session table; no v1 revocation.
5. Email backend: console by default, SMTP when `email_host` is configured.
6. CSRF: `SameSite=Lax` + JSON-only + CORS allowlist; no CSRF token in v1.
7. `ExportSnapshot` models deferred to Phase 2.
8. `BulkImportJob` model added to track async import results.
