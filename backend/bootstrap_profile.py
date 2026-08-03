"""Deterministic preview and atomic import for curated MootOS profiles."""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.db import database_connection
from backend.memory import (
    MEMORY_STATUS_ACTIVE,
    MEMORY_STATUS_ARCHIVED,
    MEMORY_STATUS_SUPERSEDED,
)


BOOTSTRAP_PROFILE_VERSION = 1
BOOTSTRAP_PROFILE_MEMORY_TYPE = "bootstrap_profile"
MAX_BOOTSTRAP_PROFILE_ENTRIES = 50
MAX_BOOTSTRAP_PROFILE_CONTENT_LENGTH = 10_000
MAX_PROJECT_NAME_LENGTH = 100


class BootstrapProfileValidationError(ValueError):
    """Raised when a submitted bootstrap-profile manifest is invalid."""


class BootstrapProfileConflictError(ValueError):
    """Raised when lifecycle history blocks an otherwise valid import."""


class BootstrapProfileStorageError(RuntimeError):
    """Raised when preview or import cannot safely read or write storage."""


def _normalize_content(content: str) -> str:
    """Return the literal-equivalence form used for duplicate classification."""
    return " ".join(content.split()).casefold()


def _scope_key(project: Optional[str]) -> Optional[str]:
    return project.casefold() if project is not None else None


