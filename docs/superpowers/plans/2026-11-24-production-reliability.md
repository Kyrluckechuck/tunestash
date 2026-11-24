# Production Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Track the checkboxes below.

**Goal:** Restore trustworthy download matching, failure state, and retained diagnostics without automatically downloading incorrect recordings.

**Architecture:** Preserve existing provider and Django service boundaries. Repair logging coverage and use a maintained process-safe rotating handler with gzip, age expiry, and shared-directory budget enforcement. Keep audited legacy flag repair separate from downloads.

**Tech Stack:** Python 3.13, Django, Celery, pytest, Docker Compose.

**Spec:** User-approved consolidated proposal in this session: YouTube update done; repair legacy flags; guard artist/version matching; classify failures honestly; persist provider diagnostics; fix DB-backed startup validation; retain memory limits; enable Valkey host overcommit with verification.

## Global Constraints

- Do not touch unrelated metadata_detection.py or test_metadata_update_migration.py changes.
- No automatic retry flood, no music file modifications during data repair.
- Logs: 30-day target, gzip, daily or size rotation, 1 GiB shared upper ceiling, not target usage.
- Keep secrets out of logs and diagnostics.
- Use Docker/local venv tests; collect red/green evidence per chunk.
- Commit only owned files, unsigned per-command if needed; batch pushes after checks.
- No worker memory limit increase.

## Review Focus

- Similar titles by unrelated artists must fail even with exact title matches.
- Featured artists and legitimate accent/punctuation variants must remain matchable.
- Zero downloads from provider/network errors must not imply catalog unavailability.
- Concurrent processes, multiple daily rotations, and old open file descriptors must not lose logs.
- Legacy repair must be dry-run by default, narrowly filtered, idempotent, and never queue tasks.

## Task 1: Matching safeguards

Files: api/downloader/track_matcher.py, api/downloader/providers/youtube.py; corresponding unit tests.

- [ ] Add regressions for CHEZ/Avoidant versus Detz/Avoidance; Jon Pumper/Change versus jame/Change; legitimate collaborations; mixed/extended/piano versions.
- [ ] Run focused tests red.
- [ ] Implement independent artist compatibility and version protection without indiscriminately raising the aggregate threshold.
- [ ] Run focused tests green; inspect source callers and document changes.

## Task 2: Honest failures and provider diagnostics

Files: api/downloader/providers/fallback.py, api/library_manager/tasks/download.py, relevant unit tests.

- [ ] Add regressions for zero-download temporary failures and retained per-provider outcomes.
- [ ] Run red; add additive backward-compatible provider outcome data to DownloadChainResult.
- [ ] Log bounded per-provider failure context with song/provider identifiers; retain useful task-history failure summaries without credentials.
- [ ] Classify zero-download provider failures as temporary, not ALL_TRACKS_UNAVAILABLE; preserve actual metadata/catalog verdicts.
- [ ] Run focused tests green.

## Task 3: Startup settings consistency

Files: api/src/main.py, api/tests/unit/test_main.py.

- [ ] Add DB-backed token present/missing regressions with runtime config mocked.
- [ ] Run red; read Config().po_token instead of YAML-only reference; update guidance.
- [ ] Run green, including configuration-unavailable behavior.

## Task 4: Complete bounded logging

Files: api/settings.py, api/celery_app.py, api/lib/logging_handlers.py (new), requirements.txt if needed; new unit tests.

- [ ] Evaluate maintained concurrent rotating handler against Python 3.13 support, time plus size, gzip, locking and fork behavior.
- [ ] Add red tests for root provider file coverage after Celery logging initialization.
- [ ] Prevent Celery root handler hijacking while retaining console and task logging.
- [ ] Add process-safe rotation with unique archives, 30-day age expiry, shared budget including active logs; prefer small active chunks (e.g. 5 MiB).
- [ ] Test concurrent writers, repeated same-day rollover, gzip readability, age expiry, shared budget, safe file matching and no secret emission.
- [ ] Run green and isolated Docker smoke; retain Docker stdout as a bounded independent operational stream.

## Task 5: Controlled repair and host setting

Files: new management command and integration tests; local production access instructions if appropriate.

- [ ] Add dry-run command for only unavailable=True, failure_reason=temporary, downloaded=False records whose last_failed_at predates June 20 2026 UTC.
- [ ] Test default no-op, explicit apply, unaffected rows, idempotency and no queued downloads.
- [ ] Implement flag-only repair with counts; validate full batch before production use.
- [ ] Confirm production host accepts approved vm.overcommit_memory=1 change and persistent configuration; do not bypass sudo restrictions.
- [ ] Apply approved narrow repair only after review, record counts and verify flags/history preservation.
- [ ] Run relevant API CI-equivalent checks, fresh independent review, commit per feature and push as one validated batch.

## Execution

The user approved proceeding and requested applicable subagent work. Independent tasks may run concurrently with exclusive file ownership; the orchestrator owns logging, repair integration, production operations and final checks. No deploy is implied by local implementation until verification is complete.
