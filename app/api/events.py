"""Thin HTTP controller for filtered, paginated processed event queries."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import ProcessedEventServiceDependency
from app.schemas.processed_event import ProcessedEventPage
from app.services.processed_event_service import InvalidEventTimeRangeError

router = APIRouter()


@router.get("", response_model=ProcessedEventPage)
def list_events(
    service: ProcessedEventServiceDependency,
    machine_id: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    event_code: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    severity: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ProcessedEventPage:
    """Return events matching optional filters, newest timestamp first."""
    try:
        items, total_count = service.search(
            machine_id=machine_id,
            event_code=event_code,
            severity=severity,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size,
        )
    except InvalidEventTimeRangeError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_time must be earlier than or equal to end_time",
        ) from error

    return ProcessedEventPage(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
    )
