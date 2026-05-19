# Songboard — Collaborative Playlist Program Design

**Status:** Design approved — program-level spec
**Date:** 2026-05-19
**Type:** Multi-phase program. Each phase below gets its own spec → plan → implementation cycle; this document is the umbrella design.

> **Naming:** "Songboard" is a placeholder. Replace throughout once a real name is chosen.

## Overview

A collaborative playlist application where a friend group contributes songs to shared
playlists, votes them up or down, and exports a weighted random selection to external
music services (m3u, Spotify, Apple Music). The app reuses TuneStash's existing
cross-platform track-resolution infrastructure as a backend service rather than
re-implementing it.

## Goals

- Friends join a playlist via a per-playlist invite link and contribute songs.
- Members can **bulk-import an entire external playlist** by pasting a public
  Spotify/Apple playlist URL; every resolvable track becomes a contribution.
- Songs accumulate up/down votes from members; attribution ("who added what") is preserved.
- An **export** materializes the contributed pool + votes into a concrete, ordered
  tracklist using weighted randomness: upvoted songs effectively guaranteed, unvoted
  songs high-probability, downvoted songs low-but-nonzero probability.
- Exports go to m3u, Spotify, and Apple Music.
- Reuse TuneStash's catalog, provider search, and cross-platform track mapping.

## Non-Goals (v1)

- A live/real-time playback engine. A future playback app is a *normal* player pointed
  at an exported snapshot — see "Future Work."
- Real-time vote updates (GraphQL subscriptions) — deferred to Phase 2+.
- OAuth login — magic-link only for v1.

## Architecture

**Decision: shared codebase, separate public deployment (Option A).**

Songboard lives **inside the TuneStash repository** as a new Django app (`songboard`),
sharing TuneStash's models, database, and Celery broker. This makes the contributed-song
foreign key (`Contribution.song → library_manager.Song`) possible and lets Songboard
call TuneStash's resolution services in-process — no internal HTTP API.

The **public-facing surface runs as a separate ASGI process** (a new `songboard`
container in the Docker stack, built from the same image, different `command:`). This
process mounts **only** Songboard's GraphQL schema and its own magic-link auth — it does
**not** mount TuneStash's admin schema.

**Rationale — fail-safe over fail-open:** TuneStash has no auth and assumes a trusted
operator. Security is a structural property of *what routes are mounted in the public
process*, not of remembering an authorization guard on every admin mutation. A new admin
mutation added in the future is automatically unreachable from the internet because it
was never in the public schema.

**Deployment:** Songboard runs on the same host as TuneStash, exposed publicly via a
reverse proxy / Cloudflare Tunnel. TuneStash's admin API stays unexposed. Optional
hardening: a reduced-privilege database role for the Songboard process.

```
Internet ──▶ [songboard container]  ── shared DB / Celery ──▶ [web / worker / beat]
             public GraphQL + auth                            TuneStash admin (unexposed)
```

## Phases

Each phase is an independent spec → plan → build cycle.

| Phase | Deliverable |
|-------|-------------|
| **0** | TuneStash resolution service interface (catalog search, provider search, link resolve, playlist resolve, ingest) + index backfill |
| **1** | Songboard core: accounts (magic-link), playlists, invite links, contribution cascade, voting, bulk playlist import |
| **2** | Selection engine + m3u export — **first end-to-end usable product** |
| **3** | Spotify export (per-user Spotify OAuth grant) |
| **4** | Apple Music export (MusicKit; requires a paid Apple Developer account, ~$99/yr) |
| **Future** | Playback app — a normal player pointed at an exported snapshot |

Phase 2 is the first point the product is genuinely usable; it is a valid stopping point.

## Data Model

New Django app `songboard`, same database as TuneStash.

- **`Account`** — a Songboard user. `display_name`, `created_at`. No relationship to
  TuneStash's operator. Identity is *not* stored as columns here — see `AuthIdentity`.
- **`AuthIdentity`** — `account`, `provider` (`magic_link`, later `google`, `spotify`),
  provider-specific identifier (e.g. email), `created_at`. An `Account` has one or more.
  This structural choice makes adding OAuth providers / account-linking later a row
  insert rather than schema surgery.
- **`Playlist`** — `name`, `description`, `created_by → Account`, `invite_token`,
  `created_at`, plus embedded engine settings: `min_size`, `max_size` (nullable =
  uncapped), and curve knobs (`t_high`, `base`, `p_floor`, `t_low`).
- **`PlaylistMembership`** — `playlist`, `account`, `role` (`owner` / `member`),
  `joined_at`. Unique on (`playlist`, `account`).
- **`Contribution`** — `playlist`, `song → library_manager.Song` (`on_delete=PROTECT`),
  `contributed_by → Account`, `created_at`. Unique on (`playlist`, `song`).
- **`Vote`** — `contribution`, `account`, `value` (`+1` / `−1`), `created_at`. Unique on
  (`contribution`, `account`). "No vote" = absence of a row.
