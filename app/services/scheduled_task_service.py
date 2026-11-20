"""Application use cases for scheduled task lifecycle management."""

from datetime import datetime, timedelta, timezone

from app.models import ScheduledTask
from app.models.scheduled_task import TaskStatus
from app.repositories.scheduled_task_repository import ScheduledTaskRepository


class ScheduledTaskNotFoundError(Exception):
    """Raised when a scheduled task cannot be found."""


class InvalidTaskTransitionError(Exception):
    """Raised when a stopped task is asked to change lifecycle state."""


class ScheduledTaskService:
    """Implement task scheduling metadata and lifecycle transitions."""

    def __init__(self, repository: ScheduledTaskRepository) -> None:
        """Receive a repository bound to the current request database session."""
        self._repository = repository

    def create(
        self,
        *,
        machine_id: str,
        interval_seconds: int,
        start_at: datetime,
        stop_at: datetime | None,
    ) -> ScheduledTask:
        """Create an active scheduled task without dispatching execution work."""
        return self._repository.create(
            machine_id=machine_id,
            status=TaskStatus.ACTIVE,
            interval_seconds=interval_seconds,
            start_at=start_at,
            stop_at=stop_at,
        )

    def list_all(self) -> list[ScheduledTask]:
        """Return all scheduled task records, including paused and stopped ones."""
        return self._repository.list_all()

    def pause(self, task_id: int) -> ScheduledTask:
        """Pause an active task; repeated pause requests are idempotent."""
        task = self._get_task(task_id)
        if task.status == TaskStatus.STOPPED:
            raise InvalidTaskTransitionError(task_id)
        if task.status != TaskStatus.PAUSED:
            task.status = TaskStatus.PAUSED
            return self._repository.save(task)
        return task

    def resume(self, task_id: int) -> ScheduledTask:
        """Resume a paused task; repeated resume requests are idempotent."""
        task = self._get_task(task_id)
        if task.status == TaskStatus.STOPPED:
            raise InvalidTaskTransitionError(task_id)
        if task.status != TaskStatus.ACTIVE:
            task.status = TaskStatus.ACTIVE
            task.next_attempt = datetime.now(timezone.utc) + timedelta(
                seconds=task.interval_seconds
            )
            return self._repository.save(task)
        return task

    def stop(self, task_id: int) -> None:
        """Mark a task stopped while retaining its scheduling history."""
        task = self._get_task(task_id)
        if task.status != TaskStatus.STOPPED:
            task.status = TaskStatus.STOPPED
            task.next_attempt = None
            self._repository.save(task)

    def _get_task(self, task_id: int) -> ScheduledTask:
        task = self._repository.get_by_id(task_id)
        if task is None:
            raise ScheduledTaskNotFoundError(task_id)
        return task
