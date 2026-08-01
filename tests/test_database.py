"""Tests for centralized SQLite configuration and migrations."""

import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from backend.db import (
    SQLITE_BUSY_TIMEOUT_MS,
    connect,
    database_connection,
)
from backend.migrations import (
    LATEST_SCHEMA_VERSION,
    get_schema_version,
    initialize_database,
)


def test_connection_applies_sqlite_safety_pragmas(tmp_path):
    database_path = tmp_path / "configured.db"
    initialize_database(database_path)

    connection = connect(database_path)
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert (
            connection.execute("PRAGMA busy_timeout").fetchone()[0]
            == SQLITE_BUSY_TIMEOUT_MS
        )
    finally:
        connection.close()


def test_clean_database_reaches_latest_schema(tmp_path):
    database_path = tmp_path / "clean.db"

    assert get_schema_version(database_path) == 0
    assert initialize_database(database_path) == LATEST_SCHEMA_VERSION
    assert get_schema_version(database_path) == LATEST_SCHEMA_VERSION

    with database_connection(database_path) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {
        "schema_migrations",
        "projects",
        "memories",
        "conversations",
        "messages",
    }.issubset(tables)


def test_migration_adopts_existing_schema_without_losing_data(tmp_path):
    database_path = tmp_path / "legacy.db"
    memory_id = str(uuid.uuid4())

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE memories (
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
            INSERT INTO memories (id, content, project, memory_type, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                "Existing production memory",
                "MootOS",
                "project",
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    initialize_database(database_path)

    with database_connection(database_path) as connection:
        saved = connection.execute(
            """
            SELECT content, status, created_at, updated_at,
                   replaces_memory_id, superseded_by_id
            FROM memories
            WHERE id = ?
            """,
            (memory_id,),
        ).fetchone()

    assert saved["content"] == "Existing production memory"
    assert saved["status"] == "active"
    assert saved["updated_at"] == saved["created_at"]
    assert saved["replaces_memory_id"] is None
    assert saved["superseded_by_id"] is None
    assert get_schema_version(database_path) == LATEST_SCHEMA_VERSION


def test_memory_lifecycle_migration_preserves_existing_rows(tmp_path):
    database_path = tmp_path / "schema-one.db"
    memory_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                description TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                project TEXT,
                memory_type TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                project TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            """
        )
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, applied_at)
            VALUES (1, 'initial_schema', ?)
            """,
            (created_at,),
        )
        connection.execute(
            """
            INSERT INTO memories (id, content, project, memory_type, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (memory_id, "Keep this row", None, "test", created_at),
        )

    assert initialize_database(database_path) == 2

    with database_connection(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        indexes = {
            item["name"]
            for item in connection.execute("PRAGMA index_list(memories)").fetchall()
        }

    assert row["content"] == "Keep this row"
    assert row["status"] == "active"
    assert row["updated_at"] == created_at
    assert row["replaces_memory_id"] is None
    assert row["superseded_by_id"] is None
    assert "idx_memories_status_created_at" in indexes
    assert "idx_memories_superseded_by_id" in indexes


def test_incompatible_existing_schema_is_not_marked_migrated(tmp_path):
    database_path = tmp_path / "incompatible.db"

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                project TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

    with pytest.raises(RuntimeError, match="missing required columns: memory_type"):
        initialize_database(database_path)

    with sqlite3.connect(database_path) as connection:
        migration_table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_migrations'
            """
        ).fetchone()

    assert migration_table is None


def test_migrations_are_idempotent(tmp_path):
    database_path = tmp_path / "repeat.db"

    first = initialize_database(database_path)
    second = initialize_database(database_path)

    assert first == LATEST_SCHEMA_VERSION
    assert second == LATEST_SCHEMA_VERSION

    with database_connection(database_path) as connection:
        applied = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0]

    assert applied == LATEST_SCHEMA_VERSION


def test_newer_database_schema_is_rejected(tmp_path):
    database_path = tmp_path / "future.db"

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, applied_at)
            VALUES (?, ?, ?)
            """,
            (
                LATEST_SCHEMA_VERSION + 1,
                "future_migration",
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    with pytest.raises(RuntimeError, match="newer than this MootOS build"):
        initialize_database(database_path)


def test_foreign_keys_reject_orphan_messages(tmp_path):
    database_path = tmp_path / "foreign-keys.db"
    initialize_database(database_path)

    with pytest.raises(sqlite3.IntegrityError):
        with database_connection(database_path) as connection:
            connection.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, provider, model, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    "missing-conversation",
                    "user",
                    "This must not be saved",
                    None,
                    None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


def test_concurrent_writes_complete_without_lock_failures(tmp_path):
    database_path = tmp_path / "concurrent.db"
    initialize_database(database_path)

    def write_memory(index: int) -> None:
        with database_connection(database_path) as connection:
            connection.execute(
                """
                INSERT INTO memories (id, content, project, memory_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    f"Concurrent memory {index}",
                    "MootOS",
                    "test",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    write_count = 40
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write_memory, range(write_count)))

    with database_connection(database_path) as connection:
        saved_count = connection.execute(
            "SELECT COUNT(*) FROM memories WHERE memory_type = 'test'"
        ).fetchone()[0]

    assert saved_count == write_count
