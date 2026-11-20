"""Application query service for filtered processed event retrieval."""

from datetime import datetime, timezone

from app.models import ProcessedEvent
from app.repositories.processed_event_repository import ProcessedEventRepository


class InvalidEventTimeRangeError(Exception):
    """Raised when an event query's start time is after its end time."""


class ProcessedEventService:
    """Validate event query parameters and delegate paging to the repository."""

    def __init__(self, repository: ProcessedEventRepository) -> None:
        """Receive a repository bound to the current request database session."""
        self._repository = repository

    def search(
        self,
        *,
        machine_id: str | None,
        event_code: str | None,
        severity: str | None,
        start_time: datetime | None,
        end_time: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ProcessedEvent], int]:
        """Return the requested filtered page and matching total."""
        if start_time is not None:
            start_time = _as_utc(start_time)
        if end_time is not None:
            end_time = _as_utc(end_time)
        if start_time is not None and end_time is not None and start_time > end_time:
            raise InvalidEventTimeRangeError

        return self._repository.search(
            machine_id=machine_id,
            event_code=event_code,
            severity=severity,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size,
        )


def _as_utc(value: datetime) -> datetime:
    """Treat naive filter values as UTC and normalize aware values to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
