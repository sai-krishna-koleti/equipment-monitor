"""Smoke tests for application construction and configuration."""

from app.main import app


def test_application_uses_configured_title() -> None:
    """The FastAPI application exposes the configured project title."""
    assert app.title == "Equipment Event Monitoring System"
