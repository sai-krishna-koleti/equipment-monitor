"""Tests for Celery event processing, idempotency, and failure history."""

import json
from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, EventRule, ExecutionHistory, ProcessedEvent, ScheduledTask
from app.models.scheduled_task import TaskStatus
from app.workers import tasks as worker_tasks
from app.core.celery_app import celery_app

CSV_CONTENT = (
    "cursor,timestamp,event_code\n"
    "1,2026-01-01T00:00:00+00:00,TEMP_HIGH\n"
    "2,2026-01-01T00:00:01+00:00,UNKNOWN_CODE\n"
    "3,2026-01-01T00:00:02+00:00,FLOW_LOW\n"
)


@pytest.fixture
def worker_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[sessionmaker[Session], None, None]:
    """Provide an isolated database and inject its session factory into the worker."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker_tasks, "SessionLocal", session_factory)
    try:
        yield session_factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _create_active_task(session_factory: sessionmaker[Session]) -> int:
    """Insert a task with matching rules and one previously stored event."""
    with session_factory() as session:
        session.add_all(
            [
                EventRule(event_code="TEMP_HIGH", description="High temperature"),
                EventRule(event_code="FLOW_LOW", description="Low flow"),
            ]
        )
        task = ScheduledTask(
            machine_id="ETCH-001",
            status=TaskStatus.ACTIVE,
            interval_seconds=60,
            start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session.add(task)
        session.flush()
        session.add(
            ProcessedEvent(
                machine_id="ETCH-001",
                cursor=1,
                timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                event_code="TEMP_HIGH",
                severity="UNKNOWN",
                task_id=task.id,
            )
        )
        session.commit()
        return task.id


def test_worker_filters_events_updates_cursor_and_is_idempotent(
    worker_sessions: sessionmaker[Session],
) -> None:
    """Only registered events are stored and replayed cursors are not duplicated."""
    task_id = _create_active_task(worker_sessions)
    request_cursors: list[int] = []

    def simulator_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            payload = json.loads(request.content)
            request_cursors.append(payload["last_processed_cursor"])
            if payload["last_processed_cursor"] >= 3:
                return httpx.Response(
                    404,
                    json={"detail": worker_tasks.NO_EVENTS_DETAIL},
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "machine_id": "ETCH-001",
                    "file_name": "snapshot.csv",
                    "start_cursor": 1,
                    "end_cursor": 3,
                    "download_url": "http://simulator/v1/simulator/files/snapshot.csv",
                },
                request=request,
            )
        return httpx.Response(
            200,
            content=CSV_CONTENT,
            headers={"content-type": "text/csv"},
            request=request,
        )

    transport = httpx.MockTransport(simulator_handler)
    with httpx.Client(base_url="http://simulator", transport=transport) as client:
        first_result = worker_tasks.run_scheduled_task(task_id, client)
        second_result = worker_tasks.run_scheduled_task(task_id, client)

    assert request_cursors == [0, 3]
    assert first_result == {
        "task_id": task_id,
        "status": "SUCCESS",
        "records_processed": 3,
        "records_stored": 1,
        "last_processed_cursor": 3,
    }
    assert second_result["records_processed"] == 0
    assert second_result["last_processed_cursor"] == 3

    with worker_sessions() as session:
        stored_events = list(
            session.scalars(
                select(ProcessedEvent).order_by(ProcessedEvent.cursor)
            )
        )
        histories = list(
            session.scalars(
                select(ExecutionHistory).order_by(ExecutionHistory.id)
            )
        )
        task = session.get(ScheduledTask, task_id)

    assert [(event.cursor, event.event_code) for event in stored_events] == [
        (1, "TEMP_HIGH"),
        (3, "FLOW_LOW"),
    ]
    assert stored_events[1].severity == "UNKNOWN"
    assert [history.status for history in histories] == ["SUCCESS", "SUCCESS"]
    assert [history.records_processed for history in histories] == [3, 0]
    assert task is not None
    assert task.last_processed_cursor == 3
    assert task.last_attempt is not None


def test_worker_records_api_failure_and_propagates_error(
    worker_sessions: sessionmaker[Session],
) -> None:
    """Simulator failures are recorded without advancing the cursor and re-raised."""
    task_id = _create_active_task(worker_sessions)

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    with httpx.Client(
        base_url="http://simulator",
        transport=httpx.MockTransport(failing_handler),
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            worker_tasks.run_scheduled_task(task_id, client)

    with worker_sessions() as session:
        task = session.get(ScheduledTask, task_id)
        histories = list(session.scalars(select(ExecutionHistory)))

    assert task is not None
    assert task.last_processed_cursor is None
    assert task.last_attempt is not None
    assert len(histories) == 1
    assert histories[0].status == "FAILED"
    assert "503" in (histories[0].message or "")


def test_celery_entrypoint_uses_mock_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered Celery task delegates without contacting Redis or HTTP."""
    received: dict[str, object] = {}

    class MockClient:
        def __init__(self, *, base_url: str, timeout: float) -> None:
            received["base_url"] = base_url
            received["timeout"] = timeout

        def __enter__(self) -> MockClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        worker_tasks,
        "get_settings",
        lambda: SimpleNamespace(simulator_api_base_url="http://simulator/"),
    )
    monkeypatch.setattr(worker_tasks.httpx, "Client", MockClient)
    monkeypatch.setattr(
        worker_tasks,
        "run_scheduled_task",
        lambda task_id, client: received.update(
            {"task_id": task_id, "client": client}
        )
        or {"task_id": task_id, "status": "SUCCESS"},
    )

    task = worker_tasks.process_scheduled_task
    result = task.run(42)

    assert task.name == "app.workers.tasks.process_scheduled_task"
    assert task.name in celery_app.tasks
    assert result == {"task_id": 42, "status": "SUCCESS"}
    assert received["base_url"] == "http://simulator"
    assert received["timeout"] == 30.0
    assert received["task_id"] == 42
