# UI Polish & Mobile Responsiveness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve TuneStash UI with tab persistence, better stat cards, cached stats, home page redesign, mobile responsiveness, and visual polish.

**Architecture:** Backend adds a CachedStat model with periodic refresh. Frontend updates route search params for tab persistence, restyled dashboard cards, redesigned home page reading from cached stats, hamburger nav for mobile, and a shared mobile card layout component for tables.

**Tech Stack:** Django/Strawberry GraphQL (backend), React/TanStack Router/Tailwind (frontend), Celery Beat (periodic refresh)

---

## File Structure

### Backend (create)
- `api/library_manager/migrations/XXXX_add_cached_stat.py` — migration
- `api/src/services/cached_stat.py` — service with refresh logic
- `api/src/graphql_types/cached_stat.py` — GraphQL types

### Backend (modify)
- `api/library_manager/models.py` — add CachedStat model
- `api/library_manager/tasks/periodic.py` — add refresh_cached_stats task
- `api/library_manager/tasks/__init__.py` — re-export new task
- `api/celery_beat_schedule.py` — register periodic task
- `api/src/schema/query.py` — add cachedStats query
- `api/src/graphql_types/__init__.py` — export new type

### Frontend (create)
- `frontend/src/queries/cached-stats.graphql` — GraphQL query
- `frontend/src/components/ui/MobileCardList.tsx` — shared mobile card component

### Frontend (modify)
- `frontend/src/routes/tasks.tsx` — tab persistence via search params
- `frontend/src/routes/artists.tsx` — tab persistence via search params
- `frontend/src/routes/playlists.tsx` — tab persistence via search params
- `frontend/src/routes/dashboard.tsx` — restyle stat cards
- `frontend/src/routes/index.tsx` — home page redesign
- `frontend/src/components/Navbar.tsx` — hamburger menu for mobile
- Various table routes — mobile card layout, hover states, empty states

---

### Task 1: CachedStat Model & Migration

**Files:**
- Modify: `api/library_manager/models.py`
- Create: migration via `makemigrations`

- [ ] **Step 1: Add CachedStat model to models.py**

Add at the end of `api/library_manager/models.py`:

```python
class CachedStat(models.Model):
    """Pre-computed statistics for fast dashboard/home page reads."""

    key = models.CharField(max_length=100, unique=True, db_index=True)
    display_name = models.CharField(max_length=200)
    value = models.JSONField()
    category = models.CharField(max_length=50, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cached_stats"

    def __str__(self) -> str:
        return f"{self.key}: {self.value}"
```

- [ ] **Step 2: Create migration**

Run: `docker compose exec web python manage.py makemigrations library_manager`
Expected: new migration file created

- [ ] **Step 3: Apply migration**

Run: `docker compose exec web python manage.py migrate`
Expected: migration applied successfully

- [ ] **Step 4: Commit**

```bash
git add api/library_manager/models.py api/library_manager/migrations/
git commit -m "Add CachedStat model for pre-computed dashboard stats"
```

---

### Task 2: CachedStat Service & Refresh Logic

**Files:**
- Create: `api/src/services/cached_stat.py`

- [ ] **Step 1: Create the CachedStat service**

Write `api/src/services/cached_stat.py`:

