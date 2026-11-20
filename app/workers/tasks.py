"""Celery task for fetching, filtering, and idempotently storing machine events."""

import csv
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError
from sqlalchemy import case, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import EventRule, ExecutionHistory, ProcessedEvent, ScheduledTask
from app.models.scheduled_task import TaskStatus
from app.schemas.simulator import SimulatorDownloadResponse

logger = logging.getLogger(__name__)
CSV_FIELDS = ("cursor", "timestamp", "event_code")
UNKNOWN_SEVERITY = "UNKNOWN"
NO_EVENTS_DETAIL = "No events are available after the supplied cursor"


@dataclass(frozen=True)
class SimulatorEvent:
    """Validated event row returned by the simulator CSV endpoint."""

    cursor: int
    timestamp: datetime
    event_code: str


def run_scheduled_task(task_id: int, client: httpx.Client) -> dict[str, Any]:
    """Process one task attempt using an injected HTTP client."""
    started_at = datetime.now(timezone.utc)
    logger.info("Starting scheduled task processing: task_id=%s", task_id)

    with SessionLocal() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None:
            logger.error("Scheduled task not found: task_id=%s", task_id)
            raise LookupError(f"Scheduled task {task_id} does not exist")

        machine_id = task.machine_id
        last_processed_cursor = task.last_processed_cursor or 0
        task_status = task.status
        logger.info(
            "Loaded task metadata: task_id=%s machine_id=%s status=%s cursor=%s",
            task_id,
            machine_id,
            task_status.value,
            last_processed_cursor,
        )

        if task_status != TaskStatus.ACTIVE:
            task.last_attempt = started_at
            _add_history(
                session,
                task_id=task_id,
                started_at=started_at,
                status="SKIPPED",
                records_processed=0,
                message=f"Task status is {task_status.value}",
            )
            session.commit()
            logger.info("Skipped inactive scheduled task: task_id=%s", task_id)
            return {
                "task_id": task_id,
                "status": "SKIPPED",
                "records_processed": 0,
                "last_processed_cursor": last_processed_cursor,
            }

    try:
        logger.info(
            "Requesting simulator events: task_id=%s machine_id=%s cursor=%s",
            task_id,
            machine_id,
            last_processed_cursor,
        )
        events = _fetch_events(client, machine_id, last_processed_cursor)
        logger.info(
            "Simulator response received: task_id=%s event_count=%s",
            task_id,
            len(events) if events is not None else 0,
        )
        return _persist_events(
            task_id=task_id,
            started_at=started_at,
            events=events,
        )
    except (
        httpx.HTTPError,
        ValidationError,
        csv.Error,
        ValueError,
        TypeError,
        KeyError,
        SQLAlchemyError,
        OSError,
    ) as error:
        logger.exception("Scheduled task processing failed: task_id=%s", task_id)
        _record_failed_attempt(task_id, started_at, error)
        raise


def _fetch_events(
    client: httpx.Client,
    machine_id: str,
    last_processed_cursor: int,
) -> list[SimulatorEvent] | None:
    """Request a simulator snapshot and validate its CSV records."""
    response = client.post(
        "/v1/simulator/download",
        json={
            "machine_id": machine_id,
            "last_processed_cursor": last_processed_cursor,
        },
    )
    if response.status_code == 404:
        response_body = response.json()
        if isinstance(response_body, dict) and response_body.get("detail") == NO_EVENTS_DETAIL:
            logger.info(
                "No new simulator events: machine_id=%s cursor=%s",
                machine_id,
                last_processed_cursor,
            )
            return None
    response.raise_for_status()

    metadata = SimulatorDownloadResponse.model_validate(response.json())
    if metadata.machine_id != machine_id:
        raise ValueError("Simulator response machine_id does not match the task")
    _validate_download_origin(client, metadata.download_url)

    logger.info(
        "Downloading simulator CSV: file_name=%s cursor_range=%s-%s",
        metadata.file_name,
        metadata.start_cursor,
        metadata.end_cursor,
    )
    file_response = client.get(metadata.download_url)
    file_response.raise_for_status()
    csv_content = file_response.content.decode("utf-8")
    events = _parse_csv(csv_content, last_processed_cursor)
    if not events:
        raise ValueError("Simulator returned an empty CSV snapshot")
    if (
        events[0].cursor != metadata.start_cursor
        or events[-1].cursor != metadata.end_cursor
    ):
        raise ValueError("CSV cursor range does not match simulator download metadata")
    logger.info(
        "Downloaded CSV bytes: file_name=%s byte_count=%s",
        metadata.file_name,
        len(file_response.content),
    )
    return events


