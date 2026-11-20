"""API tests for processed event filtering, pagination, and total counts."""

from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.core.database import get_db
from app.models import Base, EventRule, ProcessedEvent, ScheduledTask
from app.models.scheduled_task import TaskStatus


@pytest.fixture
def event_client() -> Generator[TestClient, None, None]:
    """Provide an isolated database populated with processed event records."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    test_app = FastAPI()
    test_app.include_router(api_router)
    test_app.dependency_overrides[get_db] = override_get_db

    with Session(engine) as session:
        session.add_all(
            [
                EventRule(event_code="TEMP_HIGH", description="High temperature"),
                EventRule(event_code="FLOW_LOW", description="Low flow"),
            ]
        )
        task = ScheduledTask(
            machine_id="ETCH-001",
            status=TaskStatus.ACTIVE,
            interval_seconds=60,
            start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        other_task = ScheduledTask(
            machine_id="ETCH-002",
            status=TaskStatus.ACTIVE,
            interval_seconds=60,
            start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session.add_all([task, other_task])
        session.flush()

        records = [
            ("ETCH-001", 1, 1, "TEMP_HIGH", "HIGH", task.id),
            ("ETCH-001", 2, 2, "TEMP_HIGH", "HIGH", task.id),
            ("ETCH-001", 3, 3, "FLOW_LOW", "LOW", task.id),
            ("ETCH-002", 4, 4, "TEMP_HIGH", "HIGH", other_task.id),
            ("ETCH-001", 5, 5, "TEMP_HIGH", "HIGH", task.id),
        ]
        for machine_id, cursor, hour, event_code, severity, task_id in records:
            session.add(
                ProcessedEvent(
                    machine_id=machine_id,
                    cursor=cursor,
                    timestamp=datetime(2026, 1, 1, hour, tzinfo=timezone.utc),
                    event_code=event_code,
                    severity=severity,
                    task_id=task_id,
                )
            )
        session.commit()

    try:
        with TestClient(test_app) as client:
            yield client
    finally:
        test_app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_events_filters_pagination_and_total_count(event_client: TestClient) -> None:
    """Combined filters constrain count and page, which is timestamp-descending."""
    params = {
        "machine_id": "ETCH-001",
        "event_code": "TEMP_HIGH",
        "severity": "HIGH",
        "start_time": "2026-01-01T02:00:00Z",
        "end_time": "2026-01-01T05:00:00Z",
        "page_size": 1,
    }

    first_page = event_client.get("/v1/events", params={**params, "page": 1})
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["total_count"] == 2
    assert first_payload["page"] == 1
    assert first_payload["page_size"] == 1
    assert [item["cursor"] for item in first_payload["items"]] == [5]

    second_page = event_client.get("/v1/events", params={**params, "page": 2})
    assert second_page.status_code == 200
    assert second_page.json()["total_count"] == 2
    assert [item["cursor"] for item in second_page.json()["items"]] == [2]


def test_events_default_sort_is_timestamp_descending(event_client: TestClient) -> None:
    """Unfiltered results are ordered newest first and paged with defaults."""
    response = event_client.get("/v1/events", params={"page_size": 2})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 5
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert [item["cursor"] for item in payload["items"]] == [5, 4]


def test_events_reject_invalid_time_range_and_page_size(
    event_client: TestClient,
) -> None:
    """Invalid ranges and oversized pages are rejected during request handling."""
    invalid_range = event_client.get(
        "/v1/events",
        params={
            "start_time": "2026-01-02T00:00:00Z",
            "end_time": "2026-01-01T00:00:00Z",
        },
    )
    oversized_page = event_client.get("/v1/events", params={"page_size": 101})
    assert invalid_range.status_code == 422
    assert oversized_page.status_code == 422
