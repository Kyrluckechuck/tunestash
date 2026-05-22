# Queuetip → External Playlist Sync — Design

**Status**: Approved 2026-05-21, implementation pending. Covers BOTH the upcoming Subsonic sync AND a refactor of the existing Spotify export, because they should obey the same lifecycle rules.

**Why this exists**: Queuetip's collaborative playlists need to reach real listening environments. Rather than rebuild a playback stack (in-app player) or proxy a Subsonic API ourselves (which would take over the user's whole listening surface), we **push** queuetip playlists into each user's existing external service (Spotify for streaming, Navidrome / any Subsonic server for self-hosted).

---

## Shared lifecycle principles (apply to Spotify, Subsonic, and any future destination)

These rules govern the relationship between a queuetip collaborative playlist and its representation on an external service. They were learned by observing the current Spotify-export flow's failure modes and codifying them so we don't recreate the same problems on Subsonic.

### Principle 1 — One queuetip playlist ↔ one remote playlist (per user, per destination)

A user must not end up with 5 timestamped copies of the same collab playlist on Spotify or Navidrome. The model: one row keyed on `(account, playlist, destination_type)` carrying the remote playlist's ID. First export creates; subsequent exports update in place.

**Current bug**: today's `exportToSpotify` mutation creates a fresh Spotify playlist every time. We fix this by storing the remote playlist ID on the export-target row and, on subsequent exports, updating that playlist's track list in place instead of creating new.

### Principle 2 — Detect a deleted remote, stop syncing, require explicit re-link

