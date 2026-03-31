# UI Polish & Mobile Responsiveness

## Overview

Three tiers of improvements: functional UX fixes, visual identity, and polish. Plus mobile responsiveness as a cross-cutting concern.

## 1. Tab Persistence via URL Search Params

**Problem:** Tasks, Artists, and Playlists pages use `useState` for tab selection — resets on refresh or navigation.

**Solution:** Use TanStack Router search params. Each route defines `validateSearch` to read `?tab=` with a default. Replace `useState`/`setActiveTab` with `Route.useSearch()` and `navigate({ search: { tab } })`.

**Files:** `routes/tasks.tsx`, `routes/artists.tsx`, `routes/playlists.tsx`

## 2. Dashboard Stat Cards

**Problem:** Song/Album breakdown cards use harsh full-saturation backgrounds (green-900, red-900, blue-900, yellow-100) that clash with the slate palette.

**Solution:** Replace colored backgrounds with standard card style (`bg-white dark:bg-slate-800`). Move color to the stat number text only:
- Downloaded/Complete: `text-green-600 dark:text-green-400`
- Missing: `text-amber-600 dark:text-amber-400`
- Failed: `text-red-600 dark:text-red-400`
- Total/Unavailable: neutral slate

**Files:** `routes/dashboard.tsx`

## 3. CachedStat System

**Problem:** Some library stats (especially album counts with joins) take ~1s on prod. Home page and dashboard shouldn't wait for expensive queries.

**Solution:** New `CachedStat` model stores pre-computed stats. A periodic Celery task refreshes them on two tiers:
- **Fast (every 15 min):** tracked_artists, downloaded_songs, total_songs, playlist_count, active_tasks — simple COUNT queries
- **Expensive (every 3 hours):** downloaded_albums, completion_percentage, albums_complete, albums_partial — queries with joins/distinct

Model:
```
CachedStat:
  key: CharField(unique, indexed)
  display_name: CharField
  value: JSONField  # Stores typed values: int for counts, float for percentages, string for labels
  category: CharField ("library", "downloads", "tasks")
  updated_at: DateTimeField(auto_now)
```

GraphQL query: `cachedStats(category: String) -> [CachedStatType]`

Home page and dashboard both read from this. Dashboard retains a "Refresh" button that forces live recalculation.

**Files:**
- `api/library_manager/models.py` — CachedStat model
- `api/library_manager/migrations/` — new migration
- `api/library_manager/tasks/periodic.py` — refresh_cached_stats task
- `api/celery_beat_schedule.py` — register periodic task
- `api/src/graphql_types/` — CachedStatType
- `api/src/schema/query.py` — cachedStats query
- `api/src/services/` — CachedStatService

## 4. Home Page Redesign

**Remove:** "Get started" section entirely.

**Quick stats row:** Replace 4 plain-text link cards with stat-driven cards sourced from CachedStat:
- Artists: "{count} tracked"
- Songs: "{count} downloaded"
- Playlists: "{count} synced"
- Downloads: "{percentage}% complete" (or similar)

Each card links to its respective page.

**System Status:** Collapse into a compact summary by default. Single-line status ("All systems OK" or "1 issue") with expand toggle for full detail.

**Files:** `routes/index.tsx` (home page)

## 5. Table & Empty State Polish

**Row hover:** Add `hover:bg-slate-50 dark:hover:bg-slate-800/50` to all table rows.

**Empty states:** Replace emoji-centered patterns (clipboard, checkmark) with clean text-only empty states. No emoji.

**Playlist pills:** The Yes/No pills with checkmark/X are visually loud. Explore replacing with muted text badges. **Check in with user** before finalizing this visual — show options during implementation.

**Files:** Various table components across routes

## 6. Typography & Spacing

**Page headers:** Reduce vertical margin below h1 + subtitle blocks so content is visible sooner.

**Files:** Various route files, possibly extract shared page header component

## 7. Mobile Responsiveness

**Navbar:**
- Below `md` (768px): collapse nav links into hamburger menu
- Keep visible on mobile: logo, theme toggle, search icon, download button
- Hamburger opens slide-down overlay with nav links
- Implementation: `hidden md:flex` on links, `md:hidden` on hamburger

**Tables — mobile card layout:**
- Below `md`: render key fields as stacked cards instead of table rows
- Shared `<MobileCardList>` component with column config per page (one component, not six)
- Desktop shows `hidden md:table`, mobile shows `md:hidden` card list
- Each page defines which fields appear on mobile cards

**Action buttons:**
- Stack vertically on small screens: `flex-col sm:flex-row`

**Pages affected:** Navbar, Artists, Albums, Songs, Playlists, Tasks, Settings, Home, Dashboard

## Build Sequence

1. **CachedStat backend** — model, migration, periodic task, GraphQL query
2. **Tab persistence** — 3 route files, URL search params
3. **Dashboard stat cards** — restyle cards
4. **Home page redesign** — stat cards from CachedStat, collapsible status, remove Get Started
5. **Mobile navbar** — hamburger menu
6. **Mobile card layouts** — shared MobileCardList component, apply to all tables
7. **Polish** — table hover, empty states, playlist pills (check in with user), header spacing
8. **Lint + test**
