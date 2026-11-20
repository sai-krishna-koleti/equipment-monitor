"""Processed event ORM model with a composite idempotency constraint."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ProcessedEvent(Base):
    """An equipment event recorded once per machine and source cursor."""

    __tablename__ = "processed_events"
    __table_args__ = (
        UniqueConstraint("machine_id", "cursor"),
        Index("ix_processed_events_timestamp_id", "timestamp", "id"),
        Index(
            "ix_processed_events_machine_timestamp_id",
            "machine_id",
            "timestamp",
            "id",
        ),
        Index(
            "ix_processed_events_event_code_timestamp_id",
            "event_code",
            "timestamp",
            "id",
        ),
        Index(
            "ix_processed_events_severity_timestamp_id",
            "severity",
            "timestamp",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(100), nullable=False)
    cursor: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_code: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("event_rules.event_code"),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("scheduled_tasks.id"),
        nullable=False,
        index=True,
    )

    event_rule: Mapped[EventRule] = relationship(back_populates="processed_events")
    task: Mapped[ScheduledTask] = relationship(back_populates="processed_events")
