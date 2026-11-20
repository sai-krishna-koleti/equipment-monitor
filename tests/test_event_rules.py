"""API tests for event rule CRUD operations and status codes."""

from collections.abc import Generator

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


def test_event_rule_create_list_and_delete(client: TestClient) -> None:
    """The event rule endpoints create, list, and delete records."""
    create_response = client.post(
        "/v1/event-codes",
        json={"event_code": "TEMP_HIGH", "description": "High temperature"},
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["event_code"] == "TEMP_HIGH"
    assert created["description"] == "High temperature"
    assert created["id"] > 0
    assert "created_at" in created

    list_response = client.get("/v1/event-codes")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [created["id"]]

    delete_response = client.delete(f"/v1/event-codes/{created['id']}")
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert client.get("/v1/event-codes").json() == []


def test_duplicate_event_code_returns_conflict(client: TestClient) -> None:
    """Duplicate event codes return HTTP 409 instead of an unhandled DB error."""
    payload = {"event_code": "FLOW_LOW", "description": "Low flow"}
    assert client.post("/v1/event-codes", json=payload).status_code == 201

    duplicate_response = client.post("/v1/event-codes", json=payload)
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"] == "event_code already exists"


def test_invalid_event_rule_payload_returns_unprocessable_entity(
    client: TestClient,
) -> None:
    """Empty event codes are rejected by request schema validation."""
    response = client.post(
        "/v1/event-codes",
        json={"event_code": "", "description": "Missing event code"},
    )
    assert response.status_code == 422


def test_deleting_missing_event_rule_returns_not_found(client: TestClient) -> None:
    """Deleting an unknown primary key returns HTTP 404."""
    response = client.delete("/v1/event-codes/99")
    assert response.status_code == 404
