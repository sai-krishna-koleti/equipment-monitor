"""SQLAlchemy query builder for filtered and paginated processed events."""

from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import ProcessedEvent


class ProcessedEventRepository:
    """Build matching count and page queries without loading relationships."""

    def __init__(self, session: Session) -> None:
        """Bind this repository to a request-scoped SQLAlchemy session."""
        self._session = session

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
        """Return one timestamp-descending page and total count for its filters."""
        filters: list[ColumnElement[bool]] = []
        if machine_id is not None:
            filters.append(ProcessedEvent.machine_id == machine_id)
        if event_code is not None:
            filters.append(ProcessedEvent.event_code == event_code)
        if severity is not None:
            filters.append(ProcessedEvent.severity == severity)
        if start_time is not None:
            filters.append(ProcessedEvent.timestamp >= start_time)
        if end_time is not None:
            filters.append(ProcessedEvent.timestamp <= end_time)

        count_statement = (
            select(func.count(ProcessedEvent.id))
            .select_from(ProcessedEvent)
            .where(*filters)
        )
        total_count = self._session.execute(count_statement).scalar_one()

        page_statement = (
            select(ProcessedEvent)
            .where(*filters)
            .order_by(desc(ProcessedEvent.timestamp), desc(ProcessedEvent.id))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self._session.scalars(page_statement))
        return items, total_count
