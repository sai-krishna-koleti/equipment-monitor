"""SQLAlchemy repository for scheduled task persistence operations."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ScheduledTask
from app.models.scheduled_task import TaskStatus


class ScheduledTaskRepository:
    """Encapsulate task queries and persistence for scheduling metadata."""

    def __init__(self, session: Session) -> None:
        """Bind this repository to a request-scoped SQLAlchemy session."""
        self._session = session

    def get_by_id(self, task_id: int) -> ScheduledTask | None:
        """Find a scheduled task by its primary key."""
        return self._session.get(ScheduledTask, task_id)

    def list_all(self) -> list[ScheduledTask]:
        """Return all scheduled tasks in stable primary-key order."""
        statement = select(ScheduledTask).order_by(ScheduledTask.id)
        return list(self._session.scalars(statement))

    def create(
        self,
        *,
        machine_id: str,
        status: TaskStatus,
        interval_seconds: int,
        start_at: datetime,
        stop_at: datetime | None,
    ) -> ScheduledTask:
        """Persist a new active task and its initial scheduling metadata."""
        task = ScheduledTask(
            machine_id=machine_id,
            status=status,
            interval_seconds=interval_seconds,
            start_at=start_at,
            stop_at=stop_at,
            next_attempt=start_at,
        )
        self._session.add(task)
        self._session.commit()
        self._session.refresh(task)
        return task

    def save(self, task: ScheduledTask) -> ScheduledTask:
        """Persist changes to an existing task and return refreshed state."""
        self._session.add(task)
        self._session.commit()
        self._session.refresh(task)
        return task
