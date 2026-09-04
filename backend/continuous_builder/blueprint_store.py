"""Durable immutable Continuous Builder blueprint snapshots."""

import sqlite3

from backend.db import connect
from .blueprint_parser import ParsedBlueprint
from .chief_builder import BlueprintApprovalEvidence


class BlueprintStoreError(RuntimeError):
    """Raised when an immutable blueprint snapshot cannot be stored."""


def store_blueprint(database_path, parsed, approval, created_at):
    if not isinstance(parsed, ParsedBlueprint):
        raise BlueprintStoreError("parsed blueprint is required")
    if not isinstance(approval, BlueprintApprovalEvidence):
        raise BlueprintStoreError("approval evidence is required")
    if approval.blueprint_digest != parsed.content_sha256:
        raise BlueprintStoreError("approval binding mismatch")
    blueprint = parsed.blueprint
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO builder_blueprints VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (blueprint.blueprint_id, blueprint.blueprint_version,
             parsed.content_sha256, parsed.canonical_json,
             approval.approval_id, approval.supplied_approver_identity,
             int(approval.approver_authenticated), created_at),
        )
        for item in blueprint.slices:
            import json
            canonical = json.dumps(item.to_dict(), sort_keys=True,
                                   separators=(",", ":"))
            connection.execute(
                "INSERT INTO builder_slices VALUES (?, ?, ?, ?, ?)",
                (blueprint.blueprint_id, blueprint.blueprint_version,
                 item.slice_id, item.version, canonical),
            )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise BlueprintStoreError("blueprint snapshot conflicts") from error
    finally:
        connection.close()
