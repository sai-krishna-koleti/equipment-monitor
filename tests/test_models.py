"""Tests for ORM table metadata and event idempotency constraints."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import _configure_sqlite_connection
from app.models import Base, EventRule, ProcessedEvent, ScheduledTask


def test_sqlite_connections_enforce_foreign_keys_and_wait_for_locks() -> None:
    """The SQLite connection setup enables foreign keys and a lock timeout."""
    engine = create_engine("sqlite://")
    from sqlalchemy import event

    event.listen(engine, "connect", _configure_sqlite_connection)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 30000
    finally:
        engine.dispose()


def test_all_models_are_registered_in_migration_metadata() -> None:
    """Importing the model package registers every model table on Base.metadata."""
    assert set(Base.metadata.tables) == {
        "event_rules",
        "scheduled_tasks",
        "processed_events",
        "execution_history",
    }


def test_models_create_tables_with_unique_machine_cursor_constraint() -> None:
    """The composite constraint rejects duplicate source cursors per machine."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    try:
        table_names = set(inspect(engine).get_table_names())
        assert table_names == set(Base.metadata.tables)

        with Session(engine) as session:
            session.add(EventRule(event_code="TEMP_HIGH", description="High temperature"))
            task = ScheduledTask(
                machine_id="machine-1",
                status="ACTIVE",
                interval_seconds=60,
                start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            session.add(task)
            session.flush()
            session.add(
                ProcessedEvent(
                    machine_id="machine-1",
                    cursor=1,
                    timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    event_code="TEMP_HIGH",
                    severity="warning",
                    task_id=task.id,
                )
            )
            session.commit()

            session.add(
                ProcessedEvent(
                    machine_id="machine-1",
                    cursor=1,
                    timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    event_code="TEMP_HIGH",
                    severity="warning",
                    task_id=task.id,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
