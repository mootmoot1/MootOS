"""Versioned SQLite schema migrations for MootOS."""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Union

from backend.db import connect, environment_flag, running_on_railway


DatabasePath = Union[str, Path]
MigrationFunction = Callable[[sqlite3.Connection], None]


class MigrationBackupRequiredError(RuntimeError):
    """Raised when a new migration would run on Railway without an
    operator-confirmed backup (see docs/future/CONTINUOUS_BUILDER_PHASE_2_SCHEMA.md
    and backend.db_backup)."""

DEFAULT_PROJECTS = (
    ("MootOS", "Development and planning for the MootOS personal AI system."),
    ("Studio", "Studio sessions, clients, engineering work, and business operations."),
    ("Social Media", "Content ideas, publishing plans, and audience growth."),
    ("Cars", "Vehicle maintenance, repairs, and automotive projects."),
    ("Personal", "Personal information that does not belong to another project."),
)

REQUIRED_COLUMNS = {
    "projects": {"id", "name", "description", "created_at"},
    "memories": {"id", "content", "project", "memory_type", "created_at", "status", "updated_at", "replaces_memory_id", "superseded_by_id"},
    "conversations": {"id", "title", "project", "created_at", "updated_at"},
    "messages": {"id", "conversation_id", "role", "content", "provider", "model", "created_at"},
    "runs": {"id", "run_type", "status", "conversation_id", "user_message_id", "assistant_message_id", "provider", "model", "tool_name", "tool_version", "started_at", "finished_at", "duration_ms", "error_class", "input_tokens", "output_tokens", "cost_usd", "data_exposure"},
    "tasks": {"id", "title", "project", "status", "due_at", "created_at", "updated_at", "completed_at", "cancelled_at"},
    "tool_operations": {"id", "tool_name", "tool_version", "status", "arguments_json", "conversation_id", "project", "created_at", "updated_at", "expires_at", "decided_at", "result_run_id", "result_reference", "error_class"},
    "builder_blueprints": {"blueprint_id", "blueprint_version", "content_digest", "canonical_json", "approval_id", "approver_id", "approver_authenticated", "created_at"},
    "builder_slices": {"blueprint_id", "blueprint_version", "slice_id", "slice_version", "canonical_json"},
    "builder_events": {"event_id", "blueprint_id", "blueprint_version", "blueprint_digest", "slice_id", "slice_version", "sequence", "previous_digest", "previous_state", "next_state", "reason", "actor_id", "actor_authenticated", "attempt_id", "dependency_digest", "policy_version", "created_at", "event_digest"},
    "builder_attempts": {"attempt_id", "blueprint_id", "blueprint_version", "slice_id", "slice_version", "owner_id", "created_at"},
    "builder_leases": {"lease_id", "attempt_id", "slice_id", "owner_id", "acquired_at", "expires_at", "released_at", "blueprint_id", "blueprint_version", "slice_version"},
    "builder_idempotency": {"idempotency_key", "operation", "content_digest", "created_at"},
    "builder_artifacts": {"artifact_id", "slice_id", "attempt_id", "kind", "content_digest", "size_bytes", "created_at"},
    "builder_lease_reconciliations": {"reconciliation_id", "lease_id", "attempt_id", "verdict", "evidence", "actor_id", "reconciled_at"},
    "schema_migrations": {"version", "name", "applied_at"},
}


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: MigrationFunction


