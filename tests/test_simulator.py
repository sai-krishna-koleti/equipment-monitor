"""Tests for simulator event generation, persistence, and HTTP download routes."""

import csv
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.router import api_router
from app.simulator.service import EVENT_CODES, MACHINE_IDS, SimulatorService, get_simulator_service


def test_simulator_cursors_resume_and_download_csv(tmp_path: Path) -> None:
    """Generated machine cursors persist and download snapshots contain CSV rows."""
    service = SimulatorService(tmp_path)
    first_cycle = service.generate_cycle()
    resumed_service = SimulatorService(tmp_path)
    second_cycle = resumed_service.generate_cycle()

    assert [event["cursor"] for event in first_cycle] == [1, 1, 1]
    assert [event["cursor"] for event in second_cycle] == [2, 2, 2]
    assert len(first_cycle) == len(second_cycle) == len(MACHINE_IDS)
    assert {
        event["event_code"] for event in first_cycle + second_cycle
    } <= set(EVENT_CODES)

    file_name, start_cursor, end_cursor = resumed_service.create_download(
        MACHINE_IDS[0],
        last_processed_cursor=0,
    )
    assert (start_cursor, end_cursor) == (1, 2)

    with resumed_service.get_download_file(file_name).open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:
        rows = list(csv.DictReader(file))
    assert [int(row["cursor"]) for row in rows] == [1, 2]


def test_simulator_download_api_returns_and_serves_snapshot(tmp_path: Path) -> None:
    """The API returns a usable download URL and safely serves the CSV file."""
    service = SimulatorService(tmp_path)
    service.generate_cycle()

    test_app = FastAPI()
    test_app.include_router(api_router)
    test_app.dependency_overrides[get_simulator_service] = lambda: service

    with TestClient(test_app) as client:
        response = client.post(
            "/v1/simulator/download",
            json={"machine_id": MACHINE_IDS[0], "last_processed_cursor": 0},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["machine_id"] == MACHINE_IDS[0]
        assert payload["start_cursor"] == payload["end_cursor"] == 1
        assert payload["file_name"].endswith(".csv")

        download_path = urlparse(payload["download_url"]).path
        csv_response = client.get(download_path)
        assert csv_response.status_code == 200
        assert csv_response.headers["content-type"].startswith("text/csv")
        assert csv_response.text.splitlines()[0] == "cursor,timestamp,event_code"

        source_log_response = client.get(
            f"/v1/simulator/files/{MACHINE_IDS[0]}.csv"
        )
        assert source_log_response.status_code == 404

        unsafe_response = client.get("/v1/simulator/files/..%2Foutside.csv")
        assert unsafe_response.status_code == 404


def test_download_api_returns_not_found_when_no_new_events(tmp_path: Path) -> None:
    """A download request with no newer cursor data returns a clear 404."""
    service = SimulatorService(tmp_path)
    test_app = FastAPI()
    test_app.include_router(api_router)
    test_app.dependency_overrides[get_simulator_service] = lambda: service

    with TestClient(test_app) as client:
        response = client.post(
            "/v1/simulator/download",
            json={"machine_id": MACHINE_IDS[0], "last_processed_cursor": 0},
        )
    assert response.status_code == 404
