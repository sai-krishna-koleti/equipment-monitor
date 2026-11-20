"""Thin HTTP controllers for event rule creation, listing, and deletion."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.api.dependencies import EventRuleServiceDependency
from app.schemas.event_rule import EventRuleCreate, EventRuleResponse
from app.services.event_rule_service import (
    EventCodeConflictError,
    EventRuleInUseError,
    EventRuleNotFoundError,
)

router = APIRouter()
PositiveRuleId = Annotated[int, Path(ge=1)]


@router.post(
    "",
    response_model=EventRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_event_rule(
    payload: EventRuleCreate,
    service: EventRuleServiceDependency,
) -> EventRuleResponse:
    """Register a unique event code."""
    try:
        return service.create(payload.event_code, payload.description)
    except EventCodeConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="event_code already exists",
        ) from error


@router.get("", response_model=list[EventRuleResponse])
def list_event_rules(
    service: EventRuleServiceDependency,
) -> list[EventRuleResponse]:
    """Return all registered event rules."""
    return service.list_all()


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_event_rule(
    rule_id: PositiveRuleId,
    service: EventRuleServiceDependency,
) -> Response:
    """Remove an event rule that is not referenced by processed events."""
    try:
        service.delete(rule_id)
    except EventRuleNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event rule not found",
        ) from error
    except EventRuleInUseError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event rule is referenced by processed events",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