```python
"""Service for managing cached statistics."""

import logging
from typing import Any

from django.db.models import Count, F, Q
from django.utils import timezone

from library_manager.models import (
    Album,
    Artist,
    CachedStat,
    Song,
    TaskHistory,
    TrackedPlaylist,
)

logger = logging.getLogger(__name__)

# Stat definitions: key -> (display_name, category, compute_function_name)
# "fast" stats run every 15 min, "expensive" every 3 hours
FAST_STATS = {
    "tracked_artists": ("Tracked Artists", "library"),
    "total_songs": ("Total Songs", "library"),
    "downloaded_songs": ("Downloaded Songs", "library"),
    "total_playlists": ("Synced Playlists", "library"),
    "failed_songs": ("Failed Downloads", "downloads"),
    "active_tasks": ("Active Tasks", "tasks"),
}

EXPENSIVE_STATS = {
    "total_albums": ("Total Albums", "library"),
    "downloaded_albums": ("Complete Albums", "library"),
    "partial_albums": ("Partial Albums", "library"),
    "missing_albums": ("Missing Albums", "library"),
    "song_completion_pct": ("Song Completion %", "library"),
    "album_completion_pct": ("Album Completion %", "library"),
}


def _compute_stat(key: str) -> Any:
    """Compute a single stat value by key."""
    if key == "tracked_artists":
        return Artist.objects.filter(tracked=True).count()
    elif key == "total_songs":
        return Song.objects.count()
    elif key == "downloaded_songs":
        return Song.objects.filter(downloaded=True).count()
    elif key == "total_playlists":
        return TrackedPlaylist.objects.count()
    elif key == "failed_songs":
        return Song.objects.filter(
            downloaded=False, failed_count__gt=0
        ).count()
    elif key == "active_tasks":
        return TaskHistory.objects.filter(status="IN_PROGRESS").count()
    elif key == "total_albums":
        return Album.objects.count()
    elif key == "downloaded_albums":
        return Album.objects.annotate(
            dl=Count("songs", filter=Q(songs__downloaded=True)),
            total=Count("songs"),
        ).filter(dl=F("total"), total__gt=0).count()
    elif key == "partial_albums":
        return Album.objects.annotate(
            dl=Count("songs", filter=Q(songs__downloaded=True)),
            total=Count("songs"),
        ).filter(dl__gt=0, total__gt=0).exclude(dl=F("total")).count()
    elif key == "missing_albums":
        return Album.objects.annotate(
            dl=Count("songs", filter=Q(songs__downloaded=True)),
            total=Count("songs"),
        ).filter(dl=0, total__gt=0).count()
    elif key == "song_completion_pct":
        total = Song.objects.count()
        if total == 0:
            return 0.0
        downloaded = Song.objects.filter(downloaded=True).count()
        return round(downloaded / total * 100, 1)
    elif key == "album_completion_pct":
        total = Album.objects.filter(songs__isnull=False).distinct().count()
        if total == 0:
            return 0.0
        complete = Album.objects.annotate(
            dl=Count("songs", filter=Q(songs__downloaded=True)),
            total=Count("songs"),
        ).filter(dl=F("total"), total__gt=0).count()
        return round(complete / total * 100, 1)
    else:
        logger.warning("Unknown stat key: %s", key)
        return 0


def refresh_fast_stats() -> int:
    """Refresh all fast stats. Returns count of stats updated."""
    updated = 0
    for key, (display_name, category) in FAST_STATS.items():
        try:
            value = _compute_stat(key)
            CachedStat.objects.update_or_create(
                key=key,
                defaults={
                    "display_name": display_name,
                    "value": value,
                    "category": category,
                },
            )
            updated += 1
        except Exception:
            logger.exception("Failed to compute stat: %s", key)
    return updated


def refresh_expensive_stats() -> int:
    """Refresh all expensive stats. Returns count of stats updated."""
    updated = 0
    for key, (display_name, category) in EXPENSIVE_STATS.items():
        try:
            value = _compute_stat(key)
            CachedStat.objects.update_or_create(
                key=key,
                defaults={
                    "display_name": display_name,
                    "value": value,
                    "category": category,
                },
            )
            updated += 1
        except Exception:
            logger.exception("Failed to compute stat: %s", key)
    return updated


def get_cached_stats(category: str | None = None) -> list[CachedStat]:
    """Get cached stats, optionally filtered by category."""
    qs = CachedStat.objects.all()
    if category:
        qs = qs.filter(category=category)
    return list(qs.order_by("key"))
```

- [ ] **Step 2: Verify it compiles**

