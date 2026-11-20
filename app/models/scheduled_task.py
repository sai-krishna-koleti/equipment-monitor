"""Scheduled task ORM model for configured equipment polling schedules."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class TaskStatus(str, Enum):
    """Supported lifecycle states for a scheduled task."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


class ScheduledTask(Base):
    """A persisted schedule and processing cursor for one equipment machine."""

    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        Index("ix_scheduled_tasks_status_next_attempt", "status", "next_attempt"),
        Index("ix_scheduled_tasks_status_stop_at", "status", "stop_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[TaskStatus] = mapped_column(
        SqlEnum(
            TaskStatus,
            native_enum=False,
            create_constraint=True,
            name="scheduled_task_status",
        ),
        nullable=False,
    )
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stop_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_processed_cursor: Mapped[int | None] = mapped_column(Integer)

    processed_events: Mapped[list[ProcessedEvent]] = relationship(
        back_populates="task",
    )
    execution_history: Mapped[list[ExecutionHistory]] = relationship(
        back_populates="task",
    )