- **`ExportSnapshot`** — `playlist`, `requested_by → Account`, `created_at`,
  `parameters` (JSON: min/max, personal filters, target service), `rng_seed`. Immutable
  historical artifact.
- **`ExportSnapshotTrack`** — `snapshot`, `song`, `position`, `inclusion_reason`
  (`guaranteed` / `rolled_in` / `topped_up`), `roll_probability`. Ordered.
- **`ExternalServiceLink`** *(Phase 3/4)* — `account`, `service`, OAuth tokens. Each
  friend links their own Spotify/Apple account for export.

**Why `Contribution.song` is a real FK:** a contributed song *is* a catalog `Song`,
carrying its existing Spotify GID and `TrackMappingCache` rows with no copying. Phase 3
export reads the track ID straight off the `Song`.

## Selection Engine

Two layers, computed in order.

### Shared layer — communal odds per song

For a contribution, `net = Σ vote values`. Probability is a **piecewise-linear curve**
over `net` with per-playlist knobs (defaults in parentheses):

- `net ≥ t_high` (+3) → `p = 1.0` — guaranteed
- `net = 0` → `p = base` (0.85) — "high odds but not guaranteed"
- `net ≤ −t_low` (−3) → `p = p_floor` (0.15) — unlikely, never impossible
- linear interpolation between anchors

Piecewise-linear (not a sigmoid) so "guaranteed" and "floor" are exact, hittable values.
Knobs ship with these defaults and are tunable per-playlist by the owner.

### Personal layer — the export request

Applied per export, never mutating shared state. v1 ships at least the filter
"exclude songs *I* downvoted." Full filter set enumerated in the Phase 2 spec.

### Materialization algorithm (produces one `ExportSnapshot`)

1. Apply personal filters to the contribution set.
2. Compute `p` for each remaining song.
3. **Roll** — include each song with probability `p` (guaranteed songs always in).
4. **Floor** — if `count < min_size`, top up with the highest-`p` excluded songs.
5. **Ceiling** — if `max_size` is set and `count > max_size`, drop the lowest-`p`
   included songs until it fits.
6. **Shuffle** the final set into random order.
7. Persist the snapshot with its `rng_seed`.

**Edge case — guaranteed songs exceed `max_size`:** step 5 cannot drop guaranteed
songs, so run a seeded weighted draw *among* the guaranteed set and flag a warning on
the snapshot.

**Re-shuffle** generates a *new* `ExportSnapshot` with a fresh seed, re-running the full
materialization (a genuinely different draw). The stored seed makes a given snapshot a
stable, named result: the same snapshot pushed to m3u, Spotify, and Apple Music yields
identical tracklists.

## Roles & Permissions

Two roles: **owner** and **member**.

- **Owner** (creator; may promote members to co-owner): rename/delete the playlist,
  change engine knobs, regenerate the invite link, remove *any* contribution, kick
  members, export.
- **Member**: contribute songs, vote, remove *their own* contributions, export, leave.

Export is available to everyone — it is a personalized read action that never mutates
shared state. Engine-knob changes are owner-only because they reshape communal odds.

## Contribution & Voting UX

**Search cascade** — one search box, three tiers:

1. Instant catalog search against TuneStash's local index.
2. An explicit "search streaming providers" action for catalog misses (slower
   provider fan-out).
3. A "paste a link" field for direct URL resolution.

Tiers 2 and 3 are deliberate user actions — a friend never waits on a provider API they
did not invoke.

**Duplicate song:** adding a song already in the pool is not an error. The UI warns
"This song is already in the playlist" and offers a yes/no: *upvote the existing
contribution instead?* "Yes" casts the user's `+1` `Vote` on the existing
`Contribution`; attribution stays with the original contributor.

**Bulk playlist import:** a member pastes a **public** Spotify/Apple playlist URL.
`resolve_playlist` expands it; the import then runs as an **async Celery task** (a large
playlist means many `ingest_track` calls and queued downloads — see the load note
below). Behaviour:

- Every resolvable track becomes a `Contribution` attributed to the **importing user**.
- Tracks already in the pool are **skipped**.
- Tracks that cannot be resolved are skipped.
- On completion the importer sees a summary: *"N added, M already present, K
  unresolved"* (with the unresolved titles listed).
- Imported songs start at net-0 with no votes; the importer may vote afterward like
  anyone else (self-voting is allowed).
- m3u file upload is **not** an import source in v1 — streaming playlist URLs only.

Because a single import can queue hundreds of downloads, this is the heaviest
contributor to the Songboard download burst — reinforcing the dedicated-queue / rate
limit consideration in Phase 0.

**Seeing songs:** v1 lists all contributions with vote tallies, refreshed on load and on
manual refresh. Real-time updates via GraphQL subscriptions are Phase 2+.

**Voting:** each contribution row has up/down; one `Vote` per user per contribution;
clicking the current vote again clears it. **Self-voting is allowed** — a contributor is
an ordinary voter on their own song.

## Moderation & Lifecycle