Run: `python3 -m py_compile api/src/services/cached_stat.py`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add api/src/services/cached_stat.py
git commit -m "Add CachedStat service with fast/expensive refresh tiers"
```

---

### Task 3: CachedStat Periodic Task & Beat Schedule

**Files:**
- Modify: `api/library_manager/tasks/periodic.py`
- Modify: `api/library_manager/tasks/__init__.py`
- Modify: `api/celery_beat_schedule.py`

- [ ] **Step 1: Add refresh_cached_stats task to periodic.py**

Add at the end of `api/library_manager/tasks/periodic.py`:

```python
@celery_app.task(bind=True, name="library_manager.tasks.refresh_cached_stats")
def refresh_cached_stats(self: Any) -> None:
    """Refresh cached statistics. Fast stats every run, expensive stats every 3 hours."""
    from datetime import timedelta

    from library_manager.models import CachedStat
    from src.services.cached_stat import (
        EXPENSIVE_STATS,
        refresh_expensive_stats,
        refresh_fast_stats,
    )

    fast_count = refresh_fast_stats()
    logger.info("Refreshed %d fast stats", fast_count)

    # Check if expensive stats need refresh (older than 3 hours)
    needs_expensive = False
    oldest_expensive = CachedStat.objects.filter(
        key__in=EXPENSIVE_STATS.keys()
    ).order_by("updated_at").first()

    if oldest_expensive is None:
        needs_expensive = True
    elif oldest_expensive.updated_at < timezone.now() - timedelta(hours=3):
        needs_expensive = True

    if needs_expensive:
        expensive_count = refresh_expensive_stats()
        logger.info("Refreshed %d expensive stats", expensive_count)
```

- [ ] **Step 2: Re-export from tasks/__init__.py**

Add to the imports in `api/library_manager/tasks/__init__.py`:

```python
from .periodic import refresh_cached_stats
```

And add `"refresh_cached_stats"` to the `__all__` list if one exists.

- [ ] **Step 3: Register in celery beat schedule**

Add to `CELERY_BEAT_SCHEDULE` in `api/celery_beat_schedule.py`:

```python
"refresh-cached-stats": {
    "task": "library_manager.tasks.refresh_cached_stats",
    "schedule": crontab(minute="*/15"),
    "options": {"priority": TaskPriority.MAINTENANCE},
},
```

- [ ] **Step 4: Commit**

```bash
git add api/library_manager/tasks/periodic.py api/library_manager/tasks/__init__.py api/celery_beat_schedule.py
git commit -m "Add periodic task to refresh cached stats every 15 min"
```

---

### Task 4: CachedStat GraphQL Query

**Files:**
- Create: `api/src/graphql_types/cached_stat.py`
- Modify: `api/src/schema/query.py`
- Create: `frontend/src/queries/cached-stats.graphql`

- [ ] **Step 1: Create GraphQL type**

Write `api/src/graphql_types/cached_stat.py`:

```python
"""GraphQL types for cached statistics."""

from datetime import datetime

import strawberry


@strawberry.type
class CachedStatType:
    key: str
    display_name: str
    value: strawberry.scalars.JSON
    category: str
    updated_at: datetime
```

- [ ] **Step 2: Add query resolver to query.py**

In `api/src/schema/query.py`, add import:

```python
from src.graphql_types.cached_stat import CachedStatType
```

Add resolver to the Query class:

```python
@strawberry.field
def cached_stats(
    self, category: Optional[str] = None
) -> list[CachedStatType]:
    from src.services.cached_stat import get_cached_stats

    stats = get_cached_stats(category)
    return [
        CachedStatType(
            key=s.key,
            display_name=s.display_name,
            value=s.value,
            category=s.category,
            updated_at=s.updated_at,
        )
        for s in stats
    ]
