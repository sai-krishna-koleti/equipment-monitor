"""Pydantic request and response schemas for event rule endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EventRuleCreate(BaseModel):
    """Validated request body for registering an event code."""

    event_code: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)


class EventRuleResponse(BaseModel):
    """Event rule representation returned by the API."""

    id: int
    event_code: str
    description: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
