"""Pydantic request and response schemas for scheduled task endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.scheduled_task import TaskStatus


class ScheduledTaskCreate(BaseModel):
    """Validated request body for creating a scheduled task."""

    machine_id: str = Field(min_length=1, max_length=100)
    interval_seconds: int = Field(gt=0)
    start_at: datetime
    stop_at: datetime | None = None


class ScheduledTaskResponse(BaseModel):
    """Stored scheduling metadata returned by task endpoints."""

    id: int
    machine_id: str
    status: TaskStatus
    interval_seconds: int
    start_at: datetime
    stop_at: datetime | None
    last_attempt: datetime | None
    next_attempt: datetime | None
    last_processed_cursor: int | None

    model_config = ConfigDict(from_attributes=True)
