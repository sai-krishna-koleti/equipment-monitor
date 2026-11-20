"""API tests for scheduled task metadata and lifecycle transitions."""

from collections.abc import Generator
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.core.database import get_db
from app.models import Base


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Provide an isolated in-memory database for each API test."""
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

    try:
        with TestClient(test_app) as test_client:
            yield test_client
    finally:
        test_app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_task_lifecycle_and_soft_stop(client: TestClient) -> None:
    """Task lifecycle endpoints persist status and soft-stop instead of deleting."""
    response = client.post(
        "/v1/tasks",
        json={
            "machine_id": "ETCH-001",
            "interval_seconds": 60,
            "start_at": "2026-01-01T00:00:00Z",
            "stop_at": None,
        },
    )
    assert response.status_code == 201
    task = response.json()
    task_id = task["id"]
    assert task["status"] == "ACTIVE"
    assert task["interval_seconds"] == 60
    assert task["next_attempt"] is not None
    assert task["last_attempt"] is None
    assert task["last_processed_cursor"] is None

    list_response = client.get("/v1/tasks")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [task_id]

    pause_response = client.put(f"/v1/tasks/{task_id}/pause")
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "PAUSED"
    assert client.put(f"/v1/tasks/{task_id}/pause").json()["status"] == "PAUSED"

    resume_response = client.put(f"/v1/tasks/{task_id}/resume")
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "ACTIVE"
    assert datetime.fromisoformat(resume_response.json()["next_attempt"]) > datetime.now()

    delete_response = client.delete(f"/v1/tasks/{task_id}")
    assert delete_response.status_code == 204
    assert delete_response.content == b""

    stored_tasks = client.get("/v1/tasks").json()
    assert len(stored_tasks) == 1
    assert stored_tasks[0]["id"] == task_id
    assert stored_tasks[0]["status"] == "STOPPED"
    assert stored_tasks[0]["next_attempt"] is None
    assert client.put(f"/v1/tasks/{task_id}/resume").status_code == 409
    assert client.put(f"/v1/tasks/{task_id}/pause").status_code == 409


def test_task_creation_validates_positive_interval(client: TestClient) -> None:
    """A non-positive task interval is rejected before persistence."""
    response = client.post(
        "/v1/tasks",
        json={
            "machine_id": "ETCH-001",
            "interval_seconds": 0,
            "start_at": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422
    assert client.get("/v1/tasks").json() == []


def test_task_actions_return_not_found_for_unknown_id(client: TestClient) -> None:
    """Pause, resume, and stop return 404 for an unknown task."""
    assert client.put("/v1/tasks/99/pause").status_code == 404
    assert client.put("/v1/tasks/99/resume").status_code == 404
    assert client.delete("/v1/tasks/99").status_code == 404
