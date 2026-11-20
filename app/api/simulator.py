"""HTTP endpoints for requesting and downloading simulator event CSV files."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from app.schemas.simulator import (
    SimulatorDownloadRequest,
    SimulatorDownloadResponse,
)
from app.simulator.service import SimulatorService, get_simulator_service

router = APIRouter()
Simulator = Annotated[SimulatorService, Depends(get_simulator_service)]


@router.post("/download", response_model=SimulatorDownloadResponse)
def request_event_download(
    payload: SimulatorDownloadRequest,
    request: Request,
    simulator: Simulator,
) -> SimulatorDownloadResponse:
    """Create a CSV snapshot containing events after the supplied cursor."""
    try:
        file_name, start_cursor, end_cursor = simulator.create_download(
            payload.machine_id,
            payload.last_processed_cursor,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return SimulatorDownloadResponse(
        machine_id=payload.machine_id,
        file_name=file_name,
        start_cursor=start_cursor,
        end_cursor=end_cursor,
        download_url=str(
            request.url_for("download_simulator_file", file_name=file_name)
        ),
    )


@router.get("/files/{file_name}", name="download_simulator_file")
def download_simulator_file(
    file_name: str,
    simulator: Simulator,
) -> FileResponse:
    """Return a previously generated CSV snapshot."""
    try:
        path = simulator.get_download_file(file_name)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Simulator file not found") from error

    return FileResponse(
        path,
        media_type="text/csv",
        filename=file_name,
    )
