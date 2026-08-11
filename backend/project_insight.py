"""Cross-resource per-project rollup (V0.3E manual-pipeline proof #2).

A **read-only derived view** over data that already exists: the
``projects``, ``memories``, ``tasks``, and ``conversations`` tables. It
adds no storage, no column, and no migration -- like
``backend/capability_catalog.py`` and ``backend/self_inspection.py``,
this module only reads and reshapes.

Why this lives in its own module rather than in ``backend/memory.py`` or
``backend/tasks.py``: the rollup deliberately spans several domains at
once, so it belongs to none of them. Putting a query over ``tasks`` into
``backend/memory.py`` (or vice versa) would blur the domain boundaries
``AGENTS.md`` asks to keep separate.

## Query shape

Three ``GROUP BY project`` aggregates plus one project listing -- four
queries total, independent of how many projects exist. This is
deliberately **not** an N+1 loop issuing per-project counts, so the cost
does not grow with the number of projects.

## Two correctness details worth knowing

1. **Project names are matched case-insensitively.** ``projects.name`` is
   ``UNIQUE COLLATE NOCASE``, and ``memories``/``tasks``/``conversations``
   each store the canonical project *name* (resolved through their own
   ``_get_project``-style lookups at write time). Merging on a
   ``casefold()``-ed key means a row stored under a differently-cased
   spelling still lands on the right project instead of silently
   disappearing from the rollup.
2. **Timestamps are compared as strings, and that is sound here.** Every
   ``created_at``/``updated_at`` in these tables is written as
   ``datetime.now(timezone.utc).isoformat()`` -- always UTC, always the
   same fixed-width shape -- so lexicographic ``max()`` over them equals
   chronological max. This would stop being true if a caller ever stored
   a local-timezone or differently-formatted timestamp; nothing in
   MootOS does.

## What this deliberately does not expose

Counts and one timestamp per project. **No memory content, no task
titles, no conversation titles, and no message content of any kind.** A
caller learns how much is in a project and when it was last touched,
never what any of it says.
"""

import sqlite3
from typing import Any, Optional

from backend.db import database_connection
from backend.memory import MEMORY_STATUS_ACTIVE
from backend.tasks import TASK_STATUS_OPEN


# The key used for the not-assigned-to-any-project bucket in the merged
# intermediate mapping. Never a legal project name (project names are
# non-empty), so it cannot collide with a real one.
_UNASSIGNED_KEY = None


def _empty_entry() -> dict[str, Any]:
    return {
        "active_memories": 0,
        "open_tasks": 0,
        "total_tasks": 0,
        "conversations": 0,
        "last_activity_at": None,
    }


def _newer(current: Optional[str], candidate: Optional[str]) -> Optional[str]:
    """Lexicographic max of two ISO-8601 UTC timestamps -- see the module
    docstring for why string comparison is correct for these columns."""
    if candidate is None:
        return current
    if current is None:
        return candidate
    return max(current, candidate)


def _merge_key(project: Optional[str]) -> Optional[str]:
    return _UNASSIGNED_KEY if project is None else project.casefold()


def _canonical_project_name(connection: sqlite3.Connection, project: str) -> str:
    row = connection.execute(
        "SELECT name FROM projects WHERE name = ? COLLATE NOCASE",
        (project,),
    ).fetchone()
    if row is None:
        raise ValueError("Project does not exist")
    return str(row["name"])


def summarize_projects(project: Optional[str] = None) -> dict[str, Any]:
    """Summarize activity per project, optionally scoped to one project.

    Returns::

        {
          "projects": [
            {"name", "active_memories", "open_tasks", "total_tasks",
             "conversations", "last_activity_at"},
            ...                      # one entry per project, name-ordered
          ],
          "count": <number of project entries returned>,
          "unassigned": {...}        # same shape minus "name"; omitted
                                     # entirely when scoped to one project
        }

    Every project in the ``projects`` table always appears, including one
    with no activity at all (all zeros, ``last_activity_at`` ``None``) --
    so an empty project is visibly empty rather than mysteriously absent.

    ``unassigned`` counts memories/tasks/conversations whose ``project``
    is ``NULL``. It exists so the per-project numbers are never quietly
    misleading: without it, a caller summing the rows could conclude
    MootOS holds fewer Tasks than it really does. It is omitted when
    ``project`` scopes the call to a single project, where an
    unassigned bucket would be meaningless.

    Raises ``ValueError`` when ``project`` names a project that does not
    exist -- the same fail-closed behavior ``backend.tasks`` already uses.
    """
    with database_connection() as connection:
        canonical_project = None
        if project is not None:
            canonical_project = _canonical_project_name(connection, project)

        merged: dict[Optional[str], dict[str, Any]] = {}

        def entry_for(name: Optional[str]) -> dict[str, Any]:
            key = _merge_key(name)
            if key not in merged:
                merged[key] = _empty_entry()
            return merged[key]

        memory_rows = connection.execute(
            """
            SELECT project,
                   COUNT(*) AS active_memories,
                   MAX(created_at) AS last_created_at
            FROM memories
            WHERE status = ?
            GROUP BY project
            """,
            (MEMORY_STATUS_ACTIVE,),
        ).fetchall()
        for row in memory_rows:
            entry = entry_for(row["project"])
            entry["active_memories"] = int(row["active_memories"])
            entry["last_activity_at"] = _newer(entry["last_activity_at"], row["last_created_at"])

        task_rows = connection.execute(
            """
            SELECT project,
                   COUNT(*) AS total_tasks,
                   SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS open_tasks,
                   MAX(created_at) AS last_created_at
            FROM tasks
            GROUP BY project
            """,
            (TASK_STATUS_OPEN,),
        ).fetchall()
        for row in task_rows:
            entry = entry_for(row["project"])
            entry["total_tasks"] = int(row["total_tasks"])
            entry["open_tasks"] = int(row["open_tasks"] or 0)
            entry["last_activity_at"] = _newer(entry["last_activity_at"], row["last_created_at"])

        conversation_rows = connection.execute(
            """
            SELECT project,
                   COUNT(*) AS conversations,
                   MAX(updated_at) AS last_updated_at
            FROM conversations
            GROUP BY project
            """
        ).fetchall()
        for row in conversation_rows:
            entry = entry_for(row["project"])
            entry["conversations"] = int(row["conversations"])
            entry["last_activity_at"] = _newer(entry["last_activity_at"], row["last_updated_at"])

        project_rows = connection.execute(
            "SELECT name FROM projects ORDER BY name COLLATE NOCASE ASC"
        ).fetchall()

    entries = []
    for row in project_rows:
        name = str(row["name"])
        if canonical_project is not None and name != canonical_project:
            continue
        entry = dict(merged.get(_merge_key(name), _empty_entry()))
        entries.append({"name": name, **entry})

    result: dict[str, Any] = {"projects": entries, "count": len(entries)}
    if canonical_project is None:
        result["unassigned"] = dict(merged.get(_UNASSIGNED_KEY, _empty_entry()))
    return result
