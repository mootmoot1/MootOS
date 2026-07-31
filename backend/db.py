"""Central SQLite connection configuration for MootOS."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Union


SQLITE_BUSY_TIMEOUT_MS = 5_000
SQLITE_CONNECT_TIMEOUT_SECONDS = SQLITE_BUSY_TIMEOUT_MS / 1_000
DatabasePath = Union[str, Path]


def resolve_database_path() -> Path:
    """Choose an explicit path, Railway volume, or local development database."""
    explicit_path = os.getenv("MOOTOS_DATABASE_PATH", "").strip()
    if explicit_path:
        return Path(explicit_path).expanduser()

    railway_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if railway_mount:
        return Path(railway_mount) / "mootos.db"

    return Path(__file__).resolve().parent.parent / "data" / "mootos.db"


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
