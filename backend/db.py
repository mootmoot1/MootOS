"""Central SQLite connection configuration for MootOS."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Union


SQLITE_BUSY_TIMEOUT_MS = 5_000
SQLITE_CONNECT_TIMEOUT_SECONDS = SQLITE_BUSY_TIMEOUT_MS / 1_000
TRUE_VALUES = {"1", "true", "yes", "on"}
DatabasePath = Union[str, Path]


class DatabaseConfigurationError(RuntimeError):
    """Raised when production storage could silently use the wrong database."""


class DatabaseReadinessError(RuntimeError):
    """Raised when the configured database is not ready to serve traffic."""


def _environment_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUE_VALUES


def _running_on_railway() -> bool:
    return bool(
        os.getenv("RAILWAY_ENVIRONMENT", "").strip()
        or os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    )


def _normalized_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        _normalized_path(path).relative_to(_normalized_path(parent))
        return True
    except ValueError:
        return False


def resolve_database_path() -> Path:
    """Choose an explicit path, Railway volume, or local development database."""
    explicit_path = os.getenv("MOOTOS_DATABASE_PATH", "").strip()
    if explicit_path:
        return Path(explicit_path).expanduser()

    railway_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if railway_mount:
        return Path(railway_mount).expanduser() / "mootos.db"

    return Path(__file__).resolve().parent.parent / "data" / "mootos.db"


def validate_database_configuration() -> Path:
    """Fail closed when Railway could start on an unintended database path.

    Local development keeps its normal repository-local fallback and optional
    ``MOOTOS_DATABASE_PATH`` override. Railway must use its attached volume unless
    the separate high-risk override is explicitly enabled.
    """
    resolved_path = resolve_database_path()
    if not _running_on_railway():
        return resolved_path

    explicit_path = os.getenv("MOOTOS_DATABASE_PATH", "").strip()
    railway_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    unsafe_override = _environment_flag("MOOTOS_ALLOW_UNSAFE_DATABASE_PATH")

    if explicit_path:
        if not unsafe_override:
            raise DatabaseConfigurationError(
                "Railway deployments reject MOOTOS_DATABASE_PATH by default. "
                "Use the attached Railway volume, or set "
                "MOOTOS_ALLOW_UNSAFE_DATABASE_PATH=true only for an intentional "
                "high-risk override."
            )
        if not Path(explicit_path).expanduser().is_absolute():
            raise DatabaseConfigurationError(
                "Railway MOOTOS_DATABASE_PATH must be an absolute path"
            )
        return resolved_path

    if not railway_mount:
        raise DatabaseConfigurationError(
            "Railway deployments require an attached persistent volume. "
            "RAILWAY_VOLUME_MOUNT_PATH is missing, so MootOS refuses to create "
            "a temporary local database."
        )

    mount_path = Path(railway_mount).expanduser()
    if not mount_path.is_absolute():
        raise DatabaseConfigurationError(
            "RAILWAY_VOLUME_MOUNT_PATH must be an absolute path"
        )
    if not mount_path.is_dir():
        raise DatabaseConfigurationError(
            "The configured Railway volume mount is unavailable"
        )
    if not _path_is_within(resolved_path, mount_path):
        raise DatabaseConfigurationError(
            "The production database must remain inside the Railway volume mount"
        )
    return resolved_path


DATABASE_PATH = resolve_database_path()


def connect(database_path: Optional[DatabasePath] = None) -> sqlite3.Connection:
    """Open one consistently configured SQLite connection.

    Every caller receives the same safety settings:

    - foreign-key enforcement
    - write-ahead logging
    - NORMAL synchronous mode
    - a five-second busy timeout
    - dictionary-like ``sqlite3.Row`` results
    """
    path = Path(database_path) if database_path is not None else DATABASE_PATH
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        path,
        timeout=SQLITE_CONNECT_TIMEOUT_SECONDS,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def check_database_readiness(
    expected_schema_version: int,
    database_path: Optional[DatabasePath] = None,
) -> None:
    """Verify an existing writable database and exact supported schema.

    Readiness never creates a database or runs migrations. Startup owns those
    responsibilities. This check only proves that the configured existing file
    can be opened read-write and has the schema version the running code expects.
    """
    path = Path(database_path) if database_path is not None else DATABASE_PATH
    path = _normalized_path(path)
    if not path.is_file():
        raise DatabaseReadinessError("Database file is unavailable")

    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=rw",
            uri=True,
            timeout=SQLITE_CONNECT_TIMEOUT_SECONDS,
        )
        try:
            connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
            connection.execute("SELECT 1").fetchone()
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise DatabaseReadinessError("Database cannot be opened safely") from error

    schema_version = int(row[0]) if row is not None else 0
    if schema_version != expected_schema_version:
        raise DatabaseReadinessError("Database schema is not ready")


@contextmanager
def database_connection(
    database_path: Optional[DatabasePath] = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a configured connection and always close it safely."""
    connection = connect(database_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
