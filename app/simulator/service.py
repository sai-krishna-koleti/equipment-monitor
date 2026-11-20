"""Thread-safe event generation, CSV persistence, and cursor-based downloads."""

import asyncio
import csv
import logging
import os
import random
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import RLock
from uuid import uuid4

MACHINE_IDS = ("ETCH-001", "ETCH-002", "ETCH-003")
EVENT_CODES = (
    "TEMP_HIGH",
    "FLOW_LOW",
    "PRESSURE_HIGH",
    "MOTOR_FAILURE",
    "POWER_FAILURE",
    "VACUUM_LOW",
)
CSV_FIELDS = ("cursor", "timestamp", "event_code")
SNAPSHOT_FILE_PATTERN = re.compile(
    r"(?:ETCH-001|ETCH-002|ETCH-003)_after_[0-9]+_[0-9]+_[0-9a-f]{32}\.csv"
)
logger = logging.getLogger(__name__)


class SimulatorService:
    """Generate per-machine events and persist them as append-only CSV logs."""

    def __init__(self, files_dir: Path | None = None) -> None:
        """Create the storage directory and resume cursors from existing logs."""
        self.files_dir = (
            files_dir if files_dir is not None else Path(__file__).parent / "files"
        ).resolve()
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._cursors: dict[str, int] = {}

        for machine_id in MACHINE_IDS:
            file_path = self._machine_file(machine_id)
            if not file_path.exists():
                with file_path.open("w", newline="", encoding="utf-8") as file:
                    csv.writer(file).writerow(CSV_FIELDS)
            self._cursors[machine_id] = self._read_last_cursor(file_path)

    def generate_cycle(self) -> list[dict[str, str | int]]:
        """Generate and persist one event for each configured machine."""
        with self._lock:
            return [
                self._generate_event_unlocked(machine_id)
                for machine_id in MACHINE_IDS
            ]

    async def run_forever(self, interval_seconds: float) -> None:
        """Generate events continuously until the application cancels this task."""
        while True:
            await asyncio.sleep(interval_seconds)
            await asyncio.to_thread(self.generate_cycle)
            logger.info("Generated one simulator event per machine")

    def create_download(
        self,
        machine_id: str,
        last_processed_cursor: int,
    ) -> tuple[str, int, int]:
        """Create a CSV snapshot of a machine's events after the given cursor."""
        if machine_id not in MACHINE_IDS:
            raise LookupError(f"Unknown machine: {machine_id}")
        if last_processed_cursor < 0:
            raise ValueError("last_processed_cursor must be non-negative")

        with self._lock:
            machine_file = self._machine_file(machine_id)
            with machine_file.open("r", newline="", encoding="utf-8") as file:
                events = [
                    row
                    for row in csv.DictReader(file)
                    if int(row["cursor"]) > last_processed_cursor
                ]

            if not events:
                raise LookupError("No events are available after the supplied cursor")

            start_cursor = int(events[0]["cursor"])
            end_cursor = int(events[-1]["cursor"])
            file_name = (
                f"{machine_id}_after_{last_processed_cursor}_{end_cursor}_"
                f"{uuid4().hex}.csv"
            )
            target_path = self.files_dir / file_name
            temporary_path = self.files_dir / f".{uuid4().hex}.tmp"
            try:
                with temporary_path.open("w", newline="", encoding="utf-8") as file:
                    writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
                    writer.writeheader()
                    writer.writerows(events)
                os.replace(temporary_path, target_path)
            finally:
                temporary_path.unlink(missing_ok=True)

            return file_name, start_cursor, end_cursor

    def get_download_file(self, file_name: str) -> Path:
        """Resolve an existing generated snapshot under the storage directory."""
        if SNAPSHOT_FILE_PATTERN.fullmatch(file_name) is None:
            raise FileNotFoundError(file_name)

        candidate = (self.files_dir / file_name).resolve()
        if (
            candidate.parent != self.files_dir
            or candidate.suffix.lower() != ".csv"
            or not candidate.is_file()
        ):
            raise FileNotFoundError(file_name)
        return candidate

    def _generate_event_unlocked(self, machine_id: str) -> dict[str, str | int]:
        cursor = self._cursors[machine_id] + 1
        timestamp = datetime.now(timezone.utc).isoformat()
        event_code = random.choice(EVENT_CODES)
        event = {
            "cursor": cursor,
            "timestamp": timestamp,
            "event_code": event_code,
        }

        with self._machine_file(machine_id).open(
            "a",
            newline="",
            encoding="utf-8",
        ) as file:
            csv.DictWriter(file, fieldnames=CSV_FIELDS).writerow(event)
        self._cursors[machine_id] = cursor
        return event

    def _machine_file(self, machine_id: str) -> Path:
        """Return the canonical append-only CSV path for a configured machine."""
        return self.files_dir / f"{machine_id}.csv"

    @staticmethod
    def _read_last_cursor(file_path: Path) -> int:
        """Read and validate the final cursor stored in a machine CSV."""
        last_cursor = 0
        with file_path.open("r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != list(CSV_FIELDS):
                raise ValueError(f"Invalid simulator CSV header in {file_path}")
            for row in reader:
                cursor = int(row["cursor"])
                if cursor <= last_cursor:
                    raise ValueError(f"Non-increasing cursor in {file_path}")
                last_cursor = cursor
        return last_cursor


@lru_cache
def get_simulator_service() -> SimulatorService:
    """Return the process-wide simulator service used by routes and lifespan."""
    return SimulatorService()
