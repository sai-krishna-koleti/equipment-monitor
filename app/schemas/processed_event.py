"""Pydantic response schemas for filtered processed event listings."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProcessedEventResponse(BaseModel):
    """Processed event fields exposed in the events API."""

    id: int
    machine_id: str
    cursor: int
    timestamp: datetime
    event_code: str
    severity: str
    task_id: int

    model_config = ConfigDict(from_attributes=True)


class ProcessedEventPage(BaseModel):
    """Paginated events and the total matching filter count."""

    items: list[ProcessedEventResponse]
    total_count: int
    page: int
    page_size: int
