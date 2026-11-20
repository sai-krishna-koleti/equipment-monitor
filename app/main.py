"""Application entry point and FastAPI application factory."""

import asyncio
from contextlib import asynccontextmanager, suppress
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.simulator.service import get_simulator_service


def create_app() -> FastAPI:
    """Create the configured FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        simulator = get_simulator_service()
        generator_task = asyncio.create_task(
            simulator.run_forever(settings.simulator_interval_seconds),
            name="equipment-event-simulator",
        )
        application.state.simulator_task = generator_task
        try:
            yield
        finally:
            application.state.simulator_task = None
            generator_task.cancel()
            with suppress(asyncio.CancelledError):
                await generator_task

    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )
    application.include_router(api_router)
    return application


app = create_app()
