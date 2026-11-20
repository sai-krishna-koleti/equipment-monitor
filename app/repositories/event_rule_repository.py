"""SQLAlchemy repository for event rule persistence operations."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import EventRule


class EventRuleRepository:
    """Encapsulate database queries and transactions for event rules."""

    def __init__(self, session: Session) -> None:
        """Bind this repository to a request-scoped SQLAlchemy session."""
        self._session = session

    def get_by_id(self, rule_id: int) -> EventRule | None:
        """Find an event rule by its primary key."""
        return self._session.get(EventRule, rule_id)

    def get_by_event_code(self, event_code: str) -> EventRule | None:
        """Find an event rule by its unique event code."""
        statement = select(EventRule).where(EventRule.event_code == event_code)
        return self._session.scalar(statement)

    def list_all(self) -> list[EventRule]:
        """Return all event rules in stable primary-key order."""
        statement = select(EventRule).order_by(EventRule.id)
        return list(self._session.scalars(statement))

    def create(self, event_code: str, description: str) -> EventRule:
        """Persist a new event rule and return its database-populated fields."""
        rule = EventRule(event_code=event_code, description=description)
        self._session.add(rule)
        try:
            self._session.commit()
            self._session.refresh(rule)
        except IntegrityError:
            self._session.rollback()
            raise
        return rule

    def delete(self, rule: EventRule) -> None:
        """Delete a persisted event rule, rolling back failed constraints."""
        self._session.delete(rule)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            raise
