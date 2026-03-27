# TuneStash - TODO

## Features and Enhancements
- [ ] **Tracked Playlists improvements** - Improve update experience (not URL-locked)
- [ ] **Configurable periodic task intervals** - Allow customization of sync intervals
- [ ] **Add artists directly** - Add by artist name (not just URL)
- [ ] **Frontend UX improvements** - Loading skeletons for initial loads (optional)

## Frontend (Rejected Ideas - Do Not Implement)
- **Retries for mutations** - Most mutations either succeed or indicate real problems (DB/auth issues). Task operations enqueue jobs, don't need retries.
- **Optimistic updates** - Library management requires accuracy over perceived speed. False states confuse users about tracking/sync status.

## Notes
- Priority should be given to items affecting active development workflows
- Docker-first development approach is preferred for consistency
