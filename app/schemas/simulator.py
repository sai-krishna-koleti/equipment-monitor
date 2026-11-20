"""Pydantic API schemas for simulator event download requests and responses."""

from typing import Literal

from pydantic import BaseModel, Field

MachineId = Literal["ETCH-001", "ETCH-002", "ETCH-003"]


class SimulatorDownloadRequest(BaseModel):
    """Request a CSV containing events newer than a machine cursor."""

    machine_id: MachineId
    last_processed_cursor: int = Field(ge=0)


class SimulatorDownloadResponse(BaseModel):
    """Metadata and endpoint URL for a generated event CSV snapshot."""

    machine_id: MachineId
    file_name: str
    start_cursor: int
    end_cursor: int
    download_url: str