def _load_project_names(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        "SELECT name FROM projects ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return {str(row["name"]).casefold(): str(row["name"]) for row in rows}


def _validate_manifest(
    connection: sqlite3.Connection,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate and canonicalize one private Version 1 profile manifest."""
    if not isinstance(manifest, dict):
        raise BootstrapProfileValidationError("Profile manifest must be a JSON object")
    if manifest.get("version") != BOOTSTRAP_PROFILE_VERSION:
        raise BootstrapProfileValidationError(
            "Profile manifest version must be 1"
        )

    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise BootstrapProfileValidationError("Profile entries must be a JSON array")
    if not 1 <= len(entries) <= MAX_BOOTSTRAP_PROFILE_ENTRIES:
        raise BootstrapProfileValidationError(
            "Profile manifest must contain between 1 and 50 entries"
        )

    project_names = _load_project_names(connection)
    prepared: list[dict[str, Any]] = []
    seen: set[tuple[Optional[str], str]] = set()

    for entry in entries:
        if not isinstance(entry, dict):
            raise BootstrapProfileValidationError(
                "Every profile entry must be a JSON object"
            )

        content = entry.get("content")
        if not isinstance(content, str):
            raise BootstrapProfileValidationError(
                "Every profile entry must contain text content"
            )
        content = content.strip()
        if not content:
            raise BootstrapProfileValidationError(
                "Profile entry content cannot be empty"
            )
        if len(content) > MAX_BOOTSTRAP_PROFILE_CONTENT_LENGTH:
            raise BootstrapProfileValidationError(
                "Profile entry content must be 10,000 characters or fewer"
            )

        project = entry.get("project")
        if project is not None:
            if not isinstance(project, str):
                raise BootstrapProfileValidationError(
                    "Profile entry project must be a project name or null"
                )
            project = project.strip()
            if not project:
                raise BootstrapProfileValidationError(
                    "Profile entry project cannot be blank"
                )
            if len(project) > MAX_PROJECT_NAME_LENGTH:
                raise BootstrapProfileValidationError(
                    "Profile entry project name is too long"
                )
            canonical_project = project_names.get(project.casefold())
            if canonical_project is None:
                raise BootstrapProfileValidationError(
                    "Profile entry references a project that does not exist"
                )
            project = canonical_project

        duplicate_key = (_scope_key(project), _normalize_content(content))
        if duplicate_key in seen:
            raise BootstrapProfileValidationError(
                "Profile manifest contains duplicate entries in the same scope"
            )
        seen.add(duplicate_key)
        prepared.append({"content": content, "project": project})

    return prepared


def _memory_index(
    connection: sqlite3.Connection,
) -> dict[tuple[Optional[str], str], list[dict[str, Any]]]:
    rows = connection.execute(
        """
        SELECT id, content, project, memory_type, status
        FROM memories
        WHERE status IN (?, ?, ?)
        """,
        (
            MEMORY_STATUS_ACTIVE,
            MEMORY_STATUS_ARCHIVED,
            MEMORY_STATUS_SUPERSEDED,
        ),
    ).fetchall()

    index: dict[tuple[Optional[str], str], list[dict[str, Any]]] = {}
    for row in rows:
        memory = dict(row)
        key = (
            _scope_key(memory["project"]),
            _normalize_content(memory["content"]),
        )
        index.setdefault(key, []).append(memory)
    return index


def _classify_entries(
    connection: sqlite3.Connection,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    index = _memory_index(connection)
    ready: list[dict[str, Any]] = []
    already_active: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for entry in entries:
        key = (
            _scope_key(entry["project"]),
            _normalize_content(entry["content"]),
        )
        matches = index.get(key, [])
        has_lifecycle_conflict = any(
            match["status"]
            in {MEMORY_STATUS_ARCHIVED, MEMORY_STATUS_SUPERSEDED}
            for match in matches
        )
        has_active_match = any(
            match["status"] == MEMORY_STATUS_ACTIVE for match in matches
        )

        public_entry = {
            "content": entry["content"],
            "project": entry["project"],
        }
        if has_lifecycle_conflict:
            blocked.append({**public_entry, "reason": "lifecycle_conflict"})
        elif has_active_match:
            already_active.append({**public_entry, "reason": "already_active"})
        else:
            ready.append(public_entry)

    return {
        "version": BOOTSTRAP_PROFILE_VERSION,
        "ready": ready,
        "already_active": already_active,
        "blocked": blocked,
        "counts": {
            "ready": len(ready),
            "already_active": len(already_active),
            "blocked": len(blocked),
            "total": len(entries),
        },
        "can_import": not blocked,
    }


def preview_bootstrap_profile(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a read-only classification without changing database state."""
    try:
        with database_connection() as connection:
            entries = _validate_manifest(connection, manifest)
            return _classify_entries(connection, entries)
    except BootstrapProfileValidationError:
        raise
    except sqlite3.Error as error:
        raise BootstrapProfileStorageError(
            "MootOS could not preview the profile safely"
        ) from error


def import_bootstrap_profile(manifest: dict[str, Any]) -> dict[str, Any]:
    """Revalidate and import every ready entry in one transaction."""
    try:
        with database_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            entries = _validate_manifest(connection, manifest)
            preview = _classify_entries(connection, entries)
            if preview["blocked"]:
                raise BootstrapProfileConflictError(
                    "Profile import is blocked by archived or corrected memory history"
                )

            now = datetime.now(timezone.utc).isoformat()
            imported: list[dict[str, Any]] = []
            for entry in preview["ready"]:
                memory = {
                    "id": str(uuid.uuid4()),
                    "content": entry["content"],
                    "project": entry["project"],
                    "memory_type": BOOTSTRAP_PROFILE_MEMORY_TYPE,
                    "created_at": now,
                    "status": MEMORY_STATUS_ACTIVE,
                    "updated_at": now,
                    "replaces_memory_id": None,
                    "superseded_by_id": None,
                }
                connection.execute(
                    """
                    INSERT INTO memories (
                        id,
                        content,
                        project,
                        memory_type,
                        created_at,
                        status,
                        updated_at,
                        replaces_memory_id,
                        superseded_by_id
                    )
                    VALUES (
                        :id,
                        :content,
                        :project,
                        :memory_type,
                        :created_at,
                        :status,
                        :updated_at,
                        :replaces_memory_id,
                        :superseded_by_id
                    )
                    """,
                    memory,
                )
                imported.append(memory)

            return {
                "version": BOOTSTRAP_PROFILE_VERSION,
                "imported": imported,
                "already_active": preview["already_active"],
                "counts": {
                    "imported": len(imported),
                    "already_active": len(preview["already_active"]),
                    "total": len(entries),
                },
            }
    except (BootstrapProfileValidationError, BootstrapProfileConflictError):
        raise
    except sqlite3.Error as error:
        raise BootstrapProfileStorageError(
            "MootOS could not import the profile safely"
        ) from error
