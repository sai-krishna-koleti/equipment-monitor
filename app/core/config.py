"""Environment-backed application settings loaded with Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from tempfile import gettempdir

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration sourced from environment variables."""

    app_name: str = "Equipment Event Monitoring System"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    database_url: str = "sqlite:///./equipment_events.db"
    redis_url: str = "redis://localhost:6379/0"
    celery_result_backend_url: str = "redis://localhost:6379/1"
    simulator_api_base_url: str = "http://localhost:8000"
    simulator_interval_seconds: float = Field(default=3.0, gt=0)
    celery_beat_heartbeat_file: str = str(
        Path(gettempdir()) / "celery-beat-heartbeat"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings instance for application dependency wiring."""
    return Settings()
