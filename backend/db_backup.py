"""Real SQLite backup/restore, using SQLite's own online backup API.

This exists specifically for the migration governance contract described
in ``docs/future/CONTINUOUS_BUILDER_PHASE_2_SCHEMA.md``: before a new
schema migration is ever applied to a real (non-test) database, an
operator must take and verify a backup. ``backend.migrations.run_migrations``
enforces that this module was used -- see ``MigrationBackupRequiredError``
-- for any deployment running on Railway; it is opt-in everywhere else,
since local development and the test suite intentionally run migrations
against disposable databases with no backup step.
"""

import sqlite3
from pathlib import Path
from typing import Union

DatabasePath = Union[str, Path]


class BackupError(RuntimeError):
    """Raised when a SQLite backup or restore cannot be proven safe."""


def create_sqlite_backup(
    source_path: DatabasePath, backup_path: DatabasePath,
) -> Path:
    """Take a consistent SQLite backup using the online backup API.

    Unlike a plain file copy, ``sqlite3.Connection.backup`` is safe to
    run against a live, open database (it uses SQLite's own page-level
    backup API rather than reading the file out from under a writer).
    """
    source = Path(source_path)
    destination = Path(backup_path)
    if not source.is_file():
        raise BackupError("backup source database does not exist")
    if destination.exists():
        raise BackupError("backup destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source)
    try:
        destination_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(destination_connection)
            destination_connection.commit()
        finally:
            destination_connection.close()
    finally:
        source_connection.close()
    verify_sqlite_backup(source, destination)
    return destination


def verify_sqlite_backup(
    source_path: DatabasePath, backup_path: DatabasePath,
) -> None:
    """Prove a backup is a usable, structurally intact SQLite database
    whose table set and row counts match the source at backup time."""
    source_connection = sqlite3.connect(Path(source_path))
    try:
        integrity = source_connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        if integrity != "ok":
            raise BackupError(f"backup source database is corrupt: {integrity}")
        source_tables = _table_row_counts(source_connection)
    finally:
        source_connection.close()

    backup_connection = sqlite3.connect(Path(backup_path))
    try:
        integrity = backup_connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        if integrity != "ok":
            raise BackupError(f"backup database is corrupt: {integrity}")
        backup_tables = _table_row_counts(backup_connection)
    finally:
        backup_connection.close()

    if source_tables != backup_tables:
        raise BackupError(
            "backup does not match source: table/row counts differ"
        )


def restore_sqlite_backup(
    backup_path: DatabasePath, restore_to_path: DatabasePath,
) -> Path:
    """Restore a verified backup onto a fresh destination path.

    Refuses to overwrite an existing file -- restoring in place onto a
    live database is an operator decision (stop writers, move the
    current file aside, then restore), not something this function does
    silently.
    """
    backup = Path(backup_path)
    destination = Path(restore_to_path)
    if not backup.is_file():
        raise BackupError("backup file does not exist")
    if destination.exists():
        raise BackupError("restore destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup_connection = sqlite3.connect(backup)
    try:
        restored_connection = sqlite3.connect(destination)
        try:
            backup_connection.backup(restored_connection)
            restored_connection.commit()
        finally:
            restored_connection.close()
    finally:
        backup_connection.close()
    verify_sqlite_backup(backup, destination)
    return destination


def _table_row_counts(connection: sqlite3.Connection) -> dict:
    tables = [
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    return {
        table: connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in tables
    }