If the user deletes the synced playlist on the remote service (or it becomes unreachable for any reason that isn't transient), the sync target enters a `remote_deleted` state. We stop all automation for that target until the user explicitly intervenes — either "re-create on remote" or "stop syncing this playlist."

Why explicit intervention: if we re-created automatically, a user who deliberately deleted their copy on Spotify would have it spontaneously reappear, which is worse than the slight friction of one click.

Detection heuristic per destination:
- **Spotify**: a PUT to `/v1/playlists/{id}/tracks` returns 404 → remote_deleted.
- **Subsonic**: `getPlaylist?id=<remote_id>` returns 70 (data not found) or `updatePlaylist?playlistId=<remote_id>` returns 70 → remote_deleted.

When transitioning to `remote_deleted`:
- Set `last_sync_status = remote_deleted`
- Clear automation: `sync_mode` flips to `manual` so the next periodic check skips it.
- Surface in the UI: "Your remote playlist was deleted. Recreate or stop syncing?"

### Principle 3 — Idempotent push, ordered by queuetip's current state

Every successful sync should converge the remote playlist to queuetip's current contribution list. We don't track diffs — we just send the full ordered list and let the remote replace its contents. This avoids drift and means manual edits on the remote get overwritten on next sync (intentional — queuetip is the source of truth for synced playlists).

### Principle 4 — Sync targets are per-user, per-playlist

Two members of the same collaborative playlist can each have their own sync target into their own Spotify account / Navidrome server. They don't coordinate; each user's sync target is independent.

---

## Unified data model — `PlaylistExportTarget`

Rather than maintaining separate `SubsonicSyncTarget` and a one-off Spotify export model, we use one polymorphic table. Each row is one (user, playlist, destination_type) triple.

```python
# api/queuetip/models.py

class PlaylistExportTarget(models.Model):
    """A user's intent to mirror a collab playlist to one external service."""

    DEST_SPOTIFY = "spotify"
    DEST_SUBSONIC = "subsonic"
    DESTINATION_CHOICES = [
        (DEST_SPOTIFY, "Spotify"),
        (DEST_SUBSONIC, "Subsonic"),
    ]

    SYNC_MANUAL = "manual"
    SYNC_ON_CHANGE = "on_change"
    SYNC_MODE_CHOICES = [
        (SYNC_MANUAL, "Manual"),
        (SYNC_ON_CHANGE, "Auto-sync on changes"),
    ]

    STATUS_PENDING = "pending"
    STATUS_OK = "ok"
    STATUS_PARTIAL = "partial"
    STATUS_FAILED = "failed"
    STATUS_REMOTE_DELETED = "remote_deleted"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_OK, "Synced"),
        (STATUS_PARTIAL, "Synced (some unmatched)"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REMOTE_DELETED, "Remote deleted — re-link required"),
    ]

    account            FK    → Account
    playlist           FK    → Playlist, related_name="export_targets"
    destination_type   Char  (choices=DESTINATION_CHOICES)

    # Exactly one of these is populated, depending on destination_type.
    # Spotify uses the existing ExternalServiceLink table (one per account).
    # Subsonic uses the new SubsonicConnection table (also one per account in MVP).
    spotify_link       FK    → ExternalServiceLink (null=True, blank=True)
    subsonic_connection FK   → SubsonicConnection (null=True, blank=True)

    # Set after the first successful create. Empty string until then.
    remote_playlist_id Char  (max=200, blank=True)

    sync_mode          Char  (choices=SYNC_MODE_CHOICES, default=SYNC_MANUAL)
    last_synced_at     DateTime (null=True)
    last_sync_status   Char  (choices=STATUS_CHOICES, default=STATUS_PENDING)
    last_error         Text  (blank=True)
    unmatched_track_titles JSON (default=list)
    matched_track_count Int   (default=0)
    total_track_count  Int   (default=0)
    created_at         DateTime (auto_now_add=True)

    class Meta:
        unique_together = [("account", "playlist", "destination_type")]
        constraints = [
            CheckConstraint(
                # Exactly one foreign key matches the destination_type.
                check=(
                    (Q(destination_type="spotify") & Q(spotify_link__isnull=False) & Q(subsonic_connection__isnull=True))
                    | (Q(destination_type="subsonic") & Q(subsonic_connection__isnull=False) & Q(spotify_link__isnull=True))
                ),
                name="queuetip_exporttarget_dest_fk_matches",
            ),
        ]
```

**Why unify**: the lifecycle rules above are identical for both destinations. Splitting into two tables means two implementations of "is the remote deleted?", two "find or create target by (user, playlist, dest)" queries, two UI lists. One table = one source of truth.

**Why the dual FK** (spotify_link, subsonic_connection): the auth and credential model are radically different per destination, and they already live in separate models we don't want to merge. Polymorphic FKs (django-polymorphic, GenericForeignKey) add too much overhead for two values; an explicit pair with a CHECK constraint is cleaner.

---

## Spotify export refactor (Principle 1 + 2 applied)

**Today**:
- Each call to `exportToSpotify(snapshotId)` creates a new Spotify playlist via `_create_playlist` and returns its URL.
- An `ExportSnapshot` is created. No record on `Account` of "this playlist's Spotify counterpart."

**After**:
- On `exportToSpotify(playlistId)` (note: no longer per-snapshot — per-playlist):
  1. Find-or-create `PlaylistExportTarget(account, playlist, dest=spotify, spotify_link=current_user_link)`.
  2. If `remote_playlist_id` is empty: create a Spotify playlist, store its ID.
  3. If `remote_playlist_id` is set: PUT to `/v1/playlists/{remote_playlist_id}/tracks` to fully replace the track list.
     - On 404 → mark `STATUS_REMOTE_DELETED`, surface in UI, do not auto-recreate. User must explicitly click "Re-create on Spotify."
- `ExportSnapshot` stays as the audit log of what was sent when — it's still created on each successful sync, but it's a side effect, not the primary identity.

**Backward compatibility**: the existing `/exports/<snapshot_id>` page becomes a snapshot detail view (which it already is). The "export to Spotify" affordance moves up to the playlist page itself — same semantic action, just attached to the durable entity.

---

---

## Architecture

```
┌──────────────┐    sync push (Subsonic API)
│   queuetip   │ ───────────────────────────────►  ┌─────────────────┐
│   (web app)  │                                   │ user's Navidrome │
└──────────────┘                                   └─────────────────┘
       │                                                   │
       │ collaborative editing, voting, contributions      │  user's
       │                                                   │  Subsonic
       ▼                                                   │  client
   queuetip UI                                             │  (Symfonium,
   (browser / mobile web)                                  │   Amperfy,
                                                           │   play:Sub, …)
                                                           ▼
                                                  playback as usual
```

Queuetip is **never on the playback path**. It writes playlists out and is done. The user's existing Subsonic client (any of the dozens that exist) plays from their existing server.

**Subsonic vs Navidrome**: Navidrome implements the Subsonic API. "Targeting Subsonic" = supporting Navidrome, Airsonic, Gonic, Funkwhale, LMS, and others for free. We don't need server-specific code paths for CRUD on playlists.

## Why not the alternatives

| Alternative | Why we rejected it |
|---|---|
| Queuetip as Subsonic-compatible proxy server | Replaces the user's normal listening surface; would have to mirror all their non-queuetip playlists; failure of the proxy kills playback. |
| Fork a Subsonic client | One platform per fork; iOS without an Apple Developer Program account is blocked; user has to install new software instead of changing zero things. |
| Build an in-app player in queuetip | Audio stack + offline cache + lockscreen + CarPlay/Android Auto = years of work, all already solved in existing clients. |

## Subsonic-specific connection model

`PlaylistExportTarget` (defined above) holds the per-destination state. Subsonic also needs a place to store the user's server credentials — Spotify uses the existing `ExternalServiceLink` for that, but no equivalent exists for Subsonic yet.

```python
# api/queuetip/models.py

class SubsonicConnection(models.Model):
    """A user's connection to their own Subsonic-compatible server."""

    STATUS_OK = "ok"
    STATUS_FAILED = "failed"
    STATUS_UNKNOWN = "unknown"

    account             FK    → Account, related_name="subsonic_connections"
    label               Char  (max=80)                    # "home navidrome"
    server_url          URL   (max=500)
    username            Char  (max=120)
    password_encrypted  Binary                            # Fernet, key from QUEUETIP_SUBSONIC_FERNET_KEY env var
    last_verified_at    DateTime  (null=True)
    verification_status Char  (choices, default=UNKNOWN)
    verification_error  Text  (blank=True)
    created_at          DateTime  (auto_now_add=True)
    updated_at          DateTime  (auto_now=True)

    # MVP: one connection per account. Multi-connection is a later optimization.
    class Meta:
        unique_together = [("account",)]
```

## Sync algorithm (idempotent overwrite, applies to both destinations)

A sync run is one Celery task: `sync_export_target(target_id: int)`. The task dispatches on `destination_type` to a destination-specific syncer (`SpotifyExportSyncer` / `SubsonicExportSyncer`), which share the same lifecycle.

1. Load the `PlaylistExportTarget`, its `Playlist`, and the destination-specific credential row (`spotify_link` or `subsonic_connection`).
2. If `last_sync_status == STATUS_REMOTE_DELETED`, abort immediately. The user must explicitly recreate.
3. List queuetip songs on the playlist (ordered by contribution position).
4. For each song, **resolve to a remote track ID** using the destination-specific resolution ladder (Spotify: search by ISRC then title+artist; Subsonic: same ladder against `search3`).
5. Tracks that resolved → `matched`. Tracks that didn't → append title to `unmatched_track_titles`.
6. **For unmatched songs with a known source ID** (Spotify GID / Deezer ID), queue a download via `library_manager.tasks.download_track_by_spotify_gid` / `download_deezer_track`. Dedup via `is_task_pending_or_running`. (This is queuetip helping TuneStash catch up; it's most useful for the Subsonic path where the missing track may actually arrive in the user's library, but harmless for Spotify too.)
7. **Push to the destination** (idempotent overwrite, principle 3):
   - **Subsonic**:
     - If `remote_playlist_id` is empty → `createPlaylist(name=<queuetip name>, songId=<matched IDs>)`. Persist returned ID.
     - Else → read current contents via `getPlaylist`, then `updatePlaylist(playlistId=<remote>, songIdToAdd=<matched IDs>, songIndexToRemove=<all current indices>)`. Stable ID, two API calls per sync.
     - If either call returns code 70 ("data not found") → set `STATUS_REMOTE_DELETED`, return.
   - **Spotify**:
     - If `remote_playlist_id` is empty → `POST /v1/users/{me}/playlists` then `PUT /v1/playlists/{id}/tracks` with full list. Persist ID.
     - Else → `PUT /v1/playlists/{remote}/tracks` with the full ordered URI list (this replaces existing tracks atomically). One API call.
     - If `PUT` returns 404 → `STATUS_REMOTE_DELETED`, return.
8. Create an `ExportSnapshot` row as an audit-log entry pointing at this target. The snapshot is no longer the primary identity (the target is), but it remains useful for "show me what was synced on date X."
9. Record `last_synced_at`, `last_sync_status` (`STATUS_OK` if all matched, `STATUS_PARTIAL` if some unmatched), `last_error` (empty on success), `unmatched_track_titles`, `matched_track_count`, `total_track_count`.

## Track resolution ladder

`resolve_song_to_subsonic_id(song: Song, client: SubsonicClient) → str | None`

1. **ISRC exact match** — `search3?query=<isrc>&songCount=10`. Filter results to ones whose returned `<song>` element advertises a matching ISRC tag (Subsonic returns ISRC inconsistently — when present, use it; when absent, fall through).
2. **Title + artist exact match** — `search3?query="<title>"&songCount=20`. Case-insensitive, trimmed match against `<song artist="…" title="…"/>` results.
3. **Title fuzzy match with artist constraint** — RapidFuzz or naive Levenshtein on title with `>= 0.85` similarity AND exact-trimmed artist match. Risk of false positives is non-trivial; surface in UI as "ambiguous match — please confirm" rather than auto-link.
4. **TuneStash hint (optional, opportunistic)**: if the queuetip song has a `file_path` AND we can detect that the Subsonic server's library overlaps with TuneStash's library (e.g., env var `QUEUETIP_SHARED_LIBRARY_PATH`), match by basename. Defer to a later phase — not part of the MVP.
5. Otherwise → unmatched.

## Auto-sync trigger

`PlaylistExportTarget.sync_mode == "on_change"`:

- **Edit hooks** (queuetip-side signals on `Contribution`, `Vote`) call `_schedule_auto_sync_if_dirty(playlist_id)`.
- That helper finds all `PlaylistExportTarget`s with `sync_mode=on_change` for that playlist (across destinations) AND `last_sync_status != STATUS_REMOTE_DELETED`, then schedules a 60s-debounced Celery task per target.
- **Debounce mechanism**: the task ID is derived from `(target_id, floor(now / 60s))` — all changes within the same 60s window share a task ID; Celery skips duplicate enqueues (Redis broker task-id dedup).
- The task wakes up 60s after the window starts and reads current playlist state. Further changes after the wake-up trigger a new window.

`sync_mode == "manual"`:
- No automation; user clicks "Sync now" in the UI.

`STATUS_REMOTE_DELETED`:
- All automation halts for this target until the user clicks "Recreate on remote" or "Stop syncing." Manual sync calls also refuse, instructing the user to recreate first.

## Periodic catch-up for unmatched tracks

Celery beat task: `requeue_stale_export_targets`, every 15 min.

```python
@shared_task(name="queuetip.tasks.requeue_stale_export_targets")
def requeue_stale_export_targets():
    targets = PlaylistExportTarget.objects.filter(
        sync_mode=PlaylistExportTarget.SYNC_ON_CHANGE,
    ).exclude(
        unmatched_track_titles=[]
    ).exclude(
        last_sync_status=PlaylistExportTarget.STATUS_REMOTE_DELETED
    )
    for t in targets:
        sync_export_target.delay(t.id)
```

This handles the case where:
- User syncs at T0 → 3 tracks unmatched, queuetip queues their downloads
- At T0+5min, downloads complete
- At T0+15min, this periodic check finds the still-stale target and re-syncs → tracks now match, `unmatched_track_titles` empties, target drops out of the candidate set.

**Why not hook into download completion?** Library_manager tasks would need awareness of queuetip's sync targets — cross-cutting concern that pollutes the app boundary. A periodic scan from queuetip's side keeps the dependency one-way.

## Auth model

Subsonic supports salted-MD5 auth: `?u=USER&t=md5(password+salt)&s=SALT&v=1.16.1&c=queuetip`.

- We store `password_encrypted` (Fernet) so a DB breach doesn't leak plaintext credentials.
- Per-request: decrypt, generate a fresh random salt, compute the MD5 token, send.
- Fernet key comes from `QUEUETIP_SUBSONIC_FERNET_KEY` env var (added to `.env.example`). Rotation = generate a new key, set both old + new as a key list via Fernet's `MultiFernet`, re-encrypt rows lazily on next save.

## M3U export — re-targeted

The existing M3U export emits absolute server-side file paths, which are only useful if the consumer mounts the same filesystem. We re-target it to emit Subsonic stream URLs from the requesting user's connection.

**New behaviour:**
1. If the user has a `SubsonicConnection` with `verification_status=OK`, render `https://<server>/rest/stream?id=<remote_track_id>&u=<user>&t=<token>&s=<salt>&v=1.16.1&c=queuetip-m3u` per matched track.
2. Resolve tracks via the same ladder. Unmatched tracks are emitted as M3U comments (`# unmatched: <title>`) for visibility without breaking parsers.
3. If the user has no connection, the endpoint returns 400 with: "Connect a Subsonic server to export M3U."

**Old behaviour (local file paths) is dropped.** This trades the niche self-hoster-with-mounted-share case for a feature that works for everyone who has a Subsonic server.

**Security note**: M3U URLs contain a fixed salted-MD5 token per track per export. The salt is generated server-side at export time, so the URL is a long-lived bearer token until the user changes their Navidrome password. Standard practice for Subsonic ecosystems; users should treat .m3u files like any sensitive credential file.

## GraphQL surface

```graphql
# Queries
mySubsonicConnections: [SubsonicConnectionType!]!
myExportTargets(playlistId: ID): [PlaylistExportTargetType!]!

# Subsonic connection management (auth credentials only)
addSubsonicConnection(label: String!, serverUrl: String!, username: String!, password: String!): SubsonicConnectionType!
updateSubsonicConnection(id: ID!, label: String, serverUrl: String, username: String, password: String): SubsonicConnectionType!
removeSubsonicConnection(id: ID!): Boolean!
testSubsonicConnection(id: ID!): SubsonicConnectionType!

# Unified export target management (works for both Spotify and Subsonic)
createExportTarget(
  playlistId: ID!
  destinationType: String!   # "spotify" | "subsonic"
  subsonicConnectionId: ID    # required when destinationType=subsonic
  syncMode: String!           # "manual" | "on_change"
): PlaylistExportTargetType!

updateExportTarget(id: ID!, syncMode: String): PlaylistExportTargetType!
removeExportTarget(id: ID!): Boolean!
syncExportTargetNow(id: ID!): PlaylistExportTargetType!

# Explicit recovery from remote_deleted state — user opts in to re-creation.
recreateExportTargetRemote(id: ID!): PlaylistExportTargetType!
```

**Replaces** the existing `exportToSpotify(snapshotId)` mutation. The new flow is:
1. `createExportTarget(playlistId, destinationType=spotify, syncMode=manual)` — first time.
2. `syncExportTargetNow(id)` — initial push (creates the Spotify playlist).
3. Future calls re-use the same target → idempotent updates instead of new playlists.

For backward compatibility, we keep `exportToSpotify` for one release as a thin wrapper that find-or-creates the target then syncs, marked `@deprecated`.

## UI surface

**Settings → "External services" section**
- Spotify subsection (existing): "Link Spotify" / "Linked as <user>" — already implemented via `ExternalServiceLink`.
- Subsonic subsection (new): "Add Subsonic connection" form (label, server URL, username, password). Runs `test_subsonic_connection` automatically on save. Lists saved connection with verified / failed badge; edit + delete actions.

**Playlist detail page → "Send to…" section**
- Replaces today's per-snapshot "Export to Spotify" button.
- Lists each available destination the user has set up:
  - "Sync to Spotify" (visible if `ExternalServiceLink` for spotify exists)
  - "Sync to <Subsonic connection label>" (visible if `SubsonicConnection` exists)
- Each row shows the current target state if one exists: a status badge with `last_synced_at` (relative time) + matched/total count, plus a small status colour:
  - Green: synced OK
  - Amber: synced with unmatched tracks
  - Red: failed
  - Grey + warning icon: remote deleted — click to recreate
- Click row → modal:
  - "Auto-sync on changes" toggle (sync_mode)
  - "Sync now" button (manual trigger)
  - "Recreate on <destination>" button (only when `STATUS_REMOTE_DELETED`)
  - List of unmatched track titles (if any) with their queuetip song name + artist
  - "Stop syncing" button (removes the target — does NOT delete the remote playlist; just stops queuetip from touching it)

## Modules / new files

| File | Purpose |
|---|---|
| `api/queuetip/models.py` (modified) | `SubsonicConnection`, `PlaylistExportTarget` |
| `api/queuetip/migrations/0009_export_targets_subsonic.py` | Schema migration |
| `api/queuetip/admin.py` (modified) | Admin registration |
| `api/src/queuetip/subsonic/client.py` | Subsonic REST client (httpx) — `ping`, `search3`, `getPlaylist`, `createPlaylist`, `updatePlaylist`, `deletePlaylist` |
| `api/src/queuetip/subsonic/resolution.py` | Resolution ladder for queuetip songs → Subsonic track IDs |
| `api/src/queuetip/services/export_sync.py` | Unified `ExportSyncService` with `SpotifyExportSyncer` and `SubsonicExportSyncer` subclasses; shared lifecycle logic |
| `api/src/queuetip/services/spotify_export.py` (refactored) | `SpotifyExportSyncer` — keeps the existing Spotify API code but reshaped to update an existing playlist instead of creating new |
| `api/queuetip/tasks/export.py` | `sync_export_target(target_id)`, `requeue_stale_export_targets` |
| `api/src/queuetip/crypto.py` | Fernet encrypt/decrypt helpers |
| `api/src/queuetip/schema/queuetip_exports.py` | GraphQL mutations + queries for the unified surface |
| `api/src/queuetip/m3u.py` (modified) | Re-target to Subsonic stream URLs (drops local-file-path version) |
| `queuetip-frontend/src/features/settings/SubsonicConnectionsSection.tsx` | Settings UI for Subsonic creds |
| `queuetip-frontend/src/features/playlist/SendToPanel.tsx` | Per-playlist destinations panel (replaces today's per-snapshot Spotify button) |
| `queuetip-frontend/src/queries/exports.graphql` | Query/mutation documents |
| Tests for each new module |

## Phasing inside the PR (commit sequence for reviewability)

1. **Models + migration + admin** — `PlaylistExportTarget` + `SubsonicConnection` + Fernet plumbing
2. **Spotify export refactor** — switch `exportToSpotify` to find-or-create target, update existing playlist on subsequent syncs, detect 404 → remote_deleted. Backward-compat wrapper for the old mutation. Tests.
3. **Subsonic API client + unit tests** — pure httpx wrapper
4. **Track resolution module** — ISRC → title+artist → fuzzy ladder
5. **Unified ExportSyncService + Celery task + integration tests** — `sync_export_target` dispatching to syncer subclasses
6. **GraphQL mutations/queries + permissions** — `createExportTarget`, `syncExportTargetNow`, `recreateExportTargetRemote`, etc.
7. **Frontend: Subsonic settings section**
8. **Frontend: per-playlist "Send to…" panel** — replaces today's Spotify export button. Status badge with remote_deleted handling.
9. **M3U re-target + tests**
10. **Periodic re-queue task + beat schedule entry + tests**
11. **Docs update**

Estimated total: ~2000–2400 LOC including tests (larger than the original Subsonic-only plan because we're refactoring Spotify export at the same time — but the Spotify refactor was needed anyway to fix the "duplicate playlists every export" bug).

## Deferred (post-MVP)

- Multi-connection per account (one Spotify link / one Subsonic connection in MVP)
- **OpenSubsonic explicit detection + API key auth** (scope ~150 LOC). MVP
  already implicitly benefits from OpenSubsonic ISRC fields when servers
  return them (search3 reads them when present). A focused follow-up PR
  adds `getOpenSubsonicExtensions` capability probing on connection-test,
  stores results on `SubsonicConnection.opensubsonic_extensions: JSONField`,
  and switches to API-key auth when the server advertises it. Wins: clean
  credential model (no password storage required when API key is available),
  reliable ISRC matching, MusicBrainz IDs as additional exact-match anchor,
  better error code semantics. Held back for MVP focus + dual code-path
  maintenance until we have real-world need beyond Navidrome.
- Per-connection self-signed cert trust toggle
- Hook download-completion to trigger sync (instead of 15min periodic)
- Conflict reconciliation if user manually edits the synced playlist on the remote (current behaviour: queuetip overwrites on next sync; this is intentional but could be configurable)
- Pre-sync detection of artist/album-level mismatches (we currently only resolve at track level)
- Multiple targets of the same destination type per (user, playlist) — e.g. "push to two of my Subsonic servers"
- Apple Music export (same pattern, different API)

## Follow-up — capability-gated auth picker

The current `SubsonicConnectionSection.tsx` shows both auth modes (password
and API key) regardless of what the target server supports. Adding API-key
auth against a server that doesn't implement `apiKeyAuthentication` produces
a confusing failure (the test-connection probe rejects with an auth error
that doesn't explain why).

**Why this matters now**: we discovered during PR 4's smoke test that
Navidrome 0.61.2 doesn't yet implement `apiKeyAuthentication` (the
OpenSubsonic extension that the picker's API-key path requires). The
extension is in the OpenSubsonic spec but not in this Navidrome version.

**Fix shape** (~80 LOC, future PR):

  1. Backend: add a `probeSubsonicServer(serverUrl: String!)` mutation that
     hits `/rest/getOpenSubsonicExtensions.view` without auth and returns
     the extension list + server type/version. Reachable without storing a
     connection first.
  2. Frontend: split the "Add connection" form into two steps —
     (a) enter URL → click "Probe" → see what the server supports;
     (b) auth picker shows only the modes the server can actually accept,
         with a note like "API-key auth requires the apiKeyAuthentication
         OpenSubsonic extension — your server doesn't advertise it."
  3. For password auth (always available against any Subsonic server), the
     picker can show it unconditionally as the safe default.

This naturally extends to other capability-aware behaviors we may add
later (e.g. lyrics support, MusicBrainz ID matching, transcoding hints).