def _validate_download_origin(client: httpx.Client, download_url: str) -> None:
    """Ensure the simulator-provided file URL uses the configured API origin."""
    base = urlsplit(str(client.base_url))
    download = urlsplit(download_url)
    if (download.scheme, download.netloc) != (base.scheme, base.netloc):
        raise ValueError("Simulator download URL does not match the API origin")


def _parse_csv(csv_content: str, last_processed_cursor: int) -> list[SimulatorEvent]:
    """Parse CSV rows while validating columns, cursors, and timestamps."""
    reader = csv.DictReader(io.StringIO(csv_content, newline=""))
    if reader.fieldnames != list(CSV_FIELDS):
        raise ValueError("Simulator CSV has an unexpected header")

    events: list[SimulatorEvent] = []
    previous_cursor = last_processed_cursor
    for row in reader:
        cursor_value = row.get("cursor")
        timestamp_value = row.get("timestamp")
        event_code = row.get("event_code")
        if not cursor_value or not timestamp_value or not event_code:
            raise ValueError("Simulator CSV rows must contain all required values")

        cursor = int(cursor_value)
        if cursor <= previous_cursor:
            raise ValueError("Simulator CSV cursors must increase beyond the task cursor")

        timestamp = datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Simulator event timestamps must include a timezone")

        events.append(
            SimulatorEvent(
                cursor=cursor,
                timestamp=timestamp,
                event_code=event_code,
            )
        )
        previous_cursor = cursor
    return events


