"""Prove migration 006/007 actually create the indexes, foreign keys, and
unique constraints the schema doc claims -- not just the right column
names. ``backend.migrations._verify_schema`` only checks column
presence (see backend/migrations.py); these tests independently query
SQLite's own PRAGMAs against a freshly migrated, disposable database so
a schema regression that silently dropped or mis-scoped a constraint
would be caught even though it wouldn't touch any column name."""

import sqlite3

from backend.migrations import run_migrations


def _index_columns(connection, table, index_name):
    for row in connection.execute(f"PRAGMA index_list({table})").fetchall():
        if row["name"] == index_name:
            return [
                col["name"] for col in connection.execute(
                    f"PRAGMA index_info({index_name})"
                ).fetchall()
            ], bool(row["unique"])
    return None, None


def _foreign_keys(connection, table):
    return {
        (row["table"], row["from"], row["to"])
        for row in connection.execute(
            f"PRAGMA foreign_key_list({table})"
        ).fetchall()
    }


def test_active_lease_index_is_scoped_by_full_blueprint_identity(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        columns, unique = _index_columns(
            connection, "builder_leases", "idx_builder_active_lease_identity",
        )
    finally:
        connection.close()
    assert unique is True
    assert columns == [
        "blueprint_id", "blueprint_version", "slice_id", "slice_version",
    ]


def test_stale_slice_only_lease_index_no_longer_exists(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        names = {
            row["name"] for row in connection.execute(
                "PRAGMA index_list(builder_leases)"
            ).fetchall()
        }
    finally:
        connection.close()
    assert "idx_builder_active_lease" not in names


def test_builder_events_attempt_id_has_a_real_foreign_key(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        foreign_keys = _foreign_keys(connection, "builder_events")
    finally:
        connection.close()
    assert ("builder_attempts", "attempt_id", "attempt_id") in foreign_keys
    assert (
        "builder_slices", "blueprint_id", "blueprint_id",
    ) in foreign_keys


def test_builder_events_attempt_fk_rejects_a_dangling_attempt_id(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    blueprint_digest = "d" * 64
    dependency_digest = "e" * 64
    event_digest = "f" * 64
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute(
            "INSERT INTO builder_blueprints VALUES (?,?,?,?,?,?,?,?)",
            ("bp", "v1", blueprint_digest, "{}", "a", "human", 0, "t"),
        )
        connection.execute(
            "INSERT INTO builder_slices VALUES (?,?,?,?,?)",
            ("bp", "v1", "CB-001", "1", "{}"),
        )
        try:
            connection.execute(
                "INSERT INTO builder_events VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "e1", "bp", "v1", blueprint_digest, "CB-001", "1", 1,
                    None, None, "idea", "r", "actor", 0, "missing-attempt",
                    dependency_digest, "pv", "2026-01-01T00:00:00+00:00",
                    event_digest,
                ),
            )
            connection.commit()
            raised = False
        except sqlite3.IntegrityError:
            connection.rollback()
            raised = True
    finally:
        connection.close()
    assert raised is True


def test_lease_reconciliation_table_has_expected_foreign_keys(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        foreign_keys = _foreign_keys(
            connection, "builder_lease_reconciliations",
        )
    finally:
        connection.close()
    assert ("builder_leases", "lease_id", "lease_id") in foreign_keys
    assert ("builder_attempts", "attempt_id", "attempt_id") in foreign_keys


def test_builder_lease_columns_include_full_identity(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    connection = sqlite3.connect(path)
    try:
        columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(builder_leases)"
            ).fetchall()
        }
    finally:
        connection.close()
    assert {"blueprint_id", "blueprint_version", "slice_version"} <= columns
