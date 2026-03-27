# TuneStash

A music library sync tool that tracks your artists and playlists via Deezer metadata, then downloads the music locally via YouTube Music with fallback providers (Tidal, Qobuz, Monochrome).

## Features

- **Artist tracking** -- Mark artists as tracked to auto-download new releases and missing albums
  - Automatically checks for and queues missing albums (hourly)
  - Fetch and browse metadata for all albums in a tracked artist's discography
  - Mark unwanted albums as non-wanted (useful for artists with large backlogs where you only want new releases)
- **Playlist syncing** -- Track playlists to automatically download new songs as they're added
  - Automatically refreshes and syncs tracked playlists (every 8 hours)
  - Optionally auto-track new artists discovered from playlists (e.g., a "favourites" playlist)
- **Download management** -- Download playlists, albums, or individual tracks on demand
  - Multiple download providers: YouTube Music (primary, via yt-dlp), Tidal, Qobuz, and Monochrome (Tidal CDN FLAC)
  - Configurable provider order and quality settings via the in-app Settings page
- **Deezer metadata** -- Artist, album, and track metadata sourced from Deezer
- **New releases scanner** -- Detects new releases from tracked artists via Deezer editorial data
- **Synced lyrics** -- Downloads synced lyrics from LRClib as .lrc sidecar files alongside audio
- **External music lists** -- Import and track lists from Last.fm and ListenBrainz
- **M3U playlist export** -- Export playlists as M3U files for use with Navidrome and other media servers
- **Navidrome integration** -- Triggers library rescans after downloads complete
- **Task queue** -- Background task system with Celery, backed by PostgreSQL
  - Downloads continue after restarts (pending tasks resume automatically; interrupted tasks can be retried)
  - Task progress visible in the UI
- **Notifications** -- Configurable alerts via [Apprise](https://github.com/caronc/apprise) (80+ services) for credential expiry and error rates
- **In-app settings** -- All configuration managed through the Settings page (DB-backed with sensible defaults)
- **Dark mode** -- System/light/dark theme toggle

## Notes
While this has a lot of opportunity to improve, it's reached a "stable" state for my personal usage. Therefore I will fix critical issues as I encounter them, but will not actively be working on additional features except when inspiration hits me, or there are specific community requests.

If there is enough desire from folks, I am happy to put more time in, and of course always welcome Pull Requests!

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](docs/CONTRIBUTING.md) for development setup instructions and guidelines.

## Security & Authentication

**Important Security Notice**: This application **does not include built-in authentication**. It is designed for personal use in trusted environments.

### If You Need Authentication

If you plan to expose this application externally or want to add authentication, consider:

