"""Fixed-source currentness tests; no eligibility or real execution."""

import ast
import dataclasses
import hashlib
import inspect
import json
import sqlite3

import pytest

from backend.continuous_builder import gpf_launch_candidate_binding as source
from backend.continuous_builder import gpf_launch_facts as facts
from test_continuous_builder_gpf_launch_candidate_binding import (  # noqa
    candidate as binding_candidate,  # noqa: F401
    canonical, reseal,
)
from test_continuous_builder_gpf_launch_preparation import _event


@pytest.fixture
def sources(binding_candidate):  # noqa: F811
    args, path, store, inputs, database = binding_candidate
    event = _event(1, "job_created", args["job_id"])
    store.append_event(event)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE builder_events "
                   "(blueprint_id TEXT, blueprint_version TEXT, value TEXT)")
        db.execute("CREATE TABLE builder_attempts (attempt_id TEXT, "
                   "blueprint_id TEXT, blueprint_version TEXT)")
        db.execute("CREATE TABLE builder_leases "
                   "(attempt_id TEXT, value TEXT)")
    record, _ = source.assign_launch_candidate(**args)
    return args, path, store, inputs, database, record, event


def capture(sources):
    args, _, _, _, _, record, _ = sources
    return facts.capture_launch_facts(
        job_id=record.job_id, request_id=record.request_id,
        request_bytes=args["request_bytes"])


def test_stable_facts_and_fresh_revalidation(sources):
    record = capture(sources)
    refreshed = facts.revalidate_launch_facts(
        record, request_bytes=sources[0]["request_bytes"])
    assert record.source_tokens == refreshed.source_tokens
    assert refreshed is not record
    assert record.binding_sha256 == sources[5].binding_sha256
    for flag in source._FLAGS:
        assert getattr(record, flag) is False
        assert refreshed.to_dict()[flag] is False
    body = record.to_dict()
    digest = body.pop("facts_sha256")
    assert digest == hashlib.sha256(canonical(body)).hexdigest()
    assert not hasattr(record, "launch_ready")


@pytest.mark.parametrize("kind", ["binding", "gpd", "product", "policy"])
def test_source_token_change_rejected(sources, monkeypatch, kind):
    old = capture(sources)
    args, path, store, _, database, _, event = sources
    if kind == "binding":
        body = json.loads(path.read_bytes())
        body["created_at"] = "2026-09-09T00:00:00+00:00"
        path.write_bytes(reseal(body, "binding_sha256"))
    elif kind == "gpd":
        store.append_event(_event(2, "job_admitted", args["job_id"],
                                  event.event_digest))
    elif kind == "product":
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO builder_events VALUES (?,?,?)",
                       ("blueprint_gpf4", "1", "changed"))
    else:
        monkeypatch.setattr(facts, "_policy_token", lambda: "c" * 64)
    with pytest.raises(facts.LaunchFactsStale) as result:
        facts.revalidate_launch_facts(old, request_bytes=args["request_bytes"])
    assert result.value.facts_stale is True


def test_change_during_snapshot_rejected(sources, monkeypatch):
    original = facts._identity
    args, _, store, _, _, _, event = sources

    def change(bound, raw):
        result = original(bound, raw)
        store.append_event(_event(2, "job_admitted", args["job_id"],
                                  event.event_digest))
        return result

    monkeypatch.setattr(facts, "_identity", change)
    with pytest.raises(facts.LaunchFactsStale):
        capture(sources)


@pytest.mark.parametrize("field,value", [
    ("allowed_scope_sha256", "0" * 64),
    ("admitted_capability_sha256", "0" * 64),
    ("request_sha256", "0" * 64),
    ("header_sha256", "0" * 64),
    ("attempt_id", "other_attempt"),
    ("source_tokens", ("0" * 64,) * 4),
])
def test_caller_modified_resealed_facts_rejected(sources, field, value):
    old = capture(sources)
    values = {f.name: getattr(old, f.name) for f in dataclasses.fields(old)}
    values[field] = value
    body = dict(values, **{flag: False for flag in source._FLAGS})
    body.pop("facts_sha256")
    values["facts_sha256"] = hashlib.sha256(canonical(body)).hexdigest()
    forged = facts.TrustedLaunchFacts(**values)
    with pytest.raises(facts.LaunchFactsStale):
        facts.revalidate_launch_facts(
            forged, request_bytes=sources[0]["request_bytes"])


