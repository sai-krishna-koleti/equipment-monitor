# Equipment Event Monitoring System

A clean-architecture FastAPI backend scaffold for an equipment event monitoring
system. It wires configuration, persistence, and worker infrastructure and
includes SQLAlchemy domain models, event rule and task scheduling APIs, a
simulator, and an idempotent Celery event-processing task.

## Project layout

```text
app/
  api/           HTTP routes and request dependencies
  core/          Settings, logging, database, and Celery configuration
  models/        SQLAlchemy ORM base and event/task persistence models
  repositories/  Persistence adapters
  schemas/       Pydantic request and response schemas
  services/      Application use cases
  simulator/     Event generation service and CSV storage
  workers/       Celery event-processing tasks
tests/
```

Each Python module has a module docstring describing its purpose.

## Data models

The ORM defines `EventRule`, `ScheduledTask`, `ProcessedEvent`, and
`ExecutionHistory`. Model imports register every table with `Base.metadata` for
migration tooling. `ProcessedEvent` enforces uniqueness of `(machine_id,
cursor)` to prevent duplicate processing, and uses foreign keys to associate
events with rules and scheduled tasks. No schema creation or migration is run
automatically by the application.

## Configuration

Settings are loaded from environment variables and `.env` using Pydantic
Settings. The checked-in `.env` contains development defaults only; do not put
secrets in it. `.env` is ignored by Git. Use `.env.example` as a template when
setting up another environment.

## Run locally

Requires Python 3.12+ and a Redis server.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API documentation UI is available at `http://localhost:8000/docs`.
With Redis running locally, start the worker and Beat in separate terminals:

```powershell
celery -A app.core.celery_app.celery_app worker --loglevel=INFO
celery -A app.core.celery_app.celery_app beat --scheduler=app.workers.beat_scheduler:ScheduledTaskBeatScheduler --loglevel=INFO
```

## Simulator API

The simulator generates one random event per machine every three seconds by
default and appends events to `app/simulator/files/<machine_id>.csv`. Cursor
values resume from existing machine CSVs when the service restarts.

- `POST /v1/simulator/download` accepts `machine_id` and
  `last_processed_cursor`, then returns CSV metadata for newer events.
- `GET /v1/simulator/files/{file_name}` returns the requested CSV snapshot.

The generation interval can be changed with `SIMULATOR_INTERVAL_SECONDS`.

## Event rule API

- `POST /v1/event-codes` creates an event rule and returns `201 Created`.
  Duplicate `event_code` values return `409 Conflict`.
- `GET /v1/event-codes` lists event rules.
- `DELETE /v1/event-codes/{id}` returns `204 No Content`, or `404 Not Found`
  when the rule does not exist. A rule referenced by processed events returns
  `409 Conflict`.

## Processed events API

`GET /v1/events` supports optional `machine_id`, `event_code`, `severity`,
`start_time`, and `end_time` filters. Time bounds are inclusive; timezone-naive
values are interpreted as UTC. Results are ordered by timestamp descending
(then ID descending), with `page=1` and `page_size=20` defaults. Page sizes are
limited to 100. The response includes `items`, `total_count`, `page`, and
`page_size`.

## Task scheduling API

- `POST /v1/tasks` stores machine and scheduling metadata and creates an `ACTIVE`
  task. It does not dispatch work to Celery.
- `GET /v1/tasks` lists tasks, including paused and stopped records.
- `PUT /v1/tasks/{id}/pause` and `PUT /v1/tasks/{id}/resume` change task status.
- `DELETE /v1/tasks/{id}` marks the record `STOPPED` and retains its metadata.

Tasks use the `ACTIVE`, `PAUSED`, and `STOPPED` statuses. Pause and resume are
idempotent for tasks already in the requested state; stopped tasks cannot be
resumed or paused. Resuming resets `next_attempt` to one interval from the
resume time.

Celery Beat polls active task metadata and enqueues each due task according to
`interval_seconds`. Paused tasks are not enqueued, and tasks whose `stop_at`
has passed are marked `STOPPED`.

## Celery event processing

The worker task `app.workers.tasks.process_scheduled_task` accepts a
`ScheduledTask` ID. It requests events after the stored cursor, downloads and
validates the CSV, stores only events whose codes exist in `EventRule`, skips
duplicate `(machine_id, cursor)` pairs, advances the cursor, and writes an
`ExecutionHistory` record. Celery Beat enqueues due active tasks; a task can
also be enqueued manually with `process_scheduled_task.delay(task_id)`.

The simulator CSV does not include severity, so stored events use
`severity="UNKNOWN"`. The worker API base URL is configured with
`SIMULATOR_API_BASE_URL` (`http://localhost:8000` locally and
`http://api:8000` in Docker Compose).

## Run with Docker Compose

Install Docker Engine/Desktop with the Docker Compose v2 plugin. Create a local
environment file from the template if `.env` does not already exist:

```powershell
Copy-Item .env.example .env
```

### Production configuration

The base Compose file runs the API, worker, Beat, and Redis without source-code
mounts or reload. Set a strong URL-safe `REDIS_PASSWORD` in `.env` before
deployment. Generate one with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

The API port binds to `127.0.0.1:8000` by default. Set `API_BIND_ADDRESS=0.0.0.0`
when it must be reachable outside the host, and optionally set `API_PORT`.
The API uses one Uvicorn worker because the simulator generator is managed by
the application lifespan; run a single API container until that generator is
moved to a dedicated singleton service.

```powershell
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f
docker compose logs -f api worker beat redis
docker compose restart api worker beat
```

Service health can be checked explicitly:

```powershell
docker compose exec api python -m app.core.healthcheck api
docker compose exec worker python -m app.core.healthcheck worker
docker compose exec beat python -m app.core.healthcheck beat
```

The API, worker, and Beat share the SQLite data volume. Redis and simulator CSV
files have separate named volumes. `docker compose stop` stops services,
`docker compose down` removes containers while preserving volumes, and
`docker compose down --volumes` also deletes persisted data.

### Development with automatic reload

The development override mounts source files and runs Uvicorn with `--reload`:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f api
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

Development mode sets `ENVIRONMENT=development` and `DEBUG=true`. The base
Compose configuration uses production settings and does not enable reload.

The application currently does not run schema migrations automatically; apply
the database schema before sending application requests in a fresh deployment.

## Test

```powershell
pytest
```


test cases

From the project root, activate your virtual environment and run the test suite:

```powershell
cd "C:\Users\VENKATAVETAPALEM\Desktop\Sai Krishna\equipment-monitor"
.\.venv\Scripts\Activate.ps1
python -m pytest -v
```

To run one test file:

```powershell
python -m pytest tests/test_events.py -v
```

To run one specific test, add `::` and its test function name:

```powershell
python -m pytest tests/test_events.py::test_list_events -v
```

If you’re unsure of a test’s exact name, list discovered tests with:

```powershell
python -m pytest --collect-only -q
```

