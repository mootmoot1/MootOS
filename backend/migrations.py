"""Versioned SQLite schema migrations for MootOS."""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Union

from backend.db import connect


DatabasePath = Union[str, Path]
MigrationFunction = Callable[[sqlite3.Connection], None]

DEFAULT_PROJECTS = (
    ("MootOS", "Development and planning for the MootOS personal AI system."),
    ("Studio", "Studio sessions, clients, engineering work, and business operations."),
    ("Social Media", "Content ideas, publishing plans, and audience growth."),
    ("Cars", "Vehicle maintenance, repairs, and automotive projects."),
    ("Personal", "Personal information that does not belong to another project."),
)


@dataclass(frozen=True)
class Migration:
    """One ordered database migration."""

    version: int
    name: str
    apply: MigrationFunction


def _migration_001_initial_schema(connection: sqlite3.Connection) -> None:
    """Create the Version 0.1 schema without replacing existing data."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            description TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            project TEXT,
            memory_type TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            project TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
        ON messages (conversation_id)
        """
    )

    created_at = datetime.now(timezone.utc).isoformat()
    connection.executemany(
        """
        INSERT OR IGNORE INTO projects (id, name, description, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            (str(uuid.uuid4()), name, description, created_at)
            for name, description in DEFAULT_PROJECTS
        ),
    )


MIGRATIONS = (
    Migration(1, "initial_schema", _migration_001_initial_schema),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _current_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
    ).fetchone()
    return int(row["version"])


def run_migrations(database_path: Optional[DatabasePath] = None) -> int:
    """Apply every unapplied migration in one serialized transaction."""
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_migration_table(connection)
        current_version = _current_schema_version(connection)
        if current_version > LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                "Database schema is newer than this MootOS build: "
                f"database={current_version}, supported={LATEST_SCHEMA_VERSION}"
            )

        for migration in MIGRATIONS:
            if migration.version <= current_version:
                continue

            expected_version = current_version + 1
            if migration.version != expected_version:
                raise RuntimeError(
                    "Database migration sequence is incomplete: "
                    f"expected version {expected_version}, found {migration.version}"
                )

            migration.apply(connection)
            connection.execute(
                """
                INSERT INTO schema_migrations (version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            current_version = migration.version

        connection.commit()
        return current_version
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(database_path: Optional[DatabasePath] = None) -> int:
    """Bring the database to the latest known schema version."""
    return run_migrations(database_path)


def get_schema_version(database_path: Optional[DatabasePath] = None) -> int:
    """Return the applied schema version, or zero for an uninitialized database."""
    connection = connect(database_path)
    try:
        row = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_migrations'
            """
        ).fetchone()
        if row is None:
            return 0
        return _current_schema_version(connection)
    finally:
        connection.close()