def _migration_001_initial_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, description TEXT, created_at TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, content TEXT NOT NULL, project TEXT, memory_type TEXT, created_at TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, project TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, provider TEXT, model TEXT, created_at TEXT NOT NULL, FOREIGN KEY (conversation_id) REFERENCES conversations(id))""")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages (conversation_id)")
    created_at = datetime.now(timezone.utc).isoformat()
    connection.executemany("INSERT OR IGNORE INTO projects (id, name, description, created_at) VALUES (?, ?, ?, ?)", ((str(uuid.uuid4()), name, description, created_at) for name, description in DEFAULT_PROJECTS))


def _migration_002_memory_lifecycle(connection: sqlite3.Connection) -> None:
    existing_columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(memories)").fetchall()}
    if "status" not in existing_columns:
        connection.execute("ALTER TABLE memories ADD COLUMN status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'archived'))")
    if "updated_at" not in existing_columns:
        connection.execute("ALTER TABLE memories ADD COLUMN updated_at TEXT")
    if "replaces_memory_id" not in existing_columns:
        connection.execute("ALTER TABLE memories ADD COLUMN replaces_memory_id TEXT")
    if "superseded_by_id" not in existing_columns:
        connection.execute("ALTER TABLE memories ADD COLUMN superseded_by_id TEXT")
    connection.execute("UPDATE memories SET status = 'active' WHERE status IS NULL OR status = ''")
    connection.execute("UPDATE memories SET updated_at = created_at WHERE updated_at IS NULL OR updated_at = ''")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_status_created_at ON memories (status, created_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_superseded_by_id ON memories (superseded_by_id)")


def _migration_003_model_runs(connection: sqlite3.Connection) -> None:
    connection.execute("""
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
            data_exposure TEXT CHECK (data_exposure IS NULL OR data_exposure IN ('local', 'model_provider', 'tool_external'))
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs (started_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_conversation_id_started_at ON runs (conversation_id, started_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_status_started_at ON runs (status, started_at DESC)")


def _migration_004_tasks(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL CHECK (length(trim(title)) > 0 AND length(title) <= 500),
            project TEXT,
            status TEXT NOT NULL CHECK (status IN ('open', 'completed', 'cancelled')),
            due_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            cancelled_at TEXT
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_due_at ON tasks (status, due_at, created_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_status_due_at ON tasks (project, status, due_at, created_at DESC)")


def _migration_005_tool_system(connection: sqlite3.Connection) -> None:
    """Add tool identity to Runs and a frozen tool-operation approval table.

    Tool identity intentionally lives in new ``tool_name``/``tool_version``
    columns rather than reusing ``provider``/``model``. Those columns mean
    "AI model provider used to generate this Run"; a tool is not a model
    provider, and overloading the columns would make Run rows misleading.
    """
    existing_run_columns = {
        str(row["name"]) for row in connection.execute("PRAGMA table_info(runs)").fetchall()
    }
    if "tool_name" not in existing_run_columns:
        connection.execute("ALTER TABLE runs ADD COLUMN tool_name TEXT")
    if "tool_version" not in existing_run_columns:
        connection.execute("ALTER TABLE runs ADD COLUMN tool_version TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_tool_name_started_at ON runs (tool_name, started_at DESC)"
    )

    connection.execute("""
        CREATE TABLE IF NOT EXISTS tool_operations (
            id TEXT PRIMARY KEY,
            tool_name TEXT NOT NULL,
            tool_version TEXT,
            status TEXT NOT NULL CHECK (
                status IN ('pending', 'executing', 'succeeded', 'rejected', 'failed', 'expired')
            ),
            arguments_json TEXT NOT NULL,
            conversation_id TEXT,
            project TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            decided_at TEXT,
            result_run_id TEXT,
            result_reference TEXT,
            error_class TEXT
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_operations_status_created_at ON tool_operations (status, created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_operations_conversation_id ON tool_operations (conversation_id)"
    )


def _migration_006_continuous_builder_state(
    connection: sqlite3.Connection,
) -> None:
    statements = """
        CREATE TABLE IF NOT EXISTS builder_blueprints (
            blueprint_id TEXT NOT NULL, blueprint_version TEXT NOT NULL,
            content_digest TEXT NOT NULL UNIQUE, canonical_json TEXT NOT NULL,
            approval_id TEXT NOT NULL, approver_id TEXT NOT NULL,
            approver_authenticated INTEGER NOT NULL CHECK (approver_authenticated IN (0, 1)),
            created_at TEXT NOT NULL,
            PRIMARY KEY (blueprint_id, blueprint_version)
        );
        CREATE TABLE IF NOT EXISTS builder_slices (
            blueprint_id TEXT NOT NULL, blueprint_version TEXT NOT NULL,
            slice_id TEXT NOT NULL, slice_version TEXT NOT NULL,
            canonical_json TEXT NOT NULL,
            PRIMARY KEY (blueprint_id, blueprint_version, slice_id),
            FOREIGN KEY (blueprint_id, blueprint_version)
              REFERENCES builder_blueprints (blueprint_id, blueprint_version)
        );
        CREATE TABLE IF NOT EXISTS builder_events (
            event_id TEXT PRIMARY KEY,
            blueprint_id TEXT NOT NULL, blueprint_version TEXT NOT NULL,
            blueprint_digest TEXT NOT NULL, slice_id TEXT NOT NULL,
            slice_version TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence >= 1),
            previous_digest TEXT, previous_state TEXT, next_state TEXT NOT NULL,
            reason TEXT NOT NULL, actor_id TEXT NOT NULL,
            actor_authenticated INTEGER NOT NULL CHECK (actor_authenticated IN (0, 1)),
            attempt_id TEXT, dependency_digest TEXT NOT NULL,
            policy_version TEXT NOT NULL, created_at TEXT NOT NULL,
            event_digest TEXT NOT NULL UNIQUE,
            UNIQUE (blueprint_id, blueprint_version, slice_id, sequence),
            FOREIGN KEY (blueprint_id, blueprint_version, slice_id)
              REFERENCES builder_slices (blueprint_id, blueprint_version, slice_id)
        );
        CREATE TABLE IF NOT EXISTS builder_attempts (
            attempt_id TEXT PRIMARY KEY, blueprint_id TEXT NOT NULL,
            blueprint_version TEXT NOT NULL, slice_id TEXT NOT NULL,
            slice_version TEXT NOT NULL, owner_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (blueprint_id, blueprint_version, slice_id)
              REFERENCES builder_slices (blueprint_id, blueprint_version, slice_id)
        );
        CREATE TABLE IF NOT EXISTS builder_leases (
            lease_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE,
            slice_id TEXT NOT NULL, owner_id TEXT NOT NULL,
            acquired_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            released_at TEXT,
            FOREIGN KEY (attempt_id) REFERENCES builder_attempts (attempt_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_builder_active_lease
          ON builder_leases (slice_id) WHERE released_at IS NULL;
        CREATE TABLE IF NOT EXISTS builder_idempotency (
            idempotency_key TEXT PRIMARY KEY, operation TEXT NOT NULL,
            content_digest TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS builder_artifacts (
            artifact_id TEXT PRIMARY KEY, slice_id TEXT NOT NULL,
            attempt_id TEXT, kind TEXT NOT NULL, content_digest TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
            created_at TEXT NOT NULL,
            FOREIGN KEY (attempt_id) REFERENCES builder_attempts (attempt_id)
        );
    """
    for statement in statements.split(";"):
        if statement.strip():
            connection.execute(statement)


def _migration_007_continuous_builder_hardening(
    connection: sqlite3.Connection,
) -> None:
    """Phase 2.5 hardening: scope active leases by full blueprint/slice
    identity (not slice_id alone), bind builder_events.attempt_id with a
    real foreign key so it can never dangle, and add an audited lease
    reconciliation trail. Additive only: migration 006 is historical and
    is never edited in place (scripts/gates/migration_safety.py) -- the
    ``builder_events`` foreign key is added via SQLite's documented
    rebuild-and-swap procedure, since ALTER TABLE cannot add a foreign key
    to an existing table.
    """
    existing_lease_columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(builder_leases)").fetchall()
    }
    for column in ("blueprint_id", "blueprint_version", "slice_version"):
        if column not in existing_lease_columns:
            connection.execute(f"ALTER TABLE builder_leases ADD COLUMN {column} TEXT")
    connection.execute("""
        UPDATE builder_leases
        SET blueprint_id = (
                SELECT blueprint_id FROM builder_attempts
                WHERE builder_attempts.attempt_id = builder_leases.attempt_id
            ),
            blueprint_version = (
                SELECT blueprint_version FROM builder_attempts
                WHERE builder_attempts.attempt_id = builder_leases.attempt_id
            ),
            slice_version = (
                SELECT slice_version FROM builder_attempts
                WHERE builder_attempts.attempt_id = builder_leases.attempt_id
            )
        WHERE blueprint_id IS NULL
    """)
    connection.execute("DROP INDEX IF EXISTS idx_builder_active_lease")
    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_builder_active_lease_identity
          ON builder_leases (blueprint_id, blueprint_version, slice_id, slice_version)
          WHERE released_at IS NULL
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS builder_events__v2 (
            event_id TEXT PRIMARY KEY,
            blueprint_id TEXT NOT NULL, blueprint_version TEXT NOT NULL,
            blueprint_digest TEXT NOT NULL, slice_id TEXT NOT NULL,
            slice_version TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence >= 1),
            previous_digest TEXT, previous_state TEXT, next_state TEXT NOT NULL,
            reason TEXT NOT NULL, actor_id TEXT NOT NULL,
            actor_authenticated INTEGER NOT NULL CHECK (actor_authenticated IN (0, 1)),
            attempt_id TEXT, dependency_digest TEXT NOT NULL,
            policy_version TEXT NOT NULL, created_at TEXT NOT NULL,
            event_digest TEXT NOT NULL UNIQUE,
            UNIQUE (blueprint_id, blueprint_version, slice_id, sequence),
            FOREIGN KEY (blueprint_id, blueprint_version, slice_id)
              REFERENCES builder_slices (blueprint_id, blueprint_version, slice_id),
            FOREIGN KEY (attempt_id) REFERENCES builder_attempts (attempt_id)
        )
    """)
    already_rebuilt = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='builder_events' "
        "AND sql LIKE '%FOREIGN KEY (attempt_id)%'"
    ).fetchone()
    if already_rebuilt is None:
        connection.execute(
            "INSERT INTO builder_events__v2 SELECT event_id, blueprint_id, "
            "blueprint_version, blueprint_digest, slice_id, slice_version, "
            "sequence, previous_digest, previous_state, next_state, reason, "
            "actor_id, actor_authenticated, attempt_id, dependency_digest, "
            "policy_version, created_at, event_digest FROM builder_events"
        )
        connection.execute("DROP TABLE builder_events")
        connection.execute("ALTER TABLE builder_events__v2 RENAME TO builder_events")
    else:
        connection.execute("DROP TABLE builder_events__v2")

    connection.execute("""
        CREATE TABLE IF NOT EXISTS builder_lease_reconciliations (
            reconciliation_id TEXT PRIMARY KEY,
            lease_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
            verdict TEXT NOT NULL CHECK (
                verdict IN ('worker_confirmed_stopped', 'worker_confirmed_running')
            ),
            evidence TEXT NOT NULL, actor_id TEXT NOT NULL,
            reconciled_at TEXT NOT NULL,
            FOREIGN KEY (lease_id) REFERENCES builder_leases (lease_id),
            FOREIGN KEY (attempt_id) REFERENCES builder_attempts (attempt_id)
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_builder_lease_reconciliations_lease_id "
        "ON builder_lease_reconciliations (lease_id, reconciled_at DESC)"
    )


MIGRATIONS = (
    Migration(1, "initial_schema", _migration_001_initial_schema),
    Migration(2, "memory_lifecycle", _migration_002_memory_lifecycle),
    Migration(3, "model_runs", _migration_003_model_runs),
    Migration(4, "tasks", _migration_004_tasks),
    Migration(5, "tool_system", _migration_005_tool_system),
    Migration(6, "continuous_builder_state", _migration_006_continuous_builder_state),
    Migration(7, "continuous_builder_hardening", _migration_007_continuous_builder_hardening),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")


def _current_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations").fetchone()
    return int(row["version"])


def _verify_schema(connection: sqlite3.Connection) -> None:
    for table, required_columns in REQUIRED_COLUMNS.items():
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        actual_columns = {str(row["name"]) for row in rows}
        missing_columns = required_columns - actual_columns
        if missing_columns:
            raise RuntimeError(f"Database schema is incompatible: table {table} is missing required columns: {', '.join(sorted(missing_columns))}")
    foreign_keys = connection.execute("PRAGMA foreign_key_list(messages)").fetchall()
    if not any(str(row["table"]) == "conversations" and str(row["from"]) == "conversation_id" and str(row["to"]) == "id" for row in foreign_keys):
        raise RuntimeError("Database schema is incompatible: messages.conversation_id must reference conversations.id")
    invalid_memory_status = connection.execute("SELECT status FROM memories WHERE status NOT IN ('active', 'superseded', 'archived') LIMIT 1").fetchone()
    if invalid_memory_status is not None:
        raise RuntimeError(f"Database schema is incompatible: memories.status contains unsupported value {invalid_memory_status['status']!r}")
    invalid_run = connection.execute("""SELECT run_type, status, data_exposure FROM runs WHERE run_type NOT IN ('model', 'tool') OR status NOT IN ('started', 'succeeded', 'failed') OR (data_exposure IS NOT NULL AND data_exposure NOT IN ('local', 'model_provider', 'tool_external')) LIMIT 1""").fetchone()
    if invalid_run is not None:
        raise RuntimeError("Database schema is incompatible: runs contains unsupported run metadata")
    invalid_tool_run = connection.execute(
        "SELECT id FROM runs WHERE run_type = 'tool' AND (tool_name IS NULL OR trim(tool_name) = '') LIMIT 1"
    ).fetchone()
    if invalid_tool_run is not None:
        raise RuntimeError("Database schema is incompatible: a tool run is missing tool_name")
    invalid_operation = connection.execute("""
        SELECT status
        FROM tool_operations
        WHERE status NOT IN ('pending', 'executing', 'succeeded', 'rejected', 'failed', 'expired')
           OR length(trim(tool_name)) = 0
        LIMIT 1
    """).fetchone()
    if invalid_operation is not None:
        raise RuntimeError("Database schema is incompatible: tool_operations contains unsupported metadata")
    invalid_task = connection.execute("""
        SELECT status
        FROM tasks
        WHERE status NOT IN ('open', 'completed', 'cancelled')
           OR length(trim(title)) = 0
           OR length(title) > 500
        LIMIT 1
    """).fetchone()
    if invalid_task is not None:
        raise RuntimeError("Database schema is incompatible: tasks contains unsupported task metadata")


def run_migrations(database_path: Optional[DatabasePath] = None) -> int:
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_migration_table(connection)
        current_version = _current_schema_version(connection)
        if current_version > LATEST_SCHEMA_VERSION:
            raise RuntimeError(f"Database schema is newer than this MootOS build: database={current_version}, supported={LATEST_SCHEMA_VERSION}")
        if (
            current_version < LATEST_SCHEMA_VERSION
            and running_on_railway()
            and not environment_flag("MOOTOS_MIGRATION_BACKUP_CONFIRMED")
        ):
            raise MigrationBackupRequiredError(
                "Refusing to apply a new migration on Railway without an "
                "operator-confirmed backup. Take and verify a backup with "
                "backend.db_backup.create_sqlite_backup, stop writers, "
                "then set MOOTOS_MIGRATION_BACKUP_CONFIRMED=true for this "
                "deploy/run."
            )
        for migration in MIGRATIONS:
            if migration.version <= current_version:
                continue
            expected_version = current_version + 1
            if migration.version != expected_version:
                raise RuntimeError(f"Database migration sequence is incomplete: expected version {expected_version}, found {migration.version}")
            migration.apply(connection)
            connection.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)", (migration.version, migration.name, datetime.now(timezone.utc).isoformat()))
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
    return run_migrations(database_path)


def get_schema_version(database_path: Optional[DatabasePath] = None) -> int:
    connection = connect(database_path)
    try:
        row = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'").fetchone()
        if row is None:
            return 0
        return _current_schema_version(connection)
    finally:
        connection.close()
