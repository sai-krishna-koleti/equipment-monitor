"""Application use cases for creating, listing, and deleting event rules."""

from sqlalchemy.exc import IntegrityError

from app.models import EventRule
from app.repositories.event_rule_repository import EventRuleRepository


class EventCodeConflictError(Exception):
    """Raised when an event code is already registered."""


class EventRuleNotFoundError(Exception):
    """Raised when a requested event rule does not exist."""


class EventRuleInUseError(Exception):
    """Raised when a rule cannot be deleted because events reference it."""


class EventRuleService:
    """Apply event rule use cases using the repository persistence boundary."""

    def __init__(self, repository: EventRuleRepository) -> None:
        """Receive a repository bound to the current request's database session."""
        self._repository = repository

    def create(self, event_code: str, description: str) -> EventRule:
        """Create an event rule while handling concurrent unique-code conflicts."""
        if self._repository.get_by_event_code(event_code) is not None:
            raise EventCodeConflictError(event_code)

        try:
            return self._repository.create(event_code, description)
        except IntegrityError as error:
            if self._repository.get_by_event_code(event_code) is not None:
                raise EventCodeConflictError(event_code) from error
            raise

    def list_all(self) -> list[EventRule]:
        """Return all registered event rules."""
        return self._repository.list_all()

    def delete(self, rule_id: int) -> None:
        """Delete a rule or report missing and still-referenced rules."""
        rule = self._repository.get_by_id(rule_id)
        if rule is None:
            raise EventRuleNotFoundError(rule_id)

        try:
            self._repository.delete(rule)
        except IntegrityError as error:
            raise EventRuleInUseError(rule_id) from error
