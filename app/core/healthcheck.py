"""Container health-check commands for API, Celery worker, and Celery Beat."""

import argparse
import logging
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from celery.exceptions import CeleryError
from kombu.exceptions import KombuError
from redis import Redis
from redis.exceptions import RedisError

from app.core.celery_app import celery_app
from app.core.config import get_settings

logger = logging.getLogger(__name__)
BEAT_HEARTBEAT_FILE = Path(get_settings().celery_beat_heartbeat_file)
BEAT_HEARTBEAT_MAX_AGE_SECONDS = 10


def check_api() -> None:
    """Fail unless the API readiness endpoint responds successfully."""
    with urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
        if response.status != 200:
            raise HealthcheckError("API readiness endpoint returned a non-200 status")


def check_worker() -> None:
    """Fail unless at least one Celery worker replies to a broker ping."""
    replies = celery_app.control.inspect(timeout=3).ping()
    if not replies:
        raise HealthcheckError("No Celery worker replied to ping")


def check_beat() -> None:
    """Fail unless Beat is ticking and Redis is reachable."""
    heartbeat_age = time.time() - BEAT_HEARTBEAT_FILE.stat().st_mtime
    if heartbeat_age > BEAT_HEARTBEAT_MAX_AGE_SECONDS:
        raise HealthcheckError("Celery Beat heartbeat is stale")

    client = Redis.from_url(
        get_settings().redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        client.ping()
    finally:
        client.close()


class HealthcheckError(Exception):
    """Raised when a container health check detects an unavailable service."""


def main() -> None:
    """Run the selected service health check and exit nonzero on failure."""
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=("api", "worker", "beat"))
    service = parser.parse_args().service
    check = {
        "api": check_api,
        "worker": check_worker,
        "beat": check_beat,
    }[service]
    try:
        check()
    except (
        HealthcheckError,
        URLError,
        OSError,
        RedisError,
        CeleryError,
        KombuError,
    ):
        logger.exception("Health check failed: service=%s", service)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
