"""Celery Beat scheduler that dispatches due active tasks from the database."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from celery.beat import Scheduler
from kombu.exceptions import KombuError
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import ScheduledTask
from app.models.scheduled_task import TaskStatus

logger = logging.getLogger(__name__)
PROCESSING_TASK_NAME = "app.workers.tasks.process_scheduled_task"
HEARTBEAT_FILE = Path(get_settings().celery_beat_heartbeat_file)


class ScheduledTaskBeatScheduler(Scheduler):
    """Poll scheduling metadata and enqueue due active task IDs."""

    def __init__(
        self,
        app: Any,
        schedule: dict[str, Any] | None = None,
        max_interval: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Configure Beat to check database task schedules at least once per second."""
        configured_interval = 1.0 if max_interval is None else min(max_interval, 1.0)
        super().__init__(
            app,
            schedule=schedule,
            max_interval=configured_interval,
            **kwargs,
        )

    def tick(self, *args: Any, **kwargs: Any) -> float:
        """Dispatch due tasks before processing any ordinary Celery Beat entries."""
        self.enqueue_due_tasks()
        try:
            HEARTBEAT_FILE.touch()
        except OSError:
            logger.exception("Could not update Celery Beat heartbeat")
        return super().tick(*args, **kwargs)

    def enqueue_due_tasks(self) -> None:
        """Atomically advance due schedules and send processing task messages."""
        now = datetime.now(timezone.utc)
        due_tasks: list[tuple[int, datetime | None, datetime]] = []

        with SessionLocal() as session:
            statement = select(ScheduledTask).where(
                ScheduledTask.status == TaskStatus.ACTIVE,
                or_(
                    ScheduledTask.next_attempt <= now,
                    and_(
                        ScheduledTask.next_attempt.is_(None),
                        ScheduledTask.start_at <= now,
                    ),
                    and_(
                        ScheduledTask.stop_at.is_not(None),
                        ScheduledTask.stop_at <= now,
                    ),
                ),
            )
            tasks = list(session.scalars(statement))
            for task in tasks:
                if task.stop_at is not None and _as_utc(task.stop_at) <= now:
                    task.status = TaskStatus.STOPPED
                    task.next_attempt = None
                    logger.info(
                        "Stopped expired scheduled task: task_id=%s stop_at=%s",
                        task.id,
                        task.stop_at,
                    )
                    continue

                previous_next_attempt = task.next_attempt
                due_at = _as_utc(task.next_attempt or task.start_at)
                interval_seconds = task.interval_seconds
                if interval_seconds <= 0:
                    raise ValueError(
                        f"Task {task.id} has invalid interval_seconds={interval_seconds}"
                    )

                missed_intervals = max(
                    1,
                    int((now - due_at).total_seconds() // interval_seconds) + 1,
                )
                next_attempt = due_at + timedelta(
                    seconds=missed_intervals * interval_seconds
                )
                task.next_attempt = next_attempt
                due_tasks.append((task.id, previous_next_attempt, next_attempt))
                logger.info(
                    "Task is due: task_id=%s interval_seconds=%s next_attempt=%s",
                    task.id,
                    interval_seconds,
                    next_attempt,
                )
            session.commit()

        for task_id, previous_next_attempt, next_attempt in due_tasks:
            try:
                self.app.send_task(PROCESSING_TASK_NAME, args=[task_id])
                logger.info(
                    "Enqueued scheduled task: task_id=%s task_name=%s",
                    task_id,
                    PROCESSING_TASK_NAME,
                )
            except (KombuError, OSError):
                logger.exception("Could not enqueue scheduled task: task_id=%s", task_id)
                self._restore_due_time(
                    task_id,
                    previous_next_attempt,
                    next_attempt,
                )

    @staticmethod
    def _restore_due_time(
        task_id: int,
        previous_next_attempt: datetime | None,
        enqueued_next_attempt: datetime,
    ) -> None:
        """Make a failed broker publication eligible for the next Beat tick."""
        with SessionLocal() as session:
            task = session.get(ScheduledTask, task_id)
            if (
                task is not None
                and task.status == TaskStatus.ACTIVE
                and task.next_attempt is not None
                and _as_utc(task.next_attempt) == enqueued_next_attempt
            ):
                task.next_attempt = previous_next_attempt
                session.commit()
                logger.info(
                    "Restored due time after enqueue failure: task_id=%s",
                    task_id,
                )


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive datetime values and aware database values to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
