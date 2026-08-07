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

REQUIRED_COLUMNS = {
    "projects": {"id", "name", "description", "created_at"},
    "memories": {
        "id",
        "content",
        "project",
        "memory_type",
        "created_at",
        "status",
        "updated_at",
        "replaces_memory_id",
        "superseded_by_id",
    },
    "conversations": {"id", "title", "project", "created_at", "updated_at"},
    "messages": {
        "id",
        "conversation_id",
        "role",
        "content",
        "provider",
        "model",
        "created_at",
    },
    "runs": {
        "id",
        "run_type",
        "status",
        "conversation_id",
        "user_message_id",
        "assistant_message_id",
        "provider",
        "model",
        "started_at",
        "finished_at",
        "duration_ms",
        "error_class",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "data_exposure",
    },
    "schema_migrations": {"version", "name", "applied_at"},
}


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


def _migration_002_memory_lifecycle(connection: sqlite3.Connection) -> None:
    """Add correction and archival lifecycle fields without replacing rows."""
    existing_columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(memories)").fetchall()
    }

    if "status" not in existing_columns:
        connection.execute(
            """
            ALTER TABLE memories
            ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active', 'superseded', 'archived'))
            """
        )
    if "updated_at" not in existing_columns:
        connection.execute("ALTER TABLE memories ADD COLUMN updated_at TEXT")
    if "replaces_memory_id" not in existing_columns:
        connection.execute("ALTER TABLE memories ADD COLUMN replaces_memory_id TEXT")
    if "superseded_by_id" not in existing_columns:
        connection.execute("ALTER TABLE memories ADD COLUMN superseded_by_id TEXT")

    connection.execute(
        """
        UPDATE memories
        SET status = 'active'
        WHERE status IS NULL OR status = ''
        """
    )
    connection.execute(
        """
        UPDATE memories
        SET updated_at = created_at
        WHERE updated_at IS NULL OR updated_at = ''
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memories_status_created_at
        ON memories (status, created_at DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memories_superseded_by_id
        ON memories (superseded_by_id)
        """
    )


def _migration_003_model_runs(connection: sqlite3.Connection) -> None:
    """Add append-oriented execution records for model and future tool attempts."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            run_type TEXT NOT NULL CHECK (run_type IN ('model', 'tool')),
            status TEXT NOT NULL CHECK (status IN ('started', 'succeeded', 'failed')),
            conversation_id TEXT,
            user_message_id TEXT,
            assistant_message_id TEXT,
            provider TEXT,
            model TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
            error_class TEXT,
            input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
            output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
            cost_usd REAL CHECK (cost_usd IS NULL OR cost_usd >= 0),
            data_exposure TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_runs_started_at
        ON runs (started_at DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_runs_conversation_id_started_at
        ON runs (conversation_id, started_at DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_runs_status_started_at
        ON runs (status, started_at DESC)
        """
    )


MIGRATIONS = (
    Migration(1, "initial_schema", _migration_001_initial_schema),
    Migration(2, "memory_lifecycle", _migration_002_memory_lifecycle),
    Migration(3, "model_runs", _migration_003_model_runs),
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


def _verify_schema(connection: sqlite3.Connection) -> None:
    """Reject a partially compatible schema before recording success."""
    for table, required_columns in REQUIRED_COLUMNS.items():
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        actual_columns = {str(row["name"]) for row in rows}
        missing_columns = required_columns - actual_columns
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise RuntimeError(
                f"Database schema is incompatible: table {table} "
                f"is missing required columns: {missing}"
            )

    foreign_keys = connection.execute("PRAGMA foreign_key_list(messages)").fetchall()
    has_message_conversation_key = any(
        str(row["table"]) == "conversations"
        and str(row["from"]) == "conversation_id"
        and str(row["to"]) == "id"
        for row in foreign_keys
    )
    if not has_message_conversation_key:
        raise RuntimeError(
            "Database schema is incompatible: messages.conversation_id "
            "must reference conversations.id"
        )

    invalid_memory_status = connection.execute(
        """
        SELECT status
        FROM memories
        WHERE status NOT IN ('active', 'superseded', 'archived')
        LIMIT 1
        """
    ).fetchone()
    if invalid_memory_status is not None:
        raise RuntimeError(
            "Database schema is incompatible: memories.status contains "
            f"unsupported value {invalid_memory_status['status']!r}"
        )

    invalid_run = connection.execute(
        """
        SELECT run_type, status
        FROM runs
        WHERE run_type NOT IN ('model', 'tool')
           OR status NOT IN ('started', 'succeeded', 'failed')
        LIMIT 1
        """
    ).fetchone()
    if invalid_run is not None:
        raise RuntimeError(
            "Database schema is incompatible: runs contains unsupported run type/status"
        )


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

        _verify_schema(connection)
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
