# Queuetip Phase 2B — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a usable Queuetip web frontend covering the full MVP-plus-polish scope: magic-link sign-up/sign-in, playlist list + create, join via invite link (with preview), playlist view (members, contributions, vote tallies), contribute via search + paste-link with duplicate-detected UX, bulk import with progress polling, vote cast/clear, owner-only settings + invite regenerate + kick/promote, leave, export create + m3u download.

**Architecture:** A new Vite + React + TS app at `queuetip-frontend/`, completely separate from TuneStash's `frontend/`. Apollo Client talks to the Queuetip public ASGI at `:5050`. TanStack Router for file-based routing. TailwindCSS + shadcn/ui (vendored Radix components) for the UI primitives. A new `queuetip-frontend-dev` Docker service exposed at `:3001` mirroring how `frontend-dev` is exposed at `:3000`.

**Tech Stack:** Vite 5+, React 18+, TypeScript 5+, Apollo Client 3+, TanStack Router 1+, TailwindCSS 3+, shadcn/ui (Radix UI underneath), Vitest + React Testing Library for tests, GraphQL Code Generator for typed operations.

**Phase 1+2A spec:** `2026-05-19-queuetip-collaborative-playlist-design.md` (program), `2026-05-19-queuetip-phase-1-core-design.md` (auth + GraphQL contract).

---

## Backend the frontend talks to