```

- [ ] **Step 3: Create frontend GraphQL query**

Write `frontend/src/queries/cached-stats.graphql`:

```graphql
query GetCachedStats($category: String) {
  cachedStats(category: $category) {
    key
    displayName
    value
    category
    updatedAt
  }
}
```

- [ ] **Step 4: Export schema and generate types**

Run: `make graphql-schema-fetch` (if dev containers running) or manually update `schema.graphql` and run `make graphql-generate`

- [ ] **Step 5: Seed initial stats**

Run via shell_plus: `from src.services.cached_stat import refresh_fast_stats, refresh_expensive_stats; refresh_fast_stats(); refresh_expensive_stats()`

- [ ] **Step 6: Commit**

```bash
git add api/src/graphql_types/cached_stat.py api/src/schema/query.py frontend/src/queries/cached-stats.graphql frontend/src/types/generated/
git commit -m "Add cachedStats GraphQL query with frontend types"
```

---

### Task 5: Tab Persistence via URL Search Params

**Files:**
- Modify: `frontend/src/routes/tasks.tsx`
- Modify: `frontend/src/routes/artists.tsx`
- Modify: `frontend/src/routes/playlists.tsx`

Reference pattern from `frontend/src/routes/albums.tsx` which already uses `validateSearch`.

- [ ] **Step 1: Update tasks.tsx**

Replace the `useState` for activeTab with search params. Change the route export:

```typescript
export const Route = createFileRoute('/tasks')({
  component: Tasks,
  validateSearch: (search: Record<string, unknown>) => ({
    tab: (search.tab as string) || 'active',
  }),
});
```

Inside the `Tasks` component, replace:
```typescript
const [activeTab, setActiveTab] = useState<TasksTab>('active');
```
with:
```typescript
const { tab: activeTab } = Route.useSearch();
const navigate = Route.useNavigate();
const setActiveTab = (tab: string) => navigate({ search: { tab } });
```

Update the `<Tabs>` onChange to use the new `setActiveTab`.

- [ ] **Step 2: Update artists.tsx**

Same pattern — replace `useState<ArtistTab>('library')` with search param. Route export:

```typescript
export const Route = createFileRoute('/artists')({
  component: Artists,
  validateSearch: (search: Record<string, unknown>) => ({
    tab: (search.tab as string) || 'library',
  }),
});
```

Replace useState with `Route.useSearch()` + `Route.useNavigate()`.

- [ ] **Step 3: Update playlists.tsx**

Same pattern — replace `useState<PlaylistTab>('synced')` with search param. Route export:

```typescript
export const Route = createFileRoute('/playlists')({
  component: Playlists,
  validateSearch: (search: Record<string, unknown>) => ({
    tab: (search.tab as string) || 'synced',
  }),
});
```

Replace useState with `Route.useSearch()` + `Route.useNavigate()`.

- [ ] **Step 4: Test in browser**

Navigate to `/tasks?tab=history`, refresh — should stay on History tab.
Navigate away and back — should preserve tab.
Click tabs — URL should update.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/tasks.tsx frontend/src/routes/artists.tsx frontend/src/routes/playlists.tsx
git commit -m "Persist tab selection in URL search params across refresh/navigation"
```

---

### Task 6: Dashboard Stat Cards Restyle

**Files:**
- Modify: `frontend/src/routes/dashboard.tsx`

- [ ] **Step 1: Update colorClasses to use neutral card backgrounds**

Replace the `colorClasses` object (around line 74) so all colors use the same neutral card background:

```typescript
const colorClasses = {
  gray: 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700',
  green: 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700',
  blue: 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700',
  red: 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700',
  yellow: 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700',
  purple: 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700',
};
```

Keep the `textColorClasses` object as-is — it already has appropriate colors for the stat numbers.

- [ ] **Step 2: Verify in browser**