- **Reverse proxy with authentication**: Use [Traefik](https://traefik.io/) with auth middleware, [nginx](https://nginx.org/) with auth modules, or [Caddy](https://caddyserver.com/) with auth plugins
- **Authentication gateways**:
  - [Authentik](https://goauthentik.io/) - Self-hosted identity provider
  - [Authelia](https://www.authelia.com/) - Lightweight authentication and authorization server
  - [OAuth2 Proxy](https://oauth2-proxy.github.io/oauth2-proxy/) - OAuth2 and OIDC authentication proxy
- **VPN access**: Keep the application internal and access via VPN (WireGuard, OpenVPN, etc.)
- **Network-level protection**: Firewall rules, VPC isolation, or private networks only

### Security Best Practices

- **Never expose this application directly to the internet** without proper authentication
- **Use HTTPS** in production environments with proper TLS certificates
- **Keep the application updated** and monitor for security advisories
- **Limit network access** to trusted users and networks only
- **Regular backups** of your configuration and database

## Screenshots

> Note: These screenshots may be outdated and not reflect the current UI.

![Main Dashboard](https://github.com/Kyrluckechuck/tunestash/assets/7606153/6d32f8d5-fe6b-4884-a5a9-7970aaba284a)
![Example Artist Page](https://github.com/Kyrluckechuck/tunestash/assets/7606153/2dcceee2-41e4-4101-b257-2ca754017c20)



## Configuration / Usage
It's currently being designed to mostly run on Linux-based systems, however, many of the configurations should only require minor tweaks to adjust for Windows-based systems.

All settings are configurable through the in-app Settings page. On first run, sensible defaults are applied. You can optionally provide YouTube Music cookies for higher-quality downloads (see Download Providers below).

Notes:
- Secrets like `DJANGO_SECRET_KEY` should be set via environment variables in `.env`.
- Database and Celery broker settings are configured via environment variables in `.env` (see `.env.example`).

### Download Providers

TuneStash supports multiple download providers with a configurable fallback chain. By default, providers are tried in order until one succeeds.

**Provider order and quality are configured in the in-app Settings page.**

**Provider Comparison:**

| Provider | Source | Quality | Reliability | Notes |
|----------|--------|---------|-------------|-------|
| **youtube** | YouTube Music (via yt-dlp) | 128kbps (free) / 256kbps (Premium) | High | Largest catalog. Requires YTM cookies for Premium quality. |
| **tidal** | Tidal (via squid.wtf) | Up to 24-bit FLAC | Moderate | Third-party API, no setup required. |
| **qobuz** | Qobuz (via squid.wtf) | Up to 24-bit FLAC | Moderate | Third-party API, no setup required. |
| **monochrome** | Tidal CDN | Lossless FLAC | Moderate | Community instances, guaranteed lossless. |

**Provider Details:**

- **youtube** (default primary): Downloads from YouTube Music using [yt-dlp](https://github.com/yt-dlp/yt-dlp).
  - **Without** YouTube Music Premium: Limited to **128kbps AAC**
  - **With** YouTube Music Premium: Up to **256kbps AAC** (requires cookies from a Premium account)
  - Most reliable for track availability; YouTube Music has the largest catalog
  - Cookies are configured via the Settings page (path to cookies file)

- **tidal** / **qobuz**: Use third-party APIs (squid.wtf) that provide access to premium streaming catalogs.
  - **No account or credentials required** -- these APIs handle authentication
  - Support lossless (FLAC) and hi-res (24-bit FLAC) quality
  - Less reliable: third-party services may have downtime, rate limits, or be discontinued
  - Best used as fallback providers when YouTube Music fails to find a match

- **monochrome**: Uses Tidal's CDN via community-hosted [Monochrome](https://github.com/Kyrluckechuck/monochrome) instances.
  - **Guaranteed lossless FLAC** output
  - Requires a Monochrome instance URL (configured in the Settings page)
  - Good fallback for lossless quality when Tidal/Qobuz APIs are unavailable

**Quality Options:**

| Quality | YouTube | Tidal Format | Qobuz Format | Monochrome |
|---------|---------|--------------|--------------|------------|
| `high` | M4A (AAC 128/256kbps) | M4A (AAC ~320kbps) | FLAC -> M4A (AAC 256kbps) | FLAC |
| `lossless` | N/A | FLAC 16-bit | FLAC 16-bit | FLAC 16-bit |
| `hi_res` | N/A | FLAC 24-bit | FLAC 24-bit | FLAC (up to 24-bit) |

**How it works:**
- Providers are tried in order until one succeeds
- Each provider searches for a matching track (by ISRC, title/artist)
- Downloaded files are validated before saving
- If all providers fail, the track is marked as failed

**Monitoring:**
View provider success rates in the Dashboard "Fallback Provider Metrics" section (collapsed by default). Metrics are retained for 30 days.

### Notifications

TuneStash can send alerts via [Apprise](https://github.com/caronc/apprise) (80+ notification services) when:
- **YouTube cookies expire** or are about to expire (configurable warning thresholds)
- **PO token becomes invalid** (if configured)
- **Spotify OAuth fails** to refresh (if using user-authenticated mode)
- **High error rate** detected (configurable threshold)

Notification settings (URLs, cooldown, thresholds, cookie warning days, instance name) are all configured through the in-app Settings page.

See [Apprise Wiki](https://github.com/caronc/apprise/wiki#notification-services) for available notification services including Discord, Telegram, Gotify, Pushover, email, and many more.

## Running From Docker (recommended)
An example compose setup is included. Follow these steps:

1. Prepare a local config directory:
   ```bash
   mkdir -p ./config/db
   # Optionally export cookies from your browser while logged into YouTube Music
   # Save as ./config/youtube_music_cookies.txt (path is configurable in the Settings page)
   ```

2. Create an environment file from the example and set paths:
   ```bash
   cp .env.example .env
   # Edit .env and set SLM_CONFIG_DIR to the absolute path of ./config, e.g.:
   # SLM_CONFIG_DIR="${PWD}/config"
   # Optionally set MUSIC_DIR to where downloads should be stored
   ```

3. Bring up the stack:
   ```bash
   docker compose up --build -d
   ```

4. Access the app:
   - **Development**: http://localhost:3000 (Frontend dev server with HMR)
   - **Production**: http://localhost:5000 (Nginx serving frontend + API)

5. Useful commands:
   ```bash
   docker compose logs -f                # tail all services
   docker compose logs -f web            # API logs
   docker compose logs -f frontend-dev   # Frontend dev server logs (use 'frontend' in production)
   docker compose logs -f worker         # Worker logs
   docker compose down -v                # stop and remove volumes
   ```

## Running From Source (Development)

> [!WARNING]
> Local development without Docker is not actively tested and may not work out of the box. **Docker-based development via `make dev-container` is strongly recommended.** This section is provided for reference only.

### Prerequisites
1. Install Python 3.13 or higher
2. Install Node.js and Yarn
3. Optionally place your YouTube Music cookies in `/config/` as `youtube_music_cookies.txt`
   * You can export your cookies by using this Google Chrome extension on YouTube Music: https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc. Make sure to be logged in.

### Quick Start
1. **Setup dependencies:**
   ```bash
   make setup
   ```

2. **Start the development environment:**
   ```bash
   make dev
   ```

   This starts all three services:
   - **API Server** (http://localhost:5000/graphql)
   - **Frontend Server** (http://localhost:3000)
   - **Celery Worker** (background task processing)

### Development Commands

All commands can be run from the root directory. See the `Makefile` for additional targets.

**Getting Started:**
- `make setup` - Install all dependencies (API + frontend) and git hooks
- `make dev-container` - Start full Docker stack (recommended)
- `make dev` - Start all services locally (requires local PostgreSQL)

**Docker Development:**
- `make dev-container` - Start full stack in Docker (API, Frontend, Worker, Beat, PostgreSQL)
- `make dev-container-update` - Rebuild app containers without restarting Postgres
- `make dev-container-down` - Stop all Docker services
- `make dev-container-logs` - Tail logs from all services

**Testing & Quality:**
- `make test` - Run tests for both API and frontend
- `make lint-all` - Run all linters (API + frontend)
- `make fix-lint` - Auto-fix formatting issues

### Development Features

- **Async task processing** - Background tasks (downloads, syncing) are queued via Celery with PostgreSQL as the broker
- **Real-time monitoring** - Task progress visible in the UI, color-coded service logs in Docker
- **Reliable queue** - PostgreSQL-backed task queue survives restarts; pending tasks resume automatically

### Configuration

All application settings are managed through the in-app Settings page (accessible once the app is running). Settings are stored in the database with sensible defaults applied on first run.

Environment variables in `.env` (see `.env.example`) are used for infrastructure-level configuration:
- Database connection settings
- Celery broker settings
- Secrets like `DJANGO_SECRET_KEY`

**Periodic Task Management:**
- **Docker mode**: Access Django admin via shell: `docker compose exec web python manage.py shell`
- **Local mode**: Django admin at http://localhost:5000/admin/django_celery_beat/
- Alternatively, edit schedules directly in `api/celery_beat_schedule.py`

### Troubleshooting

If you encounter issues:

1. **Check service status:**
   ```bash
   docker compose ps
   ```

2. **Verify Celery worker is running:**
   - Check worker logs: `docker compose logs worker`
   - Check beat scheduler logs: `docker compose logs beat`

3. **Reset the environment:**
   ```bash
   make setup
   make dev
   ```

### Changing Spotify Credentials

If you need to switch Spotify API credentials (e.g., after hitting rate limits or switching accounts):

1. **Enable safe mode** in the Settings page (or add `spotify_safe_mode: true` to `config/settings.yaml`).

2. **Restart containers** to pick up safe mode (via your preferred method - Docker Compose, Portainer, Dockge, etc.)

3. **Clear old OAuth tokens and rate limit state** using any database tool (pgAdmin, DBeaver, psql, etc.):
   ```sql
   DELETE FROM spotify_oauth_tokens;
   DELETE FROM spotify_rate_limit_state;
   ```

   *To use psql from within the postgres container, open a terminal/shell and run:*
   ```bash
   psql -U slm_user -d tunestash
   ```

4. **Update your credentials** in `.env`:
   ```
   SPOTIPY_CLIENT_ID=your_new_client_id
   SPOTIPY_CLIENT_SECRET=your_new_client_secret
   ```

5. **Disable safe mode** in the Settings page (or remove from `config/settings.yaml`).

6. **Restart containers** and re-authenticate via the Spotify OAuth flow in the app.

## Migrating from spotify-library-manager

**Breaking Changes**: This version includes major infrastructure changes (Huey->Celery, SQLite->PostgreSQL, Docker-first development).

### Quick Migration (Docker Users)
```bash
docker compose down -v && git pull && docker compose up -d
```

### Full Migration Guide
For development setups or data preservation, see [MIGRATION_GUIDE.md](docs/MIGRATION_GUIDE.md) for detailed instructions.

### Legacy Django Migration History

If you are upgrading from the older repository layout where the Django app lived at `spotify_library_sync/library_manager` with migrations `0001`-`0020`, this branch consolidates that history into a new `library_manager` app with a fresh `0001_initial` that declares `replaces` for the legacy chain. This prevents migration history conflicts.

Recommended steps:

1. Back up your database.
2. Inspect the current migration state:
   ```bash
   # From repo root
   cd api
   python manage.py showmigrations library_manager
   ```
3. Apply migrations normally:
   ```bash
   python manage.py migrate
   ```
4. Only if you see errors about tables already existing for `library_manager` (e.g., upgrading from a DB that has tables but missing migration records), re-run with:
   ```bash
   python manage.py migrate --fake-initial
   ```

Notes:
- The new `0001_initial` includes a `replaces = [...]` list mapping all legacy migrations, so environments that had applied those will upgrade cleanly.
- Fresh installations are unaffected and will run the new migration sequence as normal.
