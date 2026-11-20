"""Tests for dynamic Celery Beat scheduling of active database tasks."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.celery_app import celery_app
from app.models import Base, ScheduledTask
from app.models.scheduled_task import TaskStatus
from app.workers.beat_scheduler import (
    PROCESSING_TASK_NAME,
    ScheduledTaskBeatScheduler,
)
from app.workers import beat_scheduler


@pytest.fixture
def scheduler_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[sessionmaker[Session], None, None]:
    """Provide an isolated database for Beat scheduler tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(beat_scheduler, "SessionLocal", session_factory)
    try:
        yield session_factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _insert_task(
    session: Session,
    *,
    status: TaskStatus,
    next_attempt: datetime | None,
    start_at: datetime,
    stop_at: datetime | None = None,
) -> ScheduledTask:
    """Create test scheduling metadata with a supplied lifecycle state."""
    task = ScheduledTask(
        machine_id="ETCH-001",
        status=status,
        interval_seconds=60,
        start_at=start_at,
        stop_at=stop_at,
        next_attempt=next_attempt,
    )
    session.add(task)
    session.flush()
    return task


def test_beat_enqueues_only_due_active_tasks_and_stops_expired_tasks(
    scheduler_sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Beat skips paused/stopped tasks and respects task stop_at timestamps."""
    now = datetime.now(timezone.utc)
    with scheduler_sessions() as session:
        active = _insert_task(
            session,
            status=TaskStatus.ACTIVE,
            next_attempt=now - timedelta(seconds=10),
            start_at=now - timedelta(minutes=5),
        )
        paused = _insert_task(
            session,
            status=TaskStatus.PAUSED,
            next_attempt=now - timedelta(minutes=1),
            start_at=now - timedelta(minutes=5),
        )
        stopped = _insert_task(
            session,
            status=TaskStatus.STOPPED,
            next_attempt=now - timedelta(minutes=1),
            start_at=now - timedelta(minutes=5),
        )
        expired = _insert_task(
            session,
            status=TaskStatus.ACTIVE,
            next_attempt=now - timedelta(seconds=10),
            start_at=now - timedelta(minutes=5),
            stop_at=now - timedelta(seconds=1),
        )
        active_id, paused_id, stopped_id, expired_id = (
            active.id,
            paused.id,
            stopped.id,
            expired.id,
        )
        session.commit()

    enqueued: list[tuple[str, list[int]]] = []
    monkeypatch.setattr(
        celery_app,
        "send_task",
        lambda task_name, args: enqueued.append((task_name, args)),
    )
    monkeypatch.setattr(
        beat_scheduler,
        "HEARTBEAT_FILE",
        tmp_path / "celery-beat-heartbeat",
    )
    scheduler = ScheduledTaskBeatScheduler(celery_app, schedule={})
    scheduler.tick()

    assert enqueued == [(PROCESSING_TASK_NAME, [active_id])]
    with scheduler_sessions() as session:
        tasks = {
            task.id: task
            for task in session.scalars(
                select(ScheduledTask).where(
                    ScheduledTask.id.in_(
                        [active_id, paused_id, stopped_id, expired_id]
                    )
                )
            )
        }

    assert tasks[active_id].next_attempt is not None
    assert tasks[active_id].next_attempt.replace(tzinfo=timezone.utc) > now
    assert tasks[paused_id].status == TaskStatus.PAUSED
    assert tasks[stopped_id].status == TaskStatus.STOPPED
    assert tasks[expired_id].status == TaskStatus.STOPPED
    assert tasks[expired_id].next_attempt is None


def test_beat_restores_due_time_when_broker_enqueue_fails(
    scheduler_sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed broker publish leaves the active task eligible for the next tick."""
    due_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with scheduler_sessions() as session:
        task = _insert_task(
            session,
            status=TaskStatus.ACTIVE,
            next_attempt=due_at,
            start_at=due_at,
        )
        task_id = task.id
        session.commit()

    def fail_enqueue(*args: object, **kwargs: object) -> None:
        raise OSError("broker unavailable")

    monkeypatch.setattr(celery_app, "send_task", fail_enqueue)
    scheduler = ScheduledTaskBeatScheduler(celery_app, schedule={})
    scheduler.enqueue_due_tasks()

    with scheduler_sessions() as session:
        task = session.get(ScheduledTask, task_id)
    assert task is not None
    assert task.next_attempt == due_at.replace(tzinfo=None)
