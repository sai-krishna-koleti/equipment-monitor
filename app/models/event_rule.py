"""Event rule ORM model defining the catalog of recognized event codes."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class EventRule(Base):
    """A rule catalog entry associated with a unique equipment event code."""

    __tablename__ = "event_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    processed_events: Mapped[list[ProcessedEvent]] = relationship(
        back_populates="event_rule",
    )
