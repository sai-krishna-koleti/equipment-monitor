"""Tests for the API readiness endpoint without external dependencies."""

from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.api.health import router as health_router
from app.api import health


class MockConnection:
    """Minimal SQLAlchemy connection test double."""

    def __enter__(self) -> MockConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: object) -> None:
        return None


class MockEngine:
    """Provide a successful database connection for health tests."""

    def connect(self) -> MockConnection:
        return MockConnection()


class MockRedis:
    """Provide a configurable Redis ping response for health tests."""

    def __init__(self, *, failure: bool = False) -> None:
        self.failure = failure

    def ping(self) -> bool:
        if self.failure:
            raise RedisError("Redis unavailable")
        return True

    def close(self) -> None:
        return None


class FailedSimulatorTask:
    """Represent a simulator task that stopped with an exception."""

    def done(self) -> bool:
        return True

    def cancelled(self) -> bool:
        return False

    def exception(self) -> RuntimeError:
        return RuntimeError("simulator failed")


@pytest.fixture
def health_client() -> Generator[TestClient, None, None]:
    """Create a small test app around the readiness endpoint."""
    app = FastAPI()
    app.include_router(health_router)
    with TestClient(app) as client:
        yield client


def test_health_returns_ready_when_dependencies_are_available(
    health_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint returns success after database and Redis checks pass."""
    monkeypatch.setattr(health, "engine", MockEngine())
    monkeypatch.setattr(
        health.Redis,
        "from_url",
        lambda *args, **kwargs: MockRedis(),
    )

    response = health_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_returns_unavailable_when_redis_is_down(
    health_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint returns 503 when Redis cannot be reached."""
    monkeypatch.setattr(health, "engine", MockEngine())
    monkeypatch.setattr(
        health.Redis,
        "from_url",
        lambda *args, **kwargs: MockRedis(failure=True),
    )

    response = health_client.get("/health")
    assert response.status_code == 503
    assert response.json()["detail"] == "Redis is unavailable"


def test_health_returns_unavailable_when_simulator_stops(
    health_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed simulator background task makes the API unready."""
    monkeypatch.setattr(health, "engine", MockEngine())
    health_client.app.state.simulator_task = FailedSimulatorTask()

    response = health_client.get("/health")
    assert response.status_code == 503
    assert response.json()["detail"] == "Simulator is unavailable"
