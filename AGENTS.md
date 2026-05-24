# AGENTS.md

Generic guidance for AI coding agents working in this repository.

## Project Summary

TuneStash is a Docker-first full-stack music library sync application.

- Backend: Django ORM with FastAPI serving a Strawberry GraphQL API
- Frontend: React, TypeScript, TanStack Router, Apollo Client, Vite, TailwindCSS
- Background work: Celery workers and Celery Beat, using PostgreSQL as broker/storage
- Database: PostgreSQL with Django migrations
- Configuration: Dynaconf settings loaded from `/config/settings.yaml` plus environment variables

## Development Environment

Use Docker Compose for normal development.

Prerequisites:
- Docker and Docker Compose
- Node.js 24 and Yarn for local frontend work
- Git

Common commands:
- `make dev-container` - start the full development stack
- `make dev-container-update` - rebuild/restart app containers while keeping Postgres running
- `make dev-container-down` - stop Docker services
- `make dev-container-logs` - tail all service logs
- `make dev-container-logs-web` - tail API logs
- `make dev-container-logs-worker` - tail worker logs
- `make dev-container-logs-frontend` - tail frontend logs

Development URLs:
- Frontend dev server: `http://localhost:3000`
- GraphQL API: `http://localhost:5000/graphql` inside the Docker network, or via frontend proxy in development

## Testing And Quality

Preferred checks:
- `make lint-all` - run all API and frontend linters in parallel
- `make lint-api` - run API linters
- `make lint-frontend` - run frontend linting
- `make test-api-docker` - run API tests in Docker
- `make test-frontend-docker` - run frontend tests in Docker
- `make test-api` - run API tests locally
- `make test-frontend` - run frontend tests locally
- `make fix-lint` - auto-fix formatting issues where possible

Local linting is often faster when dependencies are installed:
- From `api/`: `python3 -m flake8 <file>`, `python3 -m black <file>`, `python3 -m isort <file>`
- From `frontend/`: `yarn lint`, `yarn format`, `yarn test:run`

Python standards:
- Black, 88 character line length
- isort imports
- mypy strict type checks where configured
- flake8, bandit, pylint

Frontend standards:
- Strict TypeScript
- ESLint
- Prettier
- React hooks patterns

Comments should explain why code exists, not what changed. Do not leave changelog-style comments or commented-out dead code.

## GraphQL Workflow

When adding or changing frontend GraphQL operations:
1. Add or edit documents in `frontend/src/queries/*.graphql`.
2. Generate types with `make graphql-generate`.
3. Commit generated files under `frontend/src/types/generated/` with the query changes.

When backend schema changes:
1. Update the schema/resolvers under `api/src/schema/` or related GraphQL type modules.
2. Start the dev stack if needed: `make dev-container`.
3. Fetch the updated schema and regenerate types with `make graphql-schema-fetch`.
4. Commit the generated schema/types.

The committed local schema is the source of truth for fast local generation. Only fetch from a running server when backend schema changes.

## Database Changes

Use Django ORM and migrations.

Typical workflow:
1. Modify models in `api/library_manager/models.py` or the relevant app model module.
2. Create migrations in the container: `docker compose exec web python manage.py makemigrations`.
3. Apply migrations: `docker compose exec web python manage.py migrate`.
4. Update affected GraphQL types and generated frontend types.

Prefer containerized Django management commands for database work.

## Celery Tasks

Background tasks live under `api/library_manager/tasks/` and are re-exported from `api/library_manager/tasks/__init__.py`.

Always queue Celery tasks with `.delay()` or `.apply_async()`. Do not call task functions directly from application code.

Common places to inspect for task calls:
- `api/library_manager/helpers.py`
- `api/src/schema/mutation.py`
- Service modules under `api/src/services/`

For one-off maintenance tasks:
1. Add the Celery task under `api/library_manager/tasks/`.
2. Re-export it from `tasks/__init__.py`.
3. Register it in `api/src/services/one_off_task.py`.

Periodic schedules are defined in `api/celery_beat_schedule.py` and stored by `DatabaseScheduler` in PostgreSQL.

## Async And Sync Boundaries

This codebase mixes async FastAPI/Strawberry GraphQL code with sync Django ORM and Celery APIs.

From async contexts, wrap sync operations with `asgiref.sync.sync_to_async`, including:
- Celery `.delay()` and `.apply_async()`
- Django ORM calls like `.get()`, `.filter()`, `.create()`
- Model `.save()` and `.delete()`
- Django transactions
- Conversion functions that may touch lazy-loaded relations
- Other synchronous libraries

When returning GraphQL types from Django models, avoid accidental lazy database access in async contexts. Use `select_related`/`prefetch_related` where appropriate, or wrap the conversion function with `sync_to_async`.

Reference implementation: `api/src/services/album.py`.

## Frontend Patterns

When adding a new filter or query parameter to an Apollo-cached GraphQL query, update the relevant `keyArgs` array in `frontend/src/apolloClient.ts`. Otherwise Apollo may return cached results for different filter values.

When a component receives a function prop and calls it from `useEffect`, use the ref pattern so callers do not need to memoize the function.

Reference implementations:
- `frontend/src/hooks/useDebouncedSearch.ts`
- `frontend/src/components/ui/SearchInput.tsx`

## Docker Notes

The development override uses `frontend-dev` for Vite HMR on port `3000`; the production `frontend` service serves the built app through nginx.

If a Docker Compose service `command:` changes, recreate that service with `docker compose up -d <service>`. Hot reload tools re-run the original process command and do not re-read changed Compose command blocks.

## Local Notes

Personal or machine-specific instructions should go in ignored local files, not in this tracked file.