def test_missing_binding_fails_closed(sources):
    sources[1].unlink()
    with pytest.raises(facts.LaunchFactsError):
        capture(sources)


def test_new_reservation_invalidates_snapshot(sources):
    from backend.continuous_builder.gpe_protocol import create_worker_request
    from backend.continuous_builder.gpf_dispatch_reservation import (
        create_dispatch_reservation,
    )
    old = capture(sources)
    request = create_worker_request(**sources[3])
    sources[2].write_dispatch_reservation(create_dispatch_reservation(
        request=request))
    with pytest.raises(facts.LaunchFactsStale):
        facts.revalidate_launch_facts(
            old, request_bytes=sources[0]["request_bytes"])


def test_source_corruption_invalidates_snapshot(sources):
    old = capture(sources)
    job = sources[2].root / "jobs" / old.job_id
    (job / "events.jsonl").write_bytes(b"malformed\n")
    with pytest.raises(facts.LaunchFactsStale):
        facts.revalidate_launch_facts(
            old, request_bytes=sources[0]["request_bytes"])


def test_wrong_product_membership_blocks_capture(sources):
    with sqlite3.connect(sources[4]) as db:
        db.execute("UPDATE builder_slices SET slice_version='other'")
    with pytest.raises(facts.LaunchFactsError):
        capture(sources)


def test_product_wal_change_invalidates_snapshot(sources):
    with sqlite3.connect(sources[4]) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("INSERT INTO builder_events VALUES (?,?,?)",
                   ("blueprint_gpf4", "1", "initial WAL row"))
        db.commit()
        old = capture(sources)
        db.execute("INSERT INTO builder_events VALUES (?,?,?)",
                   ("blueprint_gpf4", "1", "new WAL row"))
        db.commit()
        with pytest.raises(facts.LaunchFactsStale):
            facts.revalidate_launch_facts(
                old, request_bytes=sources[0]["request_bytes"])


@pytest.mark.parametrize("argument", ["root", "store", "correlation_verifier"])
def test_no_source_callback_or_root_parameter(sources, argument):
    record = sources[5]
    with pytest.raises(TypeError):
        facts.capture_launch_facts(
            job_id=record.job_id, request_id=record.request_id,
            request_bytes=sources[0]["request_bytes"], **{argument: object()})


def test_transitive_import_closure_excludes_execution_stacks():
    from pathlib import Path
    root = Path(inspect.getfile(facts)).parent
    pending = ["gpf_launch_facts"]
    seen = set()
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        for node in ast.walk(ast.parse((root / (module + ".py")).read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                if node.module:
                    pending.append(node.module)
                else:
                    pending.extend(alias.name for alias in node.names)
    assert seen == {
        "gpf_launch_facts", "gpf_launch_candidate_binding",
        "gpc_trusted_admission_core", "trusted_policy", "paths", "text_safety",
    }


def test_product_lease_change_invalidates_snapshot(sources):
    with sqlite3.connect(sources[4]) as db:
        db.execute("INSERT INTO builder_attempts VALUES (?,?,?)",
                   ("product_attempt", "blueprint_gpf4", "1"))
        db.commit()
        old = capture(sources)
        db.execute("INSERT INTO builder_leases VALUES (?,?)",
                   ("product_attempt", "lease_changed"))
        db.commit()
    with pytest.raises(facts.LaunchFactsStale):
        facts.revalidate_launch_facts(
            old, request_bytes=sources[0]["request_bytes"])


def test_real_product_schema_projection(sources):
    from backend.migrations import _migration_006_continuous_builder_state
    with sqlite3.connect(sources[4]) as db:
        for table in ("builder_leases", "builder_attempts", "builder_events",
                      "builder_slices", "builder_blueprints"):
            db.execute("DROP TABLE " + table)
        _migration_006_continuous_builder_state(db)
        db.execute("INSERT INTO builder_blueprints VALUES (?,?,?,?,?,?,?,?)",
                   ("blueprint_gpf4", "1", "b" * 64, "{}", "approval",
                    "human", 1, "2026-09-07T00:00:00+00:00"))
        db.execute("INSERT INTO builder_slices VALUES (?,?,?,?,?)",
                   ("blueprint_gpf4", "1", "slice_gpf4", "1", "{}"))
    assert capture(sources).launch_authorized is False
