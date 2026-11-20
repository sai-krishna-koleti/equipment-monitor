"""Aggregate versioned API routes."""

from fastapi import APIRouter

from app.api.event_rules import router as event_rules_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.scheduled_tasks import router as scheduled_tasks_router
from app.api.simulator import router as simulator_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(event_rules_router, prefix="/v1/event-codes")
api_router.include_router(events_router, prefix="/v1/events")
api_router.include_router(scheduled_tasks_router, prefix="/v1/tasks")
api_router.include_router(simulator_router, prefix="/v1/simulator")
