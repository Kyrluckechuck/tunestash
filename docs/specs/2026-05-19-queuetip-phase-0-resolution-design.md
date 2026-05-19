# Queuetip Phase 0 — TuneStash Resolution Interface

**Status:** Design approved — sub-project spec
**Date:** 2026-05-19
**Parent:** `2026-05-19-queuetip-collaborative-playlist-design.md` (program spec)
**Branch:** `songboard-design` (branch name predates the "Queuetip" rename) — remove
specs before merging to main (`.gitignore:56-58`).

## Purpose

Phase 0 builds the resolution layer that all later Queuetip phases depend on: turning
search queries, pasted links, and external playlist URLs into TuneStash `Song` rows with
cross-platform identity. It is an internal Python interface (Option A — same codebase),
not an HTTP API.

## Scope

Four in-process functions:

1. `catalog_search(query)` — search for a track to contribute (Deezer-backed).
2. `resolve_link(url)` — resolve a single pasted track URL.
3. `resolve_playlist(url)` — expand a Spotify/Apple playlist URL into track candidates.
4. `ingest_track(candidate)` — create a `Song` (+ queued download) from a candidate.

(The program spec listed a separate `provider_search`; it folds into `catalog_search` —
see below.)

Out of scope: the Queuetip app itself (Phase 1+), voting, the selection engine, export.

## Validation Results (empirically verified 2026-05-19)

These were tested with live scripts, not assumed. Recorded so they are not re-litigated.

### Apple Music — playlist read WITHOUT a developer account ✅

- The public web page `music.apple.com/{storefront}/playlist/{slug}/{id}` returns HTTP
  200 to an anonymous request with a browser User-Agent.
- The page is a Vite SPA. Its main bundle is `/assets/index~<hash>.js`. **The `<hash>`
  changes on every Apple redeploy** — the resolver MUST parse the current bundle URL
  from the page HTML; never hardcode it.
- The bundle embeds an `AMPWebPlay` ES256 JWT (`kid: WebPlayKid`, `iss: AMPWebPlay`).
  Observed validity ~84 days. This is the bearer token for Apple's Amp API.
- With `Authorization: Bearer <token>` + `Origin: https://music.apple.com`, the
  endpoints `amp-api.music.apple.com/v1/catalog/{storefront}/playlists/{id}` and
  `.../playlists/{id}/tracks` return HTTP 200. This is Apple's real (documented-shape)
  API — only the token acquisition is unofficial.
- **Apple single-song endpoint verified:** `amp-api.music.apple.com/v1/catalog/
  {storefront}/songs/{id}` returns HTTP 200 with `name`, `artistName`, `isrc`,
  `albumName` — so `resolve_link` for Apple song URLs works via the same token.
- Each playlist track carries `attributes.name`, `attributes.artistName`, and
  `attributes.isrc`.
- Pagination: follow the relative `next` field. **`next` drops the `limit` param** — do
  not assume a fixed page size; follow `next` until absent.
- **Verified:** 59-track user playlist read end-to-end; multi-page pagination correct
  (no overlap). User playlists (`pl.u-`) have NO schema.org JSON-LD block (curated
  playlists do) — so JSON-LD is not a usable path; the token+Amp-API route is required.
- **Token re-acquisition is the scrape itself:** re-running page → bundle → regex
  yields the current token (verified repeatable). The resolver must never hardcode a
  token; it auto-refreshes on 401 / near-expiry by re-scraping.

### Spotify — playlist read via TuneStash's existing app ✅

- TuneStash already has a registered Spotify app; credentials live in DB settings
  `spotipy_client_id` / `spotipy_client_secret`, read via
  `src.app_settings.registry.get_setting` (both verified populated).
- The client-credentials flow (`spotipy.SpotifyClientCredentials`) reads **public,
  user-created** playlists. No per-user OAuth needed for import.
- Each track carries name, multiple artists, and `external_ids.isrc`.
- Pagination via `playlist_items` + `sp.next` — **verified** on a real 172-track user
  playlist (4 pages, all 172 tracks).