Check dashboard in both light and dark mode. Cards should now be neutral with colored numbers only.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/dashboard.tsx
git commit -m "Restyle dashboard stat cards to neutral backgrounds with colored text"
```

---

### Task 7: Home Page Redesign

**Files:**
- Modify: `frontend/src/routes/index.tsx`

- [ ] **Step 1: Remove "Get started" section**

Delete the "Get started" card (the section with the numbered list around lines 484-493).

- [ ] **Step 2: Replace navigation cards with stat-driven cards**

Replace the 4 plain-text link cards with cards that show data from `GetCachedStats`. Import and use the generated query:

```typescript
import { useQuery } from '@apollo/client';
import { GetCachedStatsDocument } from '../types/generated/graphql';
```

Query cached stats:
```typescript
const { data: statsData } = useQuery(GetCachedStatsDocument, {
  variables: { category: 'library' },
});
```

Helper to read a stat:
```typescript
const getStat = (key: string) => {
  const stat = statsData?.cachedStats?.find(s => s.key === key);
  return stat?.value ?? '...';
};
```

Replace each card to show: the stat value prominently, the label, and link to the page. For example the Artists card becomes:
```
[1,645]
Tracked Artists
→ /artists
```

Use `grid-cols-2 lg:grid-cols-4` for the grid.

- [ ] **Step 3: Make System Status collapsible**

Wrap the System Status content in a collapsible section. Default to collapsed. Show a single summary line: count green checks vs warnings. Use `useState` for the expand toggle (this is local UI state, not worth URL persistence).

- [ ] **Step 4: Test in browser**

Verify home page loads fast (stats from cache), cards show real numbers, system status collapses/expands.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/index.tsx
git commit -m "Redesign home page with stat cards and collapsible system status"
```

---

### Task 8: Mobile Navbar (Hamburger Menu)

**Files:**
- Modify: `frontend/src/components/Navbar.tsx`

- [ ] **Step 1: Add hamburger menu state and button**

Add state for mobile menu:
```typescript
const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
```

Add hamburger button visible only on mobile (`md:hidden`). Hide the nav links on mobile (`hidden md:flex`).

- [ ] **Step 2: Add mobile menu overlay**

When `mobileMenuOpen` is true, render a slide-down panel below the navbar with the nav links stacked vertically. Close on link click or outside click.

```tsx
{mobileMenuOpen && (
  <div className="md:hidden border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-2">
    {navLinks.map(link => (
      <Link
        key={link.to}
        to={link.to}
        className="block px-3 py-2 rounded-md text-sm font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
        activeProps={{ className: '...' }}
        onClick={() => setMobileMenuOpen(false)}
      >
        {link.label}
      </Link>
    ))}
  </div>
)}
```

- [ ] **Step 3: Adjust control buttons for mobile**

Keep theme toggle, search icon, and download button visible on mobile but more compact. Hide the "Search" text and keyboard shortcut on small screens (already done with `hidden sm:inline`).

- [ ] **Step 4: Test at 390px width**

Verify hamburger appears, menu opens/closes, links navigate and close menu.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Navbar.tsx
git commit -m "Add hamburger menu for mobile navigation"
```

---

### Task 9: Mobile Card Layout Component

**Files:**
- Create: `frontend/src/components/ui/MobileCardList.tsx`

- [ ] **Step 1: Create MobileCardList component**

```tsx
import { Link } from '@tanstack/react-router';

interface MobileCardField {
  label: string;
  render: (item: any) => React.ReactNode;
}

interface MobileCardListProps {
  items: any[];
  fields: MobileCardField[];
  keyField: string;
  linkTo?: (item: any) => string;
}

