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

## Correctness details worth knowing

1. **Project names are matched case-insensitively, and counts accumulate.**
   ``projects.name`` is ``UNIQUE COLLATE NOCASE``, and
   ``memories``/``tasks``/``conversations`` each store the canonical
   project *name*. Every current write path canonicalizes, so mixed-case
   values should not occur -- but if a legacy or directly-inserted row
   does carry one, ``GROUP BY project`` yields it as a separate row.
   Those rows are merged on a ``casefold()``-ed key and their counts are
   **added together**, never overwritten. (An earlier revision assigned
   instead of accumulating, so the last row silently evicted the other
   spelling's counts; that was caught in advisory review and is covered
   by a regression test.)
2. **A ``project`` value with no matching row in ``projects`` is folded
   into ``unassigned``, not dropped.** Otherwise those rows would vanish
   from both the per-project entries and the unassigned bucket, which
   would defeat the whole point of reporting ``unassigned`` at all.
3. **Timestamps are compared as strings, and that is sound here -- but
   not for the reason it might appear.** ``isoformat()`` is *not*
   fixed-width: it emits ``2026-01-01T00:00:00+00:00`` (25 chars) when
   microseconds are exactly zero and ``...00.000001+00:00`` (32 chars)
   otherwise. Lexicographic order still matches chronological order
   because the two possible characters at the divergence point are ``+``
   (0x2B) and ``.`` (0x2E), and ``+`` sorts first -- which is the correct
   answer, since a timestamp with no microseconds precedes one with any.
   All six write paths use the same UTC ``isoformat()`` constructor. Do
   not rely on these strings being a fixed length.
4. **``last_activity_at`` is monotonic and genuinely means "last
   touched".** It is computed over *all* rows of each table -- not just
   the ones being counted -- using ``COALESCE(updated_at, created_at)``.
   That matters: an earlier revision took ``MAX(created_at)`` over
   *active* memories only, so completing a Task did not move the
   timestamp and archiving the newest memory moved it *backward*. Both
   were caught in advisory review and are covered by regression tests.

## Consistency and cost

The four reads run inside one connection but are four separate
statements, and Python's ``sqlite3`` does not hold a read snapshot across
them (it opens transactions only for DML). A writer interleaving between
statements could therefore produce a slightly inconsistent rollup. This
is accepted rather than fixed: MootOS is single-user and single-replica,
and taking an explicit transaction here would add write-path contention
for a read-only convenience view.

Each aggregate is a full scan of its table, and the number of entries
returned is capped at ``MAX_PROJECT_ENTRIES`` with an explicit
``truncated`` flag, so the output can never grow without bound (raised in
advisory review: every sibling list-shaped tool in this codebase bounds
its results).

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

# Hard cap on how many project entries one call returns. Projects are
# user-created and realistically number in the tens, so this is not
# expected to bind -- it exists so the response can never grow without
# bound, matching the bounded-output pattern every other list-shaped tool
# in this codebase already follows. When it does bind, `truncated` says so
# explicitly rather than silently returning a partial answer.
MAX_PROJECT_ENTRIES = 200


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

        # Counts are filtered (active memories, open tasks) but the
        # activity timestamp deliberately is not -- see docstring note 4.
        memory_rows = connection.execute(
            """
            SELECT project,
                   SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS active_memories,
                   MAX(COALESCE(updated_at, created_at)) AS last_touched_at
            FROM memories
            GROUP BY project
            """,
            (MEMORY_STATUS_ACTIVE,),
        ).fetchall()
        for row in memory_rows:
            entry = entry_for(row["project"])
            entry["active_memories"] += int(row["active_memories"] or 0)
            entry["last_activity_at"] = _newer(entry["last_activity_at"], row["last_touched_at"])

        task_rows = connection.execute(
            """
            SELECT project,
                   COUNT(*) AS total_tasks,
                   SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS open_tasks,
                   MAX(COALESCE(updated_at, created_at)) AS last_touched_at
            FROM tasks
            GROUP BY project
            """,
            (TASK_STATUS_OPEN,),
        ).fetchall()
        for row in task_rows:
            entry = entry_for(row["project"])
            entry["total_tasks"] += int(row["total_tasks"] or 0)
            entry["open_tasks"] += int(row["open_tasks"] or 0)
            entry["last_activity_at"] = _newer(entry["last_activity_at"], row["last_touched_at"])

        conversation_rows = connection.execute(
            """
            SELECT project,
                   COUNT(*) AS conversations,
                   MAX(COALESCE(updated_at, created_at)) AS last_touched_at
            FROM conversations
            GROUP BY project
            """
        ).fetchall()
        for row in conversation_rows:
            entry = entry_for(row["project"])
            entry["conversations"] += int(row["conversations"] or 0)
            entry["last_activity_at"] = _newer(entry["last_activity_at"], row["last_touched_at"])

        project_rows = connection.execute(
            "SELECT name FROM projects ORDER BY name COLLATE NOCASE ASC"
        ).fetchall()

    known_keys = {_merge_key(str(row["name"])) for row in project_rows}

    entries = []
    for row in project_rows:
        name = str(row["name"])
        if canonical_project is not None and name != canonical_project:
            continue
        entry = dict(merged.get(_merge_key(name), _empty_entry()))
        entries.append({"name": name, **entry})

    truncated = len(entries) > MAX_PROJECT_ENTRIES
    entries = entries[:MAX_PROJECT_ENTRIES]

    result: dict[str, Any] = {
        "projects": entries,
        "count": len(entries),
        "truncated": truncated,
    }
    if canonical_project is None:
        # Fold rows whose project value matches no known project into
        # `unassigned` rather than dropping them -- see docstring note 2.
        unassigned = _empty_entry()
        for key, entry in merged.items():
            if key in known_keys:
                continue
            unassigned["active_memories"] += entry["active_memories"]
            unassigned["open_tasks"] += entry["open_tasks"]
            unassigned["total_tasks"] += entry["total_tasks"]
            unassigned["conversations"] += entry["conversations"]
            unassigned["last_activity_at"] = _newer(
                unassigned["last_activity_at"], entry["last_activity_at"]
            )
        result["unassigned"] = unassigned
    return result
