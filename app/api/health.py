"""Readiness endpoint that verifies the API database and Redis dependencies."""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import engine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", include_in_schema=False)
def readiness_check(request: Request) -> dict[str, str]:
    """Return ready only when both the configured database and Redis are available."""
    simulator_task = getattr(request.app.state, "simulator_task", None)
    if simulator_task is not None and simulator_task.done():
        if simulator_task.cancelled():
            logger.error("Readiness check failed: simulator task was cancelled")
        else:
            error = simulator_task.exception()
            logger.error(
                "Readiness check failed: simulator task stopped",
                exc_info=(type(error), error, error.__traceback__) if error else None,
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Simulator is unavailable",
        )

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.exception("Readiness check failed: database unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from error

    client = Redis.from_url(
        get_settings().redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        client.ping()
    except RedisError as error:
        logger.exception("Readiness check failed: Redis unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is unavailable",
        ) from error
    finally:
        client.close()

    return {"status": "ok"}
