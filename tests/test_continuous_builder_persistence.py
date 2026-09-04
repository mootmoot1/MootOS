"""Tests for the Continuous Builder migration and blueprint store."""

import sqlite3

import pytest

from backend.continuous_builder.blueprint_parser import parse_blueprint
from backend.continuous_builder.blueprint_store import (
    BlueprintStoreError,
    store_blueprint,
)
from backend.continuous_builder.chief_builder import BlueprintApprovalEvidence
from backend.migrations import LATEST_SCHEMA_VERSION, run_migrations
from test_continuous_builder_blueprint import make_blueprint


def snapshot():
    parsed = parse_blueprint(make_blueprint().canonical_bytes())
    approval = BlueprintApprovalEvidence(
        "approval-1", parsed.content_sha256, "human", True,
    )
    return parsed, approval


def test_migration_creates_builder_schema_on_isolated_database(tmp_path):
    path = tmp_path / "mootos.db"
    assert run_migrations(path) == LATEST_SCHEMA_VERSION == 6
    connection = sqlite3.connect(path)
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    connection.close()
    assert "builder_blueprints" in tables
    assert "builder_events" in tables


def test_blueprint_snapshot_is_immutable_and_duplicate_fails(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    parsed, approval = snapshot()
    store_blueprint(path, parsed, approval, "2026-01-01T00:00:00+00:00")
    with pytest.raises(BlueprintStoreError, match="conflicts"):
        store_blueprint(path, parsed, approval, "2026-01-01T00:00:00+00:00")
    connection = sqlite3.connect(path)
    row = connection.execute(
        "SELECT content_digest, approver_authenticated FROM builder_blueprints"
    ).fetchone()
    connection.close()
    assert row == (parsed.content_sha256, 0)


def test_store_transaction_rolls_back_on_slice_conflict(tmp_path):
    path = tmp_path / "mootos.db"
    run_migrations(path)
    parsed, approval = snapshot()
    store_blueprint(path, parsed, approval, "2026-01-01T00:00:00+00:00")
    connection = sqlite3.connect(path)
    count = connection.execute(
        "SELECT count(*) FROM builder_slices"
    ).fetchone()[0]
    assert count == 1
    connection.close()