export const MobileCardList = ({ items, fields, keyField, linkTo }: MobileCardListProps) => {
  return (
    <div className="md:hidden space-y-3">
      {items.map(item => {
        const content = (
          <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 space-y-2">
            {fields.map(field => (
              <div key={field.label} className="flex justify-between items-center">
                <span className="text-xs text-slate-500 dark:text-slate-400 uppercase">
                  {field.label}
                </span>
                <span className="text-sm text-slate-900 dark:text-slate-100">
                  {field.render(item)}
                </span>
              </div>
            ))}
          </div>
        );
        if (linkTo) {
          return (
            <Link key={item[keyField]} to={linkTo(item)} className="block">
              {content}
            </Link>
          );
        }
        return <div key={item[keyField]}>{content}</div>;
      })}
    </div>
  );
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ui/MobileCardList.tsx
git commit -m "Add shared MobileCardList component for responsive tables"
```

---

### Task 10: Apply Mobile Cards to Table Pages

**Files:**
- Modify: `frontend/src/routes/artists.tsx`
- Modify: `frontend/src/routes/playlists.tsx`
- Modify: `frontend/src/routes/songs.tsx`
- Modify: `frontend/src/routes/albums.tsx`
- Modify: `frontend/src/routes/tasks.tsx`

- [ ] **Step 1: Artists page**

Import `MobileCardList`. Add `hidden md:block` to the existing table wrapper. Below it, add:

```tsx
<MobileCardList
  items={artists}
  keyField="id"
  fields={[
    { label: 'Artist', render: a => a.name },
    { label: 'Status', render: a => a.isTracked ? 'Tracked' : 'Untracked' },
    { label: 'Last Synced', render: a => a.lastSyncedAt || 'Never' },
  ]}
  linkTo={a => `/artists/${a.id}`}
/>
```

- [ ] **Step 2: Apply same pattern to playlists, songs, albums, tasks**

Each page: hide table on mobile with `hidden md:block`, add `MobileCardList` below with page-specific fields. Choose 3-4 most important fields per page for mobile.

- [ ] **Step 3: Also add `flex-col sm:flex-row` to action button containers**

On pages where action buttons stack awkwardly on mobile (Artists, Playlists), wrap them in `flex flex-col sm:flex-row gap-2`.

- [ ] **Step 4: Test at 390px width across all pages**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/
git commit -m "Add mobile card layouts to all table pages"
```

---

### Task 11: Visual Polish (Hover, Empty States, Headers)

**Files:**
- Various route/component files

- [ ] **Step 1: Add table row hover states**

In every table that renders `<tr>` elements, add: `hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors`

This applies to: artists table, albums table, songs table, playlists table, tasks history table.

- [ ] **Step 2: Clean up empty states**

Find all instances of emoji-centered empty states (clipboard, checkmark, etc.) and replace with clean text-only versions. Remove the emoji, keep the message text, style as muted centered text.

- [ ] **Step 3: Tighten page header spacing**

Reduce `mb-6` or `mb-8` on page header sections to `mb-4`. Check: tasks, artists, albums, songs, playlists, dashboard, settings.

- [ ] **Step 4: Playlist pills — check in with user**

Show the user current pills vs proposed muted badges before changing. Use the visual companion if available, or screenshot comparison.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "Polish: table hover states, clean empty states, tighter header spacing"
```

---

### Task 12: Lint, Test, and Final Verification

- [ ] **Step 1: Fix lint**

Run: `make fix-lint`

- [ ] **Step 2: Run all linters**

Run: `make lint-all`
Expected: 0 failures

- [ ] **Step 3: Run API tests**

Run: `make test-api-docker`
Expected: all pass

- [ ] **Step 4: Run frontend tests**

Run: `make test-frontend-docker`
Expected: all pass

- [ ] **Step 5: Visual verification with Playwright**

Load each page at desktop (1280px) and mobile (390px) width. Take screenshots. Verify:
- Home page: stat cards show data, system status collapsed by default
- Dashboard: neutral card backgrounds, colored text
- Tasks/Artists/Playlists: tabs persist in URL on refresh
- Mobile: hamburger menu works, card layouts readable
- All pages: row hover on tables, clean empty states

- [ ] **Step 6: Commit and push**

```bash
git add -A
git commit -m "UI polish: lint fixes and final adjustments"
git push
```
