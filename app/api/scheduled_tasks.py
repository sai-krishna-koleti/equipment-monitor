"""Thin HTTP controllers for scheduled task lifecycle endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.api.dependencies import ScheduledTaskServiceDependency
from app.schemas.scheduled_task import (
    ScheduledTaskCreate,
    ScheduledTaskResponse,
)
from app.services.scheduled_task_service import (
    InvalidTaskTransitionError,
    ScheduledTaskNotFoundError,
)

router = APIRouter()
PositiveTaskId = Annotated[int, Path(ge=1)]


@router.post(
    "",
    response_model=ScheduledTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    payload: ScheduledTaskCreate,
    service: ScheduledTaskServiceDependency,
) -> ScheduledTaskResponse:
    """Create and persist a scheduled task without executing it."""
    return service.create(
        machine_id=payload.machine_id,
        interval_seconds=payload.interval_seconds,
        start_at=payload.start_at,
        stop_at=payload.stop_at,
    )


@router.get("", response_model=list[ScheduledTaskResponse])
def list_tasks(
    service: ScheduledTaskServiceDependency,
) -> list[ScheduledTaskResponse]:
    """Return all scheduled tasks and their current lifecycle states."""
    return service.list_all()


@router.put("/{id}/pause", response_model=ScheduledTaskResponse)
def pause_task(
    id: PositiveTaskId,
    service: ScheduledTaskServiceDependency,
) -> ScheduledTaskResponse:
    """Pause an active scheduled task."""
    try:
        return service.pause(id)
    except ScheduledTaskNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled task not found",
        ) from error
    except InvalidTaskTransitionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stopped tasks cannot be paused",
        ) from error


@router.put("/{id}/resume", response_model=ScheduledTaskResponse)
def resume_task(
    id: PositiveTaskId,
    service: ScheduledTaskServiceDependency,
) -> ScheduledTaskResponse:
    """Resume a paused scheduled task."""
    try:
        return service.resume(id)
    except ScheduledTaskNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled task not found",
        ) from error
    except InvalidTaskTransitionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stopped tasks cannot be resumed",
        ) from error


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def stop_task(
    id: PositiveTaskId,
    service: ScheduledTaskServiceDependency,
) -> Response:
    """Stop a scheduled task while retaining its database record."""
    try:
        service.stop(id)
    except ScheduledTaskNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled task not found",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
