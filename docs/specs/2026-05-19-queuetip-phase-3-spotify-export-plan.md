# Queuetip Phase 3 — Spotify Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each Queuetip user can link their own Spotify account via OAuth and push any `ExportSnapshot` they have access to into a real Spotify playlist on their account.

**Architecture:** A per-Queuetip-account `ExternalServiceLink` row stores Spotify OAuth tokens. New routes on the queuetip public ASGI handle the OAuth start + callback. A `SpotifyExportService` refreshes tokens, creates a Spotify playlist, and adds tracks. A new `exportToSpotify(snapshotId, playlistName?)` mutation drives the flow; `me` is extended with `externalServiceLinks` so the frontend can show link-status.

**Tech Stack:** Reuses TuneStash's existing `spotipy_client_id`/`spotipy_client_secret` DB settings via the in-app settings registry. New Queuetip-specific redirect URI: `http://localhost:5050/auth/spotify/callback`. **External config required** (one-time): the operator must add this redirect URI to the same Spotify Dev App in the Spotify console. Implementation can proceed without it; only the live click-through fails until added.

**Spec:** `2026-05-19-queuetip-collaborative-playlist-design.md` Auth + Phases sections.

---

## Design summary

**`ExternalServiceLink` model** (`api/queuetip/models.py`):
- `account` FK Account CASCADE
- `service` CharField choices: `spotify` (extensible later)
- `access_token`, `refresh_token` TextField (encrypted at rest is a future hardening — for v1, plain text in DB, no worse than TuneStash's existing operator token storage)
- `expires_at` DateTimeField
- `scope` CharField — the granted scopes
- `service_user_id` CharField — Spotify user id, useful for display
- `created_at`, `updated_at`
- `unique_together = (account, service)`

**OAuth flow** (separate from TuneStash's operator-OAuth at `api/src/routes/auth.py`):
- `GET /auth/spotify/start` (queuetip public ASGI) — caller must be signed-in (session cookie). Generates a state token (`signing.dumps({"aid": account_id, "n": nonce}, salt=...)`, 5-min max-age). Redirects to `https://accounts.spotify.com/authorize?...&redirect_uri=<queuetip>/auth/spotify/callback&state=<token>&scope=playlist-modify-private+playlist-modify-public`.
- `GET /auth/spotify/callback?code=&state=` — verify state via signing, exchange code for tokens via `POST https://accounts.spotify.com/api/token`, store ExternalServiceLink, redirect to `<QUEUETIP_FRONTEND_URL>/?spotify_linked=1`.

**Token refresh:** When `expires_at` is in the past (or within ~60s), POST refresh-token grant to get a new access_token. If refresh fails (invalid_grant), set the link to a `needs_relink` flag (or just clear the row) and surface to the user.

**Push to Spotify:**
1. Resolve account's `ExternalServiceLink(service="spotify")` — refresh token if needed.
2. `POST /v1/users/{service_user_id}/playlists` with name (default `{playlist.name} — {timestamp}`) → returns playlist id + url.
3. Map snapshot tracks to Spotify URIs: each `Song` has `gid` (the Spotify track id) — `spotify:track:{gid}`. Skip songs with no `gid` and report the count.
4. `POST /v1/playlists/{playlist_id}/tracks` in batches of 100 with the URI list.
5. Return playlist external_url (e.g. `https://open.spotify.com/playlist/{id}`) + skipped_count to the caller.

**GraphQL:**
- Extend `AccountType` with `externalServices: [String!]!` (list of service names linked — minimal, no secrets exposed).
- Or richer: `ExternalServiceLinkSummary { service: String!, serviceUserId: String!, linkedAt: DateTime! }` and `Account.externalServices: [ExternalServiceLinkSummary!]!`.
- New mutation: `exportToSpotify(snapshotId: ID!, playlistName: String): SpotifyExportResult { spotifyPlaylistUrl: String!, skippedCount: Int!, addedCount: Int! }`.

**Frontend:**
- New `/settings` route (or inline on `/`): "Link Spotify" button (calls `window.location = "/auth/spotify/start"`); shows linked status with the service_user_id; "Unlink" button.
- On the snapshot page (`/exports/:id`), add an "Export to Spotify" button next to "Download m3u" — visible when the caller has a Spotify link (use the `me` query for status). On click → `exportToSpotify` mutation → on success toast with a link to the new Spotify playlist.

**Skipped tracks rationale:** Songs ingested via Apple/Deezer/YouTube paths may have no Spotify `gid`. The MVP simply skips them and reports the count. A future enhancement could ISRC-search Spotify for missing GIDs.

---

## Tasks

### Task 1 — ExternalServiceLink model + migration

**Files:**
- Modify: `api/queuetip/models.py` (append `ExternalServiceLink`)
- Generated: `api/queuetip/migrations/0003_external_service_link.py`
- Test: `api/tests/unit/queuetip/test_models_external_service_link.py`

Model:
```python
class ExternalServiceLink(models.Model):
    """A linked external-service identity (Spotify, future: Apple) per Account."""

    SERVICE_SPOTIFY = "spotify"
    SERVICE_CHOICES = [(SERVICE_SPOTIFY, "Spotify")]

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="external_service_links"
    )
    service = models.CharField(max_length=16, choices=SERVICE_CHOICES)
    access_token = models.TextField()
    refresh_token = models.TextField()
    expires_at = models.DateTimeField()
    scope = models.CharField(max_length=512, blank=True)
    service_user_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "service"],
                name="queuetip_external_service_link_unique",
            )
        ]
```

Tests: unique-per-(account, service); fields persist. Generate + apply migration.

Commit: `feat(queuetip): ExternalServiceLink model`.

---

### Task 2 — Spotify OAuth routes

**Files:**
- Create: `api/src/queuetip/spotify_oauth.py` (state-signing helpers + token exchange + refresh)
- Modify: `api/src/queuetip/routes.py` (add `/auth/spotify/start` + `/auth/spotify/callback`)
- Test: `api/tests/integration/queuetip/test_spotify_oauth_routes.py`

`spotify_oauth.py` exports:
- `OAUTH_STATE_SALT = "queuetip.spotify.oauth-state"` + `OAUTH_STATE_MAX_AGE = 300`
- `OAUTH_SCOPES = ["playlist-modify-private", "playlist-modify-public"]`
- `make_state_token(account_id) -> str` / `read_state_token(token) -> int` (mirroring auth.py pattern)
- `exchange_code_for_tokens(code, redirect_uri) -> dict` (httpx POST to Spotify token endpoint)
- `refresh_access_token(refresh_token) -> dict`
- `get_spotify_user_id(access_token) -> str` (GET /v1/me)
- `_get_credentials() -> tuple[str, str]` reading from in-app settings `spotipy_client_id` / `spotipy_client_secret`

The routes:
- `GET /auth/spotify/start` — read session cookie (reuse `read_session_token`); raise 401 if anon. Build state token; build authorize URL; return `RedirectResponse(302)`.
- `GET /auth/spotify/callback` — verify state, exchange code, GET /v1/me for user id, upsert `ExternalServiceLink` (use `update_or_create` keyed on (account, "spotify")), redirect to `<QUEUETIP_FRONTEND_URL>/?spotify_linked=1`.

Tests: mock httpx for token exchange and /v1/me; verify state round-trips; verify upsert; verify 401 for unsigned start; verify state-tamper rejected.

Commit: `feat(queuetip): Spotify OAuth start + callback routes`.

---

### Task 3 — SpotifyExportService (push snapshot to Spotify)

**Files:**
- Create: `api/src/queuetip/services/spotify_export.py`
- Test: `api/tests/unit/queuetip/test_service_spotify_export.py`

```python
class SpotifyExportService:
    @staticmethod
    async def export(account: Account, snapshot_id: int, playlist_name: str | None) -> SpotifyExportResult: ...
```

Internals:
1. Load snapshot via `ExportService.get` (handles member-check + NotFound).
2. Load `ExternalServiceLink(account, "spotify")` or raise `NotFoundError("Spotify is not linked.")`.
3. Refresh access_token if `expires_at <= now + 60s`. Update the row.
4. Fetch ordered tracks: `snapshot.tracks.select_related("song").order_by("position")`. Build URIs from `song.gid` where present; collect skipped titles.
5. `POST /v1/users/{service_user_id}/playlists` with name (default `{playlist.name} — {ISO timestamp}`).
6. `POST /v1/playlists/{playlist_id}/tracks` in batches of 100.
7. Return `SpotifyExportResult(spotify_playlist_url, added_count, skipped_count, skipped_titles)`.

`SpotifyExportResult` is a `@dataclass` (NOT a Strawberry type — that's Task 4).

Tests mock httpx for the Spotify API calls. Cover: happy path; refresh-token branch fires; some-tracks-skipped path; not-linked raises `NotFoundError`; member-of-playlist check enforced.

Commit: `feat(queuetip): SpotifyExportService`.

---

### Task 4 — GraphQL surface for Spotify integration

**Files:**
- Modify: `api/src/queuetip/graphql_types.py` — add `ExternalServiceLinkType` and extend `AccountType` with `externalServices: list[ExternalServiceLinkType]`
- Modify: `api/src/queuetip/schema/mutation.py` — add `exportToSpotify` mutation
- Test: integration test

`ExternalServiceLinkType`:
```python
@strawberry.type
class ExternalServiceLinkType:
    service: str
    service_user_id: str
    linked_at: datetime.datetime
```

`AccountType` extend: `external_services: list[ExternalServiceLinkType]` — populated in `from_model` by pre-fetched `links` parameter (avoid lazy load). Update all `AccountType.from_model(account)` callsites to also pass `links` (mostly `me` resolver and the various services). For brevity in places where it's just an attribution (`Vote.account.displayName`), an empty list `[]` is fine — only `me` actually needs the list.

`SpotifyExportResultType`:
```python
@strawberry.type
class SpotifyExportResultType:
    spotify_playlist_url: str
    added_count: int
    skipped_count: int
    skipped_titles: list[str]
```

`exportToSpotify` mutation:
```python
@strawberry.mutation
async def export_to_spotify(
    self, info, snapshot_id: strawberry.ID, playlist_name: str | None = None,
) -> SpotifyExportResultType:
    account = _require_account(info)
    result = await SpotifyExportService.export(account, int(snapshot_id), playlist_name)
    return SpotifyExportResultType(
        spotify_playlist_url=result.spotify_playlist_url,
        added_count=result.added_count,
        skipped_count=result.skipped_count,
        skipped_titles=result.skipped_titles,
    )
```

Update `me` resolver to pre-fetch the account's links and pass them to `AccountType.from_model`:
```python
async def me(self, info) -> AccountType | None:
    ctx = info.context
    if ctx.account is None:
        return None
    links = await sync_to_async(lambda: list(ctx.account.external_service_links.all()))()
    return AccountType.from_model(ctx.account, links)
```

For other AccountType callsites that don't need the links populated, accept a default of `[]`:
```python
@classmethod
def from_model(cls, account: Account, links: list = None) -> "AccountType":
    return cls(
        ...
        external_services=[...] if links else [],
    )
```

Schema sanity + regen frontend types. Integration test: mock `SpotifyExportService.export` to return a fixture; call mutation; assert the playlist URL is returned.

Commit: `feat(queuetip): ExternalServiceLinkType + exportToSpotify mutation`.

---

### Task 5 — Frontend Spotify link UI

**Files:**
- Create: `queuetip-frontend/src/queries/spotify.graphql`
- Create: `queuetip-frontend/src/routes/settings.tsx`
- Modify: `queuetip-frontend/src/components/Layout.tsx` — add a "Settings" link in the user menu
- Test: `queuetip-frontend/src/__tests__/settings.test.tsx`

`spotify.graphql`:
```graphql
mutation ExportToSpotify($snapshotId: ID!, $playlistName: String) {
  exportToSpotify(snapshotId: $snapshotId, playlistName: $playlistName) {
    spotifyPlaylistUrl
    addedCount
    skippedCount
    skippedTitles
  }
}
```

Extend `me.graphql` to also fetch `externalServices { service serviceUserId linkedAt }`.

`/settings` page: show the current account's external service links. "Link Spotify" button that does `window.location.assign("http://localhost:5050/auth/spotify/start")`. If already linked, show `Linked as: <serviceUserId>` and a Disabled "Linked ✓" badge. (Unlinking is out of scope for v1.)

On callback, the backend redirects to `?spotify_linked=1` — the home page can show a toast on that query param.

Commit: `feat(queuetip-frontend): Spotify link UI + settings page`.

---

### Task 6 — Frontend export-to-Spotify button on snapshot page

**Files:**
- Modify: `queuetip-frontend/src/routes/exports.$id.tsx` — add an "Export to Spotify" button visible when caller is Spotify-linked
- Test: extend `export.test.tsx`

Behavior: if `me.externalServices` includes a Spotify entry, show the button next to "Download m3u". On click → call `exportToSpotify` mutation → on success show a toast with a `<a target="_blank" href={spotifyPlaylistUrl}>Open in Spotify</a>` element. If `skippedCount > 0`, mention it in the toast.

Test: render snapshot page with `me` mock that includes a Spotify link; click button; assert mutation called; assert toast/anchor renders with URL.

Commit: `feat(queuetip-frontend): export-to-Spotify button on snapshot page`.

---

## Self-Review

**Spec coverage:**
- `ExternalServiceLink` (account, service, OAuth tokens) — Task 1 ✅
- Per-user Spotify OAuth grant — Task 2 ✅
- Push snapshot to real Spotify playlist — Task 3 ✅
- GraphQL surface — Task 4 ✅
- Frontend link UX + export trigger — Tasks 5, 6 ✅

**External config needed (one-time, by user):**
- Add `http://localhost:5050/auth/spotify/callback` to the Spotify Dev App's allowed redirect URIs (same app TuneStash already uses — `spotipy_client_id` in DB settings). For production: add the prod queuetip URL too.

**Future hardening:**
- Encrypt OAuth tokens at rest (currently plain text in DB, matching TuneStash's existing storage model).
- ISRC-search Spotify for songs without `gid` (Apple/Deezer/YouTube provenance) — currently skipped.
- Unlink mutation.
- Per-user rate limiting on `exportToSpotify` (Spotify allows ~180 requests/min per token).
