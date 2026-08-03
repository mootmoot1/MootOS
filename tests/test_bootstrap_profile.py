"""Tests for deterministic curated bootstrap-profile import behavior."""

import sqlite3
from pathlib import Path

import pytest

from backend.bootstrap_profile import (
    BOOTSTRAP_PROFILE_MEMORY_TYPE,
    BootstrapProfileConflictError,
    BootstrapProfileStorageError,
    BootstrapProfileValidationError,
    import_bootstrap_profile,
    preview_bootstrap_profile,
)
from backend.db import DATABASE_PATH
from backend.memory import archive_memory, correct_memory, create_memory, init_db


@pytest.fixture
def clean_db():
    """Create a clean schema-2 database before each test."""
    paths = [
        Path(DATABASE_PATH),
        Path(f"{DATABASE_PATH}-wal"),
        Path(f"{DATABASE_PATH}-shm"),
    ]
    for path in paths:
        if path.exists():
            path.unlink()
    init_db()
    yield
    for path in paths:
        if path.exists():
            path.unlink()


def manifest(*entries):
    return {"version": 1, "entries": list(entries)}


def memory_rows():
    with sqlite3.connect(DATABASE_PATH) as connection:
        return connection.execute(
            """
            SELECT content, project, memory_type, status
            FROM memories
            ORDER BY created_at, id
            """
        ).fetchall()


def test_preview_is_read_only_and_classifies_ready_entries(clean_db):
    result = preview_bootstrap_profile(
        manifest(
            {"content": "Use plain explanations.", "project": None},
            {"content": "Studio work uses Pro Tools.", "project": "Studio"},
        )
    )

    assert result["can_import"] is True
    assert result["counts"] == {
        "ready": 2,
        "already_active": 0,
        "blocked": 0,
        "total": 2,
    }
    assert result["ready"][1]["project"] == "Studio"
    assert memory_rows() == []


def test_import_writes_all_entries_with_fixed_memory_type(clean_db):
    result = import_bootstrap_profile(
        manifest(
            {"content": "Use plain explanations.", "project": None},
            {"content": "Studio work uses Pro Tools.", "project": "studio"},
        )
    )

    assert result["counts"] == {
        "imported": 2,
        "already_active": 0,
        "total": 2,
    }
    assert {row["memory_type"] for row in result["imported"]} == {
        BOOTSTRAP_PROFILE_MEMORY_TYPE
    }
    assert result["imported"][1]["project"] == "Studio"
    assert memory_rows() == [
        ("Use plain explanations.", None, "bootstrap_profile", "active"),
        ("Studio work uses Pro Tools.", "Studio", "bootstrap_profile", "active"),
    ]


def test_repeated_import_is_a_safe_noop(clean_db):
    profile = manifest(
        {"content": "MootOS should stay understandable.", "project": "MootOS"}
    )

    first = import_bootstrap_profile(profile)
    second_preview = preview_bootstrap_profile(profile)
    second = import_bootstrap_profile(profile)

    assert first["counts"]["imported"] == 1
    assert second_preview["counts"]["already_active"] == 1
    assert second["counts"] == {
        "imported": 0,
        "already_active": 1,
        "total": 1,
    }
    assert len(memory_rows()) == 1


def test_manifest_duplicate_detection_uses_scope_case_and_whitespace(clean_db):
    with pytest.raises(
        BootstrapProfileValidationError,
        match="duplicate entries",
    ):
        preview_bootstrap_profile(
            manifest(
                {"content": "Use   plain explanations", "project": "Personal"},
                {"content": " use plain EXPLANATIONS ", "project": "personal"},
            )
        )

    assert memory_rows() == []


def test_unknown_project_is_rejected_without_writes(clean_db):
    with pytest.raises(
        BootstrapProfileValidationError,
        match="project that does not exist",
    ):
        import_bootstrap_profile(
            manifest(
                {"content": "Unknown scoped fact", "project": "Does Not Exist"}
            )
        )

    assert memory_rows() == []


def test_archived_equivalent_blocks_complete_batch(clean_db):
    archived = create_memory("Keep this archived", project="Personal")
    archive_memory(archived["id"])

    profile = manifest(
        {"content": "Keep this archived", "project": "Personal"},
        {"content": "A second ready fact", "project": None},
    )
    preview = preview_bootstrap_profile(profile)

    assert preview["can_import"] is False
    assert preview["counts"] == {
        "ready": 1,
        "already_active": 0,
        "blocked": 1,
        "total": 2,
    }
    assert preview["blocked"][0]["reason"] == "lifecycle_conflict"

    with pytest.raises(BootstrapProfileConflictError, match="archived or corrected"):
        import_bootstrap_profile(profile)

    assert memory_rows() == [
        ("Keep this archived", "Personal", None, "archived")
    ]


def test_superseded_equivalent_blocks_recreation(clean_db):
    original = create_memory("Old studio preference", project="Studio")
    correct_memory(original["id"], "Current studio preference")

    preview = preview_bootstrap_profile(
        manifest(
            {"content": " old   STUDIO preference ", "project": "studio"}
        )
    )

    assert preview["can_import"] is False
    assert preview["counts"]["blocked"] == 1
    with pytest.raises(BootstrapProfileConflictError):
        import_bootstrap_profile(
            manifest(
                {"content": " old   STUDIO preference ", "project": "studio"}
            )
        )

    assert len(memory_rows()) == 2


def test_global_and_project_scopes_are_distinct(clean_db):
    create_memory("Same literal fact", project=None)

    preview = preview_bootstrap_profile(
        manifest({"content": "Same literal fact", "project": "Cars"})
    )
    result = import_bootstrap_profile(
        manifest({"content": "Same literal fact", "project": "Cars"})
    )

    assert preview["counts"]["ready"] == 1
    assert result["counts"]["imported"] == 1
    assert {(row[1], row[0]) for row in memory_rows()} == {
        (None, "Same literal fact"),
        ("Cars", "Same literal fact"),
    }


def test_forced_insert_failure_rolls_back_complete_batch(clean_db):
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_second_profile_entry
            BEFORE INSERT ON memories
            WHEN NEW.content = 'Second profile entry'
            BEGIN
                SELECT RAISE(ABORT, 'forced profile insert failure');
            END
            """
        )

    with pytest.raises(BootstrapProfileStorageError, match="could not import"):
        import_bootstrap_profile(
            manifest(
                {"content": "First profile entry", "project": None},
                {"content": "Second profile entry", "project": "MootOS"},
            )
        )

    assert memory_rows() == []


def test_manifest_limits_are_enforced_before_import(clean_db):
    with pytest.raises(BootstrapProfileValidationError, match="between 1 and 50"):
        preview_bootstrap_profile(manifest())

    oversized = "x" * 10_001
    with pytest.raises(BootstrapProfileValidationError, match="10,000"):
        import_bootstrap_profile(
            manifest({"content": oversized, "project": None})
        )

    too_many = manifest(
        *(
            {"content": f"Profile fact {index}", "project": None}
            for index in range(51)
        )
    )
    with pytest.raises(BootstrapProfileValidationError, match="between 1 and 50"):
        import_bootstrap_profile(too_many)

    assert memory_rows() == []