def _persist_events(
    *,
    task_id: int,
    started_at: datetime,
    events: list[SimulatorEvent] | None,
) -> dict[str, Any]:
    """Filter and persist events, cursor advancement, and history atomically."""
    records_processed = len(events) if events is not None else 0
    with SessionLocal() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None:
            raise LookupError(f"Scheduled task {task_id} no longer exists")

        if task.status != TaskStatus.ACTIVE:
            task.last_attempt = started_at
            _add_history(
                session,
                task_id=task_id,
                started_at=started_at,
                status="SKIPPED",
                records_processed=0,
                message=f"Task status changed to {task.status.value} before processing",
            )
            session.commit()
            logger.info("Task became inactive before persistence: task_id=%s", task_id)
            return {
                "task_id": task_id,
                "status": "SKIPPED",
                "records_processed": 0,
                "last_processed_cursor": task.last_processed_cursor or 0,
            }

        registered_codes = set(session.scalars(select(EventRule.event_code)))
        logger.info(
            "Loaded registered event rules: task_id=%s rule_count=%s",
            task_id,
            len(registered_codes),
        )
        existing_cursors: set[int] = set()
        if events:
            existing_cursors = set(
                session.scalars(
                    select(ProcessedEvent.cursor).where(
                        ProcessedEvent.machine_id == task.machine_id,
                        ProcessedEvent.cursor >= events[0].cursor,
                        ProcessedEvent.cursor <= events[-1].cursor,
                    )
                )
            )

        records_stored = 0
        if events:
            for event in events:
                if event.event_code not in registered_codes:
                    logger.info(
                        "Skipping unregistered event code: machine_id=%s cursor=%s event_code=%s",
                        task.machine_id,
                        event.cursor,
                        event.event_code,
                    )
                    continue
                if event.cursor in existing_cursors:
                    logger.info(
                        "Skipping duplicate event: machine_id=%s cursor=%s",
                        task.machine_id,
                        event.cursor,
                    )
                    continue

                processed_event = ProcessedEvent(
                    machine_id=task.machine_id,
                    cursor=event.cursor,
                    timestamp=event.timestamp,
                    event_code=event.event_code,
                    severity=UNKNOWN_SEVERITY,
                    task_id=task.id,
                )
                try:
                    with session.begin_nested():
                        session.add(processed_event)
                        session.flush()
                except IntegrityError:
                    duplicate_id = session.scalar(
                        select(ProcessedEvent.id).where(
                            ProcessedEvent.machine_id == task.machine_id,
                            ProcessedEvent.cursor == event.cursor,
                        )
                    )
                    if duplicate_id is None:
                        raise
                    logger.info(
                        "Skipped concurrent duplicate event: machine_id=%s cursor=%s",
                        task.machine_id,
                        event.cursor,
                    )
                    existing_cursors.add(event.cursor)
                    continue

                existing_cursors.add(event.cursor)
                records_stored += 1
                logger.info(
                    "Stored matching event: machine_id=%s cursor=%s event_code=%s",
                    task.machine_id,
                    event.cursor,
                    event.event_code,
                )

            end_cursor = events[-1].cursor
            session.execute(
                update(ScheduledTask)
                .where(ScheduledTask.id == task_id)
                .values(
                    last_processed_cursor=case(
                        (
                            or_(
                                ScheduledTask.last_processed_cursor.is_(None),
                                ScheduledTask.last_processed_cursor < end_cursor,
                            ),
                            end_cursor,
                        ),
                        else_=ScheduledTask.last_processed_cursor,
                    ),
                    last_attempt=started_at,
                )
                .execution_options(synchronize_session=False)
            )
            session.expire(task)
            session.refresh(task)
            logger.info(
                "Updated task cursor: task_id=%s last_processed_cursor=%s",
                task_id,
                task.last_processed_cursor,
            )
            message = (
                f"Processed {records_processed} events and stored {records_stored} matching events"
            )
        else:
            task.last_attempt = started_at
            message = "No new events available"

        _add_history(
            session,
            task_id=task_id,
            started_at=started_at,
            status="SUCCESS",
            records_processed=records_processed,
            message=message,
        )
        session.commit()
        logger.info(
            "Saved execution history: task_id=%s status=SUCCESS records_processed=%s",
            task_id,
            records_processed,
        )
        return {
            "task_id": task_id,
            "status": "SUCCESS",
            "records_processed": records_processed,
            "records_stored": records_stored,
            "last_processed_cursor": task.last_processed_cursor or 0,
        }


def _record_failed_attempt(
    task_id: int,
    started_at: datetime,
    error: Exception,
) -> None:
    """Persist failure history without advancing the task cursor."""
    with SessionLocal() as session:
        task = session.get(ScheduledTask, task_id)
        if task is not None:
            task.last_attempt = started_at
        _add_history(
            session,
            task_id=task_id,
            started_at=started_at,
            status="FAILED",
            records_processed=0,
            message=f"{type(error).__name__}: {error}",
        )
        session.commit()
    logger.info("Recorded failed execution history: task_id=%s", task_id)


def _add_history(
    session: Session,
    *,
    task_id: int,
    started_at: datetime,
    status: str,
    records_processed: int,
    message: str,
) -> None:
    """Add an execution-history row to the caller's active transaction."""
    session.add(
        ExecutionHistory(
            task_id=task_id,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            status=status,
            records_processed=records_processed,
            message=message,
        )
    )


@celery_app.task(name="app.workers.tasks.process_scheduled_task")
def process_scheduled_task(task_id: int) -> dict[str, Any]:
    """Celery entry point that processes the supplied ScheduledTask ID."""
    settings = get_settings()
    base_url = settings.simulator_api_base_url.rstrip("/")
    logger.info(
        "Opening simulator API client: task_id=%s base_url=%s",
        task_id,
        base_url,
    )
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        return run_scheduled_task(task_id, client)