Public Queuetip ASGI on `:5050` (separate container from TuneStash's `web`):
- `POST /graphql` — 7 queries + 16 mutations from Phases 1+2A.
- `GET /auth/verify?token=<t>` — sets the session cookie, renders confirmation.
- `POST /auth/logout` — clears cookie.
- `GET /exports/{id}.m3u` — session-cookie-authed download.
- `GET /health` — `ok`.

Auth: `queuetip_session` HttpOnly cookie set by `/auth/verify`. The frontend never reads it directly — it's sent automatically with credentialed fetches. Frontend infers "signed in" by calling the `me` query and inspecting `null` vs an account.

CORS: the public app's allowlist is configured to `QUEUETIP_FRONTEND_URL` (env var, default `http://localhost:3001`). Apollo must send `credentials: "include"`.

---

## Pages (MVP + polish — 7 routes)

| Route | Purpose | Auth |
|---|---|---|
| `/` | Landing; if signed in → redirect to `/playlists`; else CTA "Sign up / Sign in" | public |
| `/sign-in` | Email + display-name form → `requestMagicLink` → "Check your email" view (same page, two states) | public |
| `/playlists` | "My playlists" list + "New playlist" modal/CTA | required |
| `/playlists/:id` | Playlist detail — members, contributions list with vote buttons + tallies, contribute CTAs, role-aware settings/kick/promote/leave/delete, bulk-import + export buttons | required (member) |
| `/join/:token` | Anonymous preview (playlist name + members), "Join" button (if signed-in) or "Sign in to join" link | public preview, signed-in to join |
| `/exports/:id` | Export snapshot view — tracks list with inclusion reason + roll probability, "Download m3u" link | required (member) |
| `*` (404) | "Not found" | public |

Modals/dialogs (rendered inside parent pages, not separate routes):
- New playlist (on `/playlists`)
- Contribute (on `/playlists/:id` — tabs: search / paste link)
- Bulk import (on `/playlists/:id` — paste URL + progress)
- Edit settings (on `/playlists/:id`, owner-only)
- Confirm delete playlist (on `/playlists/:id`, owner-only)
- Create export options (on `/playlists/:id` — `excludeMyDownvotes` toggle, then redirects to `/exports/:id`)

UX rules:
- All mutations show errors via toasts (shadcn `<Toaster>` from sonner).
- Optimistic updates **only** for `castVote`/`clearVote` (vote toggling needs to feel snappy). Everything else waits for the server response, then refetches the affected query (`refetchQueries`).
- Auth state is observed via a single `useMe()` hook that wraps the `me` query; route guards read it.
- Duplicate-detected contribute returns `alreadyPresent=true` — the modal shows an inline confirmation: "Already in the playlist. Upvote it instead?" → calls `castVote(contributionId, +1)` and closes.
- The export download link uses the `m3uUrl` field returned by `createExport` / `export` (full URL including `QUEUETIP_PUBLIC_URL` baked in by the backend).

---

## File Structure

| Path | Responsibility |
|---|---|
| `queuetip-frontend/package.json` | Vite + React + deps |
| `queuetip-frontend/vite.config.ts` | Vite + path alias `@/*` |
| `queuetip-frontend/tsconfig.json` | TS strict, `@/*` alias |
| `queuetip-frontend/tailwind.config.ts` | Tailwind config (shadcn-compatible) |
| `queuetip-frontend/postcss.config.js` | Tailwind/PostCSS |
| `queuetip-frontend/components.json` | shadcn/ui config |
| `queuetip-frontend/index.html` | Vite entry HTML |
| `queuetip-frontend/Dockerfile` | (optional) frontend build; dev runs `vite dev` directly |
| `queuetip-frontend/.eslintrc.cjs` | ESLint TS + react-hooks |
| `queuetip-frontend/codegen.ts` | GraphQL Code Generator config |
| `queuetip-frontend/src/main.tsx` | App entry; Apollo provider; router |
| `queuetip-frontend/src/index.css` | Tailwind directives + shadcn CSS vars |
| `queuetip-frontend/src/lib/apollo.ts` | Apollo client (credentials: include) |
| `queuetip-frontend/src/lib/utils.ts` | shadcn-style `cn(...)` util |
| `queuetip-frontend/src/lib/auth.ts` | `useMe()` hook + auth helpers |
| `queuetip-frontend/src/components/ui/*` | shadcn vendored primitives (button, input, dialog, dropdown, toast, etc.) |
| `queuetip-frontend/src/components/Layout.tsx` | App shell (header + sign-out + content) |
| `queuetip-frontend/src/components/RequireAuth.tsx` | Route guard |
| `queuetip-frontend/src/queries/*.graphql` | GraphQL documents (operations) |
| `queuetip-frontend/src/types/generated/*` | Codegen output (committed) |
| `queuetip-frontend/src/routes/__root.tsx` | TanStack Router root |
| `queuetip-frontend/src/routes/index.tsx` | `/` landing |
| `queuetip-frontend/src/routes/sign-in.tsx` | `/sign-in` |
| `queuetip-frontend/src/routes/playlists.index.tsx` | `/playlists` |
| `queuetip-frontend/src/routes/playlists.$id.tsx` | `/playlists/:id` |
| `queuetip-frontend/src/routes/join.$token.tsx` | `/join/:token` |
| `queuetip-frontend/src/routes/exports.$id.tsx` | `/exports/:id` |
| `queuetip-frontend/src/features/...` | Feature components (contribute modal, vote buttons, member list, etc.) |
| `queuetip-frontend/src/test/setup.ts` | Vitest + RTL setup |
| `queuetip-frontend/src/**/__tests__/*.test.tsx` | Component tests |
| `docker-compose.yml` *(modify)* | Add `queuetip-frontend` (base) |
| `docker-compose.override.yml` *(modify)* | Add `queuetip-frontend-dev` (Vite dev) |
| `api/src/queuetip/app.py` *(modify)* | Maybe widen CORS regex in dev to include `:3001` |

Conventions:
- ESLint + Prettier on TS files (mirroring `frontend/`).
- All new TS files commit cleanly via `yarn lint`.
- `yarn test` runs Vitest.
- Run frontend commands inside the dev container OR with local Node 20+ (matches the existing repo). Per CLAUDE.md, run frontend locally when convenient — Docker for parity.
- Commits with `--no-gpg-sign`, no Claude footer, pre-commit autorun.

---

### Task 1: Scaffold `queuetip-frontend/` + Vite + TS + Tailwind + shadcn/ui

**Files:** all under `queuetip-frontend/`; modify `docker-compose.yml` + `.override.yml`.

The scaffold is mechanical but lengthy. The implementer should follow this order:

- [ ] **Step 1:** `cd queuetip-frontend && yarn create vite . --template react-ts` (or write the equivalent `package.json` + `vite.config.ts` + `index.html` + `src/main.tsx` + `src/App.tsx` manually if `yarn create vite` is awkward inside this repo layout). The implementer may need to manually create files since `yarn create vite` in a non-empty/existing repo can be fiddly — fall back to writing the minimal Vite-React-TS scaffold by hand (the canonical 6 files: `package.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.node.json`, `index.html`, `src/main.tsx`).

- [ ] **Step 2:** Install dependencies. `package.json` runtime deps:
  ```
  react, react-dom, @apollo/client, graphql, @tanstack/react-router, tailwindcss-animate, class-variance-authority, clsx, tailwind-merge, lucide-react, sonner
  ```
  dev deps:
  ```
  @vitejs/plugin-react, typescript, @types/react, @types/react-dom, tailwindcss, postcss, autoprefixer, vite, vitest, @testing-library/react, @testing-library/jest-dom, @testing-library/user-event, jsdom, @graphql-codegen/cli, @graphql-codegen/client-preset, eslint, @typescript-eslint/parser, @typescript-eslint/eslint-plugin, eslint-plugin-react-hooks, prettier
  ```
  Run `yarn install` inside `queuetip-frontend/`. Verify `node_modules` populates.

- [ ] **Step 3:** Initialize Tailwind: `npx tailwindcss init -p` produces `tailwind.config.js` and `postcss.config.js`. Convert to `tailwind.config.ts`. Configure `content: ["./index.html", "./src/**/*.{ts,tsx}"]`.

- [ ] **Step 4:** Initialize shadcn/ui: `npx shadcn@latest init` (accept defaults: TS, Tailwind, `@/components` alias, `src/index.css` for CSS vars, neutral base color). This writes `components.json` + a starter `src/components/ui/` + adjusts `tailwind.config.ts` with the shadcn theme variables. Verify `src/index.css` got the CSS variables block.

- [ ] **Step 5:** Add the initial components: `npx shadcn@latest add button input label dialog dropdown-menu toast sonner card form badge separator tabs`. These cover the MVP+polish scope; more can be added per-task as needed.

- [ ] **Step 6:** Install TanStack Router and configure file-based routing per its docs. The router config goes in `vite.config.ts` (the TanStack Router Vite plugin auto-generates `src/routeTree.gen.ts` from files under `src/routes/`). Add a stub `src/routes/__root.tsx` and `src/routes/index.tsx` so the router has something to render.

- [ ] **Step 7:** Wire Apollo client in `src/lib/apollo.ts`:
  ```ts
  import { ApolloClient, InMemoryCache, createHttpLink } from "@apollo/client";

  const httpLink = createHttpLink({
    uri: import.meta.env.VITE_QUEUETIP_GRAPHQL_URL ?? "http://localhost:5050/graphql",
    credentials: "include",
  });

  export const apolloClient = new ApolloClient({
    link: httpLink,
    cache: new InMemoryCache(),
  });
  ```

- [ ] **Step 8:** `src/main.tsx` wires `ApolloProvider`, `RouterProvider`, `<Toaster />`. Render a simple "Queuetip — hello" h1 from `src/routes/index.tsx` to prove the bootstrap works.

- [ ] **Step 9:** Add `queuetip-frontend` to `docker-compose.yml` (base build):
  ```yaml
    queuetip-frontend:
      image: ${QUEUETIP_FRONTEND_IMAGE:-ghcr.io/kyrluckechuck/queuetip-frontend:latest}
      depends_on:
        queuetip:
          condition: service_healthy
      networks:
        - slm_net
      ports:
        - "${QUEUETIP_FRONTEND_PORT:-3001}:80"
      restart: unless-stopped
  ```
  (Production nginx-static image; CI will build it later. For now `image:` may not exist — the dev override below is what gets run.)

  Add `queuetip-frontend-dev` to `docker-compose.override.yml`:
  ```yaml
    queuetip-frontend-dev:
      build:
        context: ./queuetip-frontend
        target: development
      command: yarn dev --host 0.0.0.0 --port 3001
      volumes:
        - ./queuetip-frontend:/app
        - /app/node_modules
      ports:
        - "3001:3001"
      depends_on:
        queuetip:
          condition: service_healthy
      environment:
        - VITE_QUEUETIP_GRAPHQL_URL=http://localhost:5050/graphql
      networks:
        - slm_net
  ```
  Plus a minimal `queuetip-frontend/Dockerfile` with a `development` target (`FROM node:20-alpine`, `WORKDIR /app`, `RUN yarn install`, `CMD yarn dev`). Mirror `frontend/Dockerfile`'s pattern if it exists.

- [ ] **Step 10:** Start the dev service: `docker compose up -d queuetip-frontend-dev`. Verify `curl -s http://localhost:3001` returns the Vite-rendered HTML. Commit.

**Commit message:** `feat(queuetip-frontend): scaffold Vite + React + TS + Tailwind + shadcn/ui`

---

### Task 2: GraphQL Code Generator wired to Queuetip schema

**Files:** `queuetip-frontend/codegen.ts`, `queuetip-frontend/src/queries/*.graphql`, `queuetip-frontend/src/types/generated/*`

Mirror TuneStash's frontend's GraphQL codegen approach (see `frontend/codegen.ts` and `Makefile`'s `graphql-generate`). Adjust the schema source to the Queuetip schema (a separate file — the Phase 1 design committed not to share schemas between admin and public).

- [ ] **Step 1:** Export the Queuetip GraphQL SDL to a local file: `docker compose exec -T web python -c "import django; django.setup(); from src.queuetip.schema import schema; from strawberry.printer import print_schema; print(print_schema(schema))"` > `queuetip-frontend/src/types/generated/queuetip-schema.graphql`. Verify the file is non-empty and includes all the queries/mutations.

- [ ] **Step 2:** Write `queuetip-frontend/codegen.ts`:
  ```ts
  import type { CodegenConfig } from "@graphql-codegen/cli";

  const config: CodegenConfig = {
    schema: "./src/types/generated/queuetip-schema.graphql",
    documents: ["./src/queries/**/*.graphql"],
    generates: {
      "./src/types/generated/": {
        preset: "client",
        presetConfig: { fragmentMasking: false },
      },
    },
  };
  export default config;
  ```

- [ ] **Step 3:** Add to `package.json`:
  ```json
  "scripts": {
    "generate": "graphql-codegen",
    "generate:watch": "graphql-codegen --watch"
  }
  ```

- [ ] **Step 4:** Write 2 starter queries to prove the pipeline:
  - `src/queries/me.graphql`:
    ```graphql
    query Me { me { id displayName } }
    ```
  - `src/queries/auth.graphql`:
    ```graphql
    mutation RequestMagicLink($email: String!, $displayName: String) {
      requestMagicLink(email: $email, displayName: $displayName) { sent message }
    }
    ```

- [ ] **Step 5:** Run `yarn generate`. Verify `src/types/generated/graphql.ts` (or similar) appears with `MeQuery`, `MeQueryVariables`, `RequestMagicLinkMutation`, etc.

- [ ] **Step 6:** Add a `Makefile` target `queuetip-graphql-generate` (mirroring `graphql-generate`) that re-exports the schema and runs codegen.

- [ ] **Step 7:** Commit `feat(queuetip-frontend): GraphQL codegen + me/auth queries`.

---

### Task 3: Magic-link sign-in flow

**Files:**
- `queuetip-frontend/src/lib/auth.ts` — `useMe()` hook.
- `queuetip-frontend/src/routes/sign-in.tsx` — sign-in page.
- `queuetip-frontend/src/routes/index.tsx` — landing page with auth-aware redirect.
- `queuetip-frontend/src/components/Layout.tsx` — basic shell.
- Tests under `__tests__/`.

`/sign-in` is a one-form page that calls `requestMagicLink(email, displayName?)`. After a successful response, switch to a "check your email" view (same page, conditional render). Two pieces of feedback: `sent=true` → "Check your email." `sent=false, message="..."` → show the message inline (e.g. "Provide a display name to sign up").

`useMe()` wraps the `Me` query and exposes `{ account: Account | null, loading, refetch }`. Used by `<RequireAuth>` route guard (Task 5).

Layout: a top bar with "Queuetip" wordmark on the left; on the right, the user's display name + a dropdown with "Sign out" (calls `POST /auth/logout` via `fetch(..., { credentials: "include" })` then refetches `me`).

Visual: shadcn `<Card>` for the sign-in form, `<Input>` + `<Label>` + `<Button>`. Success state: shadcn `<Card>` with a green checkmark `Lucide` icon + the message + a "back to sign-in" link.

Tests: render `/sign-in`, fill email + name, click Submit, mock Apollo response, assert "Check your email" text appears.

Commit: `feat(queuetip-frontend): magic-link sign-in + Layout shell`.

---

### Task 4: My playlists list + create modal

**Files:**
- `src/queries/playlists.graphql` — `MyPlaylists`, `CreatePlaylist`.
- `src/routes/playlists.index.tsx` — list page.
- `src/features/playlists/NewPlaylistDialog.tsx`.
- Tests.

GraphQL:
```graphql
query MyPlaylists { myPlaylists { id name description createdAt members { account { displayName } role } } }
mutation CreatePlaylist($name: String!, $description: String) {
  createPlaylist(name: $name, description: $description) { id }
}
```

Page: shadcn `<Card>` per playlist (name, member count, "Open" link to `/playlists/:id`). "New playlist" button opens a `<Dialog>` with name + description form. On submit, run the mutation, `refetchQueries: ["MyPlaylists"]`, navigate to the new playlist on success.

Tests: render the page with a mocked `MyPlaylists` response containing 2 playlists; assert both names render. Render the dialog, fill the name, click Create, assert mutation called with the right vars.

Commit: `feat(queuetip-frontend): my-playlists list + create dialog`.

---

### Task 5: Route guards + Layout polish

**Files:**
- `src/components/RequireAuth.tsx`.
- Apply guards to `/playlists`, `/playlists/:id`, `/exports/:id` routes.

`<RequireAuth>` wraps a route's component: while `useMe()` is `loading`, render a centered spinner; if `account is null`, `<Navigate to="/sign-in" />`; else render children. Apply via TanStack Router's `component:` field.

Layout: when signed-in, show the user dropdown; when not, show "Sign in" link in the top bar.

Tests: render `<RequireAuth><div>secret</div></RequireAuth>` with anonymous `me` mock → assert `secret` is NOT in the document and a `/sign-in` redirect happens (use the TanStack Router test harness).

Commit: `feat(queuetip-frontend): route guard + auth-aware Layout`.

---

### Task 6: Playlist detail page (members + contributions + voting)

**Files:**
- `src/queries/playlist.graphql` — `PlaylistDetail`, `CastVote`, `ClearVote`, `RemoveContribution`, `LeavePlaylist`, `KickMember`, `PromoteMember`, `RegenerateInviteToken`, `DeletePlaylist`.
- `src/routes/playlists.$id.tsx`.
- `src/features/playlist/ContributionRow.tsx` (vote buttons + tally + remove).
- `src/features/playlist/MemberList.tsx`.
- Tests.

`PlaylistDetail` query asks for: playlist name + description + invite token + members (account + role) + contributions (song + contributor + votes + net_score). The `playlist(id)` query returns this.

Page layout:
- Header: name + description + member count badge + (owner-only) "Settings" + "Regenerate invite" + "Delete" buttons.
- Sidebar: invite link with copy-to-clipboard + member list (each member with role badge; owner sees kick/promote dropdown next to members).
- Main: contributions list. Each row shows song title + artist + contributor display name + a `+ N - M` vote tally + vote buttons (clickable; the caller's current vote is highlighted; clicking again clears).
- Footer: action buttons — "Contribute" (opens Task 7's dialog), "Bulk import" (Task 8), "Create export" (Task 9), "Leave" (member-only, not last owner).

Optimistic update for `castVote`: update the `playlist.contributions[].votes` array locally so the net_score shifts immediately, then revert on error. `clearVote` mirrors. Apollo `optimisticResponse` + `update` pattern; see `frontend/`'s existing optimistic patterns for reference.

Tests: render the page with a mocked playlist that has 3 contributions; assert each renders. Click a vote button, assert mutation called with the right vars + the optimistic UI shifts.

Commit: `feat(queuetip-frontend): playlist detail page with members + contributions + voting`.

---

### Task 7: Contribute dialog (search + paste link, dedup UX)

**Files:**
- `src/queries/contribute.graphql` — `CatalogSearch`, `ContributeFromSearch`, `ContributeFromLink`.
- `src/features/playlist/ContributeDialog.tsx`.
- Tests.

GraphQL:
```graphql
query CatalogSearch($query: String!, $limit: Int) {
  catalogSearch(query: $query, limit: $limit) { deezerId title artist isrc inLibrary }
}
mutation ContributeFromSearch($playlistId: ID!, $deezerTrackId: String!) {
  contributeFromSearch(playlistId: $playlistId, deezerTrackId: $deezerTrackId) {
    alreadyPresent
    contribution { id song { title artist } netScore }
  }
}
mutation ContributeFromLink($playlistId: ID!, $url: String!) {
  contributeFromLink(playlistId: $playlistId, url: $url) {
    alreadyPresent
    contribution { id song { title artist } netScore }
  }
}
```

Dialog uses shadcn `<Tabs>`: "Search" and "Paste link." Search tab: debounced `<Input>` (300ms) → `CatalogSearch` → results list with "Add" button per hit. Paste-link tab: `<Input>` for the URL + "Add" button.

After mutation:
- `alreadyPresent === false` → toast "Added to playlist", refetch `PlaylistDetail`, close dialog.
- `alreadyPresent === true` → switch to an inline confirmation card: "*Song X* is already in the playlist. Upvote it?" → "Upvote" button calls `CastVote(contributionId: ..., value: 1)`; "Dismiss" button just refetches and closes.

Tests: render the dialog, type in search, mock the catalog response, click a result, mock `contributeFromSearch` returning `alreadyPresent=false`, assert the dialog closes and the parent `refetchQueries` ran. Separate test for the `alreadyPresent=true` confirmation flow.

Commit: `feat(queuetip-frontend): contribute dialog (search + paste link + dedup UX)`.

---

### Task 8: Bulk import + progress polling

**Files:**
- `src/queries/bulk_import.graphql` — `BulkImportPlaylist`, `BulkImportJob`.
- `src/features/playlist/BulkImportDialog.tsx`.
- Tests.

GraphQL:
```graphql
mutation BulkImportPlaylist($playlistId: ID!, $url: String!) {
  bulkImportPlaylist(playlistId: $playlistId, url: $url) {
    id status sourceUrl addedCount skippedCount unresolvedCount unresolvedTitles error
  }
}
query BulkImportJob($id: ID!) {
  bulkImportJob(id: $id) { id status addedCount skippedCount unresolvedCount unresolvedTitles error finishedAt }
}
```

Dialog: paste URL → "Import" button → mutation returns a job with `status: "pending"`. Dialog then switches to a progress view that calls `BulkImportJob` every 2 seconds via Apollo `pollInterval`. When `status` becomes `succeeded` or `failed`, stop polling, show the result summary (counts + unresolved titles or error). After success, refetch `PlaylistDetail` so the new contributions appear.

Tests: mock the mutation returning `status: "pending"`. Use Apollo's MockedProvider with a sequence of responses for the polled query (`pending → running → succeeded` over 3 calls). Assert the dialog renders the final summary text.

Commit: `feat(queuetip-frontend): bulk import dialog with progress polling`.

---

### Task 9: Export create + snapshot page + m3u download

**Files:**
- `src/queries/export.graphql` — `CreateExport`, `Export`, `MyPlaylistExports`.
- `src/features/playlist/CreateExportDialog.tsx`.
- `src/routes/exports.$id.tsx`.
- Tests.

GraphQL:
```graphql
mutation CreateExport($playlistId: ID!, $options: ExportOptionsInput) {
  createExport(playlistId: $playlistId, options: $options) {
    id rngSeed warningMessage m3uUrl
  }
}
query Export($id: ID!) {
  export(id: $id) {
    id createdAt requestedBy { displayName } warningMessage m3uUrl
    tracks { id song { title artist } position inclusionReason rollProbability }
  }
}
query MyPlaylistExports($playlistId: ID!) {
  myPlaylistExports(playlistId: $playlistId) { id createdAt warningMessage m3uUrl }
}
```

Create dialog: shadcn `<Switch>` for `excludeMyDownvotes` (default off), "Create export" button. On submit, run the mutation, navigate to `/exports/{newId}` on success. If `warningMessage` is non-empty (guaranteed-exceeds-max case), show it as a yellow `<Alert>` on the snapshot page.

Snapshot page (`/exports/:id`): header with playlist name (look up via `Export.playlist` — note: the GraphQL `ExportSnapshotType` we built in 2A doesn't currently include `playlist` — verify by inspecting `src.queuetip.graphql_types.ExportSnapshotType`. If absent, add a `playlist: PlaylistType` field to the type and regen the schema before writing this task. Cleanest fix: extend `ExportSnapshotType.from_model` to include the playlist).

Tracks list: a numbered table, each row shows position + artist - title + inclusion-reason badge + roll-probability percentage. Big "Download m3u" button links to `m3uUrl`. Clicking opens the file in a new tab (browser handles `Content-Disposition: attachment`).

Tests: mock `CreateExport` returning a snapshot id; render dialog, click submit, assert navigation. Snapshot page: mock `Export` with 3 tracks, assert all render in order with their inclusion reasons.

Commit: `feat(queuetip-frontend): export create + snapshot page + m3u download`.

---

### Task 10: Join via invite (`/join/:token`) + edit-settings dialog + final polish

**Files:**
- `src/queries/join.graphql` — `PlaylistByInviteToken`, `JoinPlaylist`.
- `src/routes/join.$token.tsx`.
- `src/queries/settings.graphql` — `UpdatePlaylistSettings`.
- `src/features/playlist/EditSettingsDialog.tsx`.
- 404 route.
- Tests.

GraphQL:
```graphql
query PlaylistByInviteToken($token: String!) {
  playlist(inviteToken: $token) {
    id name description members { account { displayName } role }
  }
}
mutation JoinPlaylist($token: String!) {
  joinPlaylist(inviteToken: $token) { id }
}
mutation UpdatePlaylistSettings($id: ID!, $name: String, $description: String, $engine: EngineSettingsInput) {
  updatePlaylistSettings(id: $id, name: $name, description: $description, engine: $engine) { id name description }
}
```

`/join/:token` page (anonymous-accessible): runs `PlaylistByInviteToken`. Renders the playlist name + members + a "Join" button. If `useMe()` is anonymous, the button reads "Sign in to join" and links to `/sign-in?next=/join/{token}` (sign-in flow should respect `next=` query param and redirect there after sign-in lands a session). If signed-in, button runs `JoinPlaylist` then navigates to `/playlists/{id}`. If already a member, button reads "Open playlist" and navigates directly.

Settings dialog (owner-only): form with name, description, plus an "Engine" accordion section with min_size, max_size (nullable — checkbox to enable, then number), t_high, t_low, base, p_floor. Submit calls `UpdatePlaylistSettings`. Show validation errors inline.

404 route: shadcn `<Card>` with "Page not found" + link home.

Final polish: hook up the leftover unimplemented buttons from Task 6 (kick/promote/leave/delete playlist). Each opens a confirm `<Dialog>` and calls the corresponding mutation. Toast + refetch on success.

Tests: render `/join/:token` anonymous → assert sign-in link present. Signed-in → click Join, assert mutation + navigation. Settings dialog: edit + submit, assert mutation called with right vars.

Commit: `feat(queuetip-frontend): join via invite + edit settings + final polish`.

---

## Self-Review

**Spec coverage** (against Phase 1 spec + Phase 2A spec + the MVP+polish scope you picked):
- Magic-link sign-up + sign-in: Task 3 ✅
- My playlists list + create: Task 4 ✅
- Route guards: Task 5 ✅
- Playlist view (members, contributions, voting): Task 6 ✅
- Contribute (search + paste link + dedup): Task 7 ✅
- Bulk import + progress: Task 8 ✅
- Export create + snapshot page + download: Task 9 ✅
- Join via invite + edit settings + kick/promote/leave/delete polish: Task 10 ✅

**Deferred to later phases:**
- Real-time updates (GraphQL subscriptions) — Phase 2+ per program spec.
- OAuth sign-in (Spotify, Google) — Phase 3 bundle with Spotify export.
- Sharing snapshots publicly (anonymous m3u download with a per-snapshot token) — not in spec.

**Known frontend-specific risks:**
- shadcn/ui CLI may behave differently in fresh-Vite-in-existing-repo layouts — Task 1 Step 4 fallback is to vendor the components manually from shadcn-ui docs.
- TanStack Router file-based routing requires the Vite plugin and a `routeTree.gen.ts` workflow that's a bit fiddly — the implementer for Task 1 must verify the dev server renders the home route before moving on.
- The `ExportSnapshotType.from_model` GraphQL type may need a small extension (add `playlist: PlaylistType`) — Task 9 should do this minimal backend tweak if needed.