- **Remove a contribution:** owner removes any; member removes own. `Vote` rows
  cascade-delete. Past `ExportSnapshot` rows are immutable and untouched — they record
  the mix as it was exported. Removal affects only future materializations.
- **Leaving / being kicked:** membership ends, but the person's past contributions and
  votes remain — they are communal once cast, and removing them would distort the pool.
  Attribution shows a former member.
- **Catalog safety:** `Contribution.song` uses `on_delete=PROTECT` — TuneStash cannot
  delete a `Song` still referenced by a Songboard playlist.
- **Delete playlist:** owner-only; cascades contributions, votes, snapshots, memberships.

## Phase 0 — TuneStash Resolution Interface

Five in-process functions (no HTTP — same codebase), reusing existing TuneStash code
where possible:

- `catalog_search(query) → [Song]` — extends the existing `catalog_search.py` service.
- `provider_search(query) → [candidate]` — provider fan-out for catalog misses.
- `resolve_link(url) → candidate` — canonicalize a pasted Spotify/Apple/YouTube URL.
- `resolve_playlist(url) → [candidate]` — expand a public Spotify/Apple playlist URL
  into its tracks. Built on TuneStash's existing `ExternalList` / `ExternalListTrack`
  models and `external_list.py` service, which already ingest external playlists and
  resolve their tracks across platforms.
- `ingest_track(candidate) → Song` — create a `Song` row with cross-platform IDs /
  mappings. This is the index backfill.

**Ingest depth — identity + queued download:**

- `ingest_track` runs **synchronously** and creates the `Song` identity immediately, so
  the `Contribution` and voting are available at once.
- It then **queues an async TuneStash download** (Celery) so the audio enters the
  library / Navidrome. The download never blocks contribution or voting.
- **Download success is not a Songboard gate.** Export to Spotify/Apple needs only the
  track identity; local-file m3u simply skips missing audio. Songboard treats download
  state as informational.
- **Load consideration:** a burst of contributions causes a burst of downloads. Phase 0
  should consider a dedicated Celery queue or rate limit so Songboard traffic does not
  starve TuneStash's own library-sync work.

## Auth

**v1: magic-link only.** The public process emails a one-time login link; no passwords,
no third-party dependency. Stored as an `AuthIdentity` row with `provider=magic_link`.

OAuth (Google, Spotify) is a later convenience phase. Because OAuth requires registering
a developer app per provider — and Phase 3's Spotify export already requires a Spotify
developer app — Spotify OAuth login is best bundled into Phase 3. Account-linking is a
no-op structurally: adding a provider inserts another `AuthIdentity` against the same
`Account`.

## Error Handling

- **Provider search / link resolution failure:** surfaced to the contributor as a
  recoverable error ("couldn't reach the provider, try again or paste a link"); never
  crashes the contribution flow.
- **Ingest failure:** if `ingest_track` cannot resolve a candidate to a `Song`, no
  `Contribution` is created and the user is told. Partial state is never persisted.
- **Bulk import partial failure:** unresolvable or duplicate tracks never abort the
  import — each track is handled independently and the outcome is reported per-track in
  the completion summary. An invalid or non-public playlist URL fails the whole import
  up front with a clear message.
- **Download failure (post-ingest):** logged, informational only; does not affect the
  `Contribution`, votes, or export.
- **Export to external service failure (Phase 3/4):** the `ExportSnapshot` still exists
  (it is computed before any push); the push is retryable without re-rolling.
- **Invalid invite token / expired magic link:** clear, friendly error pages.

## Testing Strategy

- **Selection engine:** the materialization algorithm is pure given (contributions,
  votes, settings, seed) — unit-tested exhaustively, including the guaranteed-exceeds-max
  edge case, min top-up, and max trimming. Deterministic via seed.
- **Curve:** unit tests over `net` → `p` at and between every anchor.
- **Permissions:** tests asserting each role can/cannot perform each action.
- **Resolution interface (Phase 0):** provider calls mocked; cascade fallthrough tested.
- **Bulk import:** mocked `resolve_playlist`; tests assert correct add/skip/unresolved
  partitioning, importer attribution on every added track, and an accurate summary.
- **Lifecycle:** tests that snapshot immutability holds across contribution/member
  removal.
- pytest (API) and Vitest (frontend), matching TuneStash conventions.

## Future Work — Playback App

A normal music player pointed at an `ExportSnapshot`. It does **not** re-shuffle live;
it plays the materialized tracklist like any ordinary playlist. Because export and
playback both consume the identical `ExportSnapshot` artifact, "build the playback app
later" is additive, not a rewrite. Fork-vs-build is evaluated as its own project if/when
this phase is taken up.

## Open Questions / Deferred Details

- Final project name.
- Exact personal-filter set for exports (Phase 2 spec).
- m3u flavor — extended metadata list vs local-file paths (Phase 2 spec).
- Dedicated Celery queue vs rate limit for Songboard-triggered downloads (Phase 0 spec).
- Reduced-privilege DB role for the public process (deployment hardening).
