"""Real SQLite backup/restore proof (isolated, disposable databases only).

Uses genuine files on disk and SQLite's own online backup API -- not a
mock -- so a bug in the backup/restore round trip (missed table, wrong
row count, corrupt destination file) would actually be caught here.
"""

import sqlite3

import pytest

from backend.db_backup import (
    BackupError,
    create_sqlite_backup,
    restore_sqlite_backup,
    verify_sqlite_backup,
)
from backend.migrations import run_migrations
from backend.continuous_builder.leases import create_attempt


def _seeded_database(tmp_path):
    path = tmp_path / "source.db"
    run_migrations(path)
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO builder_blueprints VALUES (?,?,?,?,?,?,?,?)",
        ("bp", "v1", "d" * 64, "{}", "a", "human", 0, "2026-01-01T00:00:00+00:00"),
    )
    connection.execute(
        "INSERT INTO builder_slices VALUES (?,?,?,?,?)",
        ("bp", "v1", "CB-001", "1", "{}"),
    )
    connection.commit()
    connection.close()
    return path


def test_backup_is_byte_identical_in_table_and_row_shape(tmp_path):
    source = _seeded_database(tmp_path)
    backup = tmp_path / "backup.db"
    result = create_sqlite_backup(source, backup)
    assert result == backup
    assert backup.is_file()
    verify_sqlite_backup(source, backup)


def test_backup_survives_further_writes_to_the_source(tmp_path):
    source = _seeded_database(tmp_path)
    backup = tmp_path / "backup.db"
    create_sqlite_backup(source, backup)
    create_attempt(
        source, "attempt-1", "bp", "v1", "CB-001", "1", "owner-1",
        "2026-01-01T00:00:01+00:00",
    )
    backup_connection = sqlite3.connect(backup)
    count = backup_connection.execute(
        "SELECT count(*) FROM builder_attempts"
    ).fetchone()[0]
    backup_connection.close()
    assert count == 0


def test_restore_recreates_a_working_database_from_backup(tmp_path):
    source = _seeded_database(tmp_path)
    backup = tmp_path / "backup.db"
    create_sqlite_backup(source, backup)
    restored = tmp_path / "restored.db"
    restore_sqlite_backup(backup, restored)
    connection = sqlite3.connect(restored)
    try:
        row = connection.execute(
            "SELECT blueprint_id, blueprint_version FROM builder_blueprints"
        ).fetchone()
        slice_row = connection.execute(
            "SELECT slice_id FROM builder_slices"
        ).fetchone()
    finally:
        connection.close()
    assert row == ("bp", "v1")
    assert slice_row == ("CB-001",)
    create_attempt(
        restored, "attempt-1", "bp", "v1", "CB-001", "1", "owner-1",
        "2026-01-01T00:00:01+00:00",
    )


def test_backup_refuses_missing_source_and_existing_destination(tmp_path):
    with pytest.raises(BackupError, match="does not exist"):
        create_sqlite_backup(tmp_path / "missing.db", tmp_path / "out.db")
    source = _seeded_database(tmp_path)
    existing = tmp_path / "already-there.db"
    existing.write_text("not a real backup")
    with pytest.raises(BackupError, match="already exists"):
        create_sqlite_backup(source, existing)


def test_verify_detects_a_tampered_backup_missing_rows(tmp_path):
    source = _seeded_database(tmp_path)
    backup = tmp_path / "backup.db"
    create_sqlite_backup(source, backup)
    connection = sqlite3.connect(backup)
    connection.execute("DELETE FROM builder_slices")
    connection.commit()
    connection.close()
    with pytest.raises(BackupError, match="table/row counts differ"):
        verify_sqlite_backup(source, backup)