- **Editorial / algorithmic playlists (owner `spotify`) return HTTP 404** under
  client-credentials (Spotify's late-2024 API restriction) — **verified** against
  "Today's Top Hits". `resolve_playlist` MUST detect this and return a clear,
  user-facing error rather than an empty result.

### Cross-source

Both sources return ISRC. Duplicate tracks within a single source playlist are possible
(verified — a real playlist contained one) and are handled downstream by Queuetip's
`(playlist, song)` unique constraint, reported as "already present."

## The Candidate Shape

`resolve_link` and `resolve_playlist` emit a uniform DTO regardless of source:

```
TrackCandidate:
    track_name:   str
    artist_name:  str            # PRIMARY artist ONLY — never a joined multi-artist
                                 #   string (verified: joined strings degrade
                                 #   TrackMappingService fuzzy scoring; see ingest_track)
    all_artists:  list[str]      # full artist list — display only, not for matching
    isrc:         str | None
    source:       str            # "spotify" | "apple" | "deezer"
    source_id:    str | None     # provider track id, when known
```

This uniform shape is the seam that lets the two very different integrations feed one
ingest path.

## Function Designs

### `catalog_search` — Deezer-backed, with `provider_search` folded in

The program spec's two-tier "local catalog vs provider" split does not match reality:
`api/src/services/catalog_search.py`'s `CatalogSearchService.search()` already searches
Deezer and flags which results are `in_library`. Phase 0 exposes a single
`catalog_search(query)` that wraps `CatalogSearchService`, returning candidates with an
`in_library` flag and `local_id` when present. There is no separate local-index search.

### `resolve_link(url) -> TrackCandidate`

Parse a single track URL and resolve it. Per-provider support is **verified**:
- **Spotify** — `extract_spotify_id_and_type` in `spotify_validation.py` (exists);
  fetch track via spotipy → name/artist/ISRC. FULLY SUPPORTED.
- **Apple Music** song URL — via the Apple resolver; the catalog `songs` Amp-API
  endpoint is verified (see Validation Results). FULLY SUPPORTED.
- **Deezer** track URL — `_DEEZER_URL_REGEX` in `downloader.py` parses track URLs and
  `DeezerMetadataProvider.get_track` returns name/artist/ISRC (both exist). FULLY
  SUPPORTED.
- **YouTube Music** — **NOT supported in v1.** YouTube Music exposes no ISRC (verified
  via `ytmusicapi` — `get_song` and search results contain no recording identifier),
  which would force the unreliable fuzzy name-match path. A friend with only a YouTube
  link uses the search box instead.
Returns one `TrackCandidate`; raises a recoverable error if the URL is unsupported or
the track cannot be found.

### `resolve_playlist(url) -> list[TrackCandidate]`

Two source-specific resolvers behind one dispatch on URL host:

**`SpotifyPlaylistResolver`**
- Credentials from `get_setting('spotipy_client_id' / 'spotipy_client_secret')`.
- `spotipy` client-credentials; `playlist_items` paginated via `sp.next`.
- On HTTP 404 with an editorial/owner-`spotify` playlist: raise
  `EditorialPlaylistError` with a message telling the user to supply a user-created
  playlist.

**`AppleMusicPlaylistResolver`** — isolated module, the only brittle surface (~one file):
1. Fetch the playlist web page; regex the current `/assets/index~<hash>.js` URL.
2. Fetch the bundle; regex the `AMPWebPlay` JWT. **Cache the token**; auto-refresh on
   401 / near expiry by re-scraping (the re-scrape is the refresh — verified repeatable).
3. Call `amp-api.music.apple.com/v1/catalog/{storefront}/playlists/{id}/tracks`,
   following `next` until absent (do not assume a page size).
4. Storefront and playlist id are parsed from the URL path.
Fallback (only if token extraction breaks): parse the `serialized-server-data` JSON
blob from the page. Documented as a fallback, not built unless needed.

### `ingest_track(candidate) -> Song`

Reuses the create-Song logic of `_match_or_create_song_from_spotify_track`
(`api/library_manager/tasks/download.py`, lines 669–729). **Verified:** that function is
already fully download-decoupled — it creates/finds and returns a `Song`, queues no
download itself — so extracting it into a shared helper is a copy/move, not an
untangling.

1. Match an existing `Song`: **ISRC first** — a local `Song` ISRC lookup and
   `DeezerMetadataProvider.get_track_by_isrc` (verified working); then provider id;
   then `TrackMappingService.map_track(primary_artist, track)` fuzzy name match **only
   as a last resort**.
2. When calling `map_track`, pass **only the primary artist** (`candidate.artist_name`)
   — never a joined multi-artist string (verified RISKY: joined strings lower fuzzy
   match confidence and can false-negative).
3. If no match, create a `Song` **synchronously** so the caller gets identity at once.
4. Queue an async TuneStash download (Celery) — never block on it.

Identity is synchronous; download is asynchronous and its success is not a gate. Because
both Spotify and Apple supply ISRC, the fuzzy name-match path — the only step sensitive
to multi-artist strings — is rarely reached.

## ExternalList — explicitly NOT used

`ExternalList` / `ExternalListTrack` model *tracked, re-syncing* external lists. A
Queuetip import is a **one-shot bulk-add**. `resolve_playlist` → `ingest_track` →
`Contribution` rows directly; no `ExternalList` rows are created. (`ExternalListSource`
also has no `spotify` value, confirming these are separate concerns.)

## Error Handling

- **Apple token extraction failure** (bundle structure changed): raise a specific
  `AppleResolverError`; surface "Apple import temporarily unavailable" to the user; log
  loudly so the resolver can be repaired.
- **Spotify editorial playlist**: `EditorialPlaylistError`, clear user message.
- **Private / invalid / non-existent playlist URL**: fail the whole import up front.
- **Individual track resolution failure** inside a playlist: skipped, counted, reported
  per-track — never aborts the import.
- **Network/timeout**: bounded retries, then a recoverable error to the caller.

## Testing

- **Apple resolver**: mock the page HTML, JS bundle, and Amp-API responses; test bundle
  URL extraction, token extraction, pagination via `next`, and the `serialized-server-
  data` fallback path. One integration test (network, opt-in/marked) against a real
  public playlist.
- **Spotify resolver**: mock spotipy; test pagination and the editorial-404 path.
- **`resolve_link`**: per-provider URL parsing (Spotify/Apple/Deezer), including
  malformed and unsupported (YouTube) URLs.
- **`ingest_track`**: ISRC-match, provider-id-match, name-match, and create paths; that
  `map_track` is called with the primary artist only; that download is queued but not
  awaited; duplicate handling.
- **`catalog_search`**: `in_library` flagging.
- pytest, matching TuneStash conventions; provider calls mocked by default.

## Open Questions / Deferred

- Where to cache the Apple token (module-level vs a DB `AppSetting`) — implementation
  detail; DB is more robust across worker restarts.
- Throttling/politeness for the Apple web fetches (page + bundle) — light, but define a
  small rate limit during implementation.
- Verifying Apple/Spotify pagination on genuinely huge (>1000-track) playlists — the
  `next`-loop mechanism is verified; extreme scale is assumed standard.
