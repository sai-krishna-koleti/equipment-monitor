"""Shared FastAPI dependencies for injecting infrastructure into route handlers."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.event_rule_repository import EventRuleRepository
from app.repositories.processed_event_repository import ProcessedEventRepository
from app.repositories.scheduled_task_repository import ScheduledTaskRepository
from app.services.event_rule_service import EventRuleService
from app.services.processed_event_service import ProcessedEventService
from app.services.scheduled_task_service import ScheduledTaskService

DatabaseSession = Annotated[Session, Depends(get_db)]


def get_event_rule_service(session: DatabaseSession) -> EventRuleService:
    """Build the event rule service with a request-scoped repository."""
    return EventRuleService(EventRuleRepository(session))


EventRuleServiceDependency = Annotated[
    EventRuleService,
    Depends(get_event_rule_service),
]


def get_scheduled_task_service(session: DatabaseSession) -> ScheduledTaskService:
    """Build the task service with a request-scoped repository."""
    return ScheduledTaskService(ScheduledTaskRepository(session))


ScheduledTaskServiceDependency = Annotated[
    ScheduledTaskService,
    Depends(get_scheduled_task_service),
]


def get_processed_event_service(session: DatabaseSession) -> ProcessedEventService:
    """Build the processed event service with a request-scoped repository."""
    return ProcessedEventService(ProcessedEventRepository(session))


ProcessedEventServiceDependency = Annotated[
    ProcessedEventService,
    Depends(get_processed_event_service),
]
