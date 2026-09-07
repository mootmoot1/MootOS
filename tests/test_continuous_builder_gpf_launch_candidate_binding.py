"""Offline assignment tests: only temporary sources, no live stores or keys."""

import ast
import hashlib
import inspect
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.continuous_builder import gpf_launch_candidate_binding as binding
from backend.continuous_builder.gpd_attempt_ledger import create_attempt_record
from backend.continuous_builder.gpd_job_store import JobLedgerStore
from backend.continuous_builder.gpe_protocol import create_worker_request
from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
)
from backend.continuous_builder.trusted_policy_enforcement import (
    evaluate_changed_paths_against_tcb, OUTCOME_FORBIDDEN,
)
from test_continuous_builder_gpf_launch_preparation import _build_inputs, TS


def canonical(body):
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode()


def reseal(body, field="digest"):
    body = dict(body)
    body.pop(field, None)
    body[field] = hashlib.sha256(canonical(body)).hexdigest()
    return canonical(body)


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    inputs = _build_inputs(tmp_path)
    request = create_worker_request(**inputs)
    root = tmp_path / "authority"
    store = JobLedgerStore(root)
    store.write_header(inputs["header"])
    store.append_attempt(inputs["attempt"])
    database = tmp_path / "product.sqlite"
    with sqlite3.connect(database) as db:
        db.executescript('''
            CREATE TABLE builder_blueprints (
                blueprint_id TEXT, blueprint_version TEXT,
                content_digest TEXT);
            CREATE TABLE builder_slices (
                blueprint_id TEXT, blueprint_version TEXT,
                slice_id TEXT, slice_version TEXT);
        ''')
        db.execute("INSERT INTO builder_blueprints VALUES (?,?,?)",
                   ("blueprint_gpf4", "1", "b" * 64))
        db.execute("INSERT INTO builder_slices VALUES (?,?,?,?)",
                   ("blueprint_gpf4", "1", "slice_gpf4", "1"))
    monkeypatch.setattr(binding, "_AUTHORITATIVE_ROOT", root)
    monkeypatch.setattr(binding, "_PRODUCT_DATABASE", database)
    args = dict(job_id=request.job_id, attempt_id=request.attempt_id,
                request_bytes=request.canonical_bytes(),
                blueprint_id="blueprint_gpf4", blueprint_version="1",
                slice_id="slice_gpf4", created_at=TS)
    path = (root / "launch_bindings" / request.job_id /
            (request.request_id + ".json"))
    return args, path, store, inputs, database


def load(args):
    request = json.loads(args["request_bytes"])
    return binding.load_launch_candidate_binding(
        job_id=args["job_id"], request_id=request["request_id"])


def test_initial_binding_is_durable_and_zero_authority(candidate):
    args, path, *_ = candidate
    record, status = binding.assign_launch_candidate(**args)
    assert status == "new"
    assert load(args) == record
    assert path.read_bytes() == canonical(record.to_dict())
    assert record.blueprint_id == args["blueprint_id"]
    assert record.slice_version == "1"
    assert record.request_sha256 == json.loads(args["request_bytes"])["digest"]
    for flag in binding._FLAGS:
        assert getattr(record, flag) is False
        assert record.to_dict()[flag] is False
    assert path.stat().st_mode & 0o777 == 0o600


def test_exact_replay_is_idempotent(candidate):
    args, path, *_ = candidate
    first, _ = binding.assign_launch_candidate(**args)
    original_inode = path.stat().st_ino
    second, status = binding.assign_launch_candidate(**args)
    assert second == first and status == "replay"
    assert path.stat().st_ino == original_inode


@pytest.mark.parametrize("change", ["created_at", "request"])
def test_conflict_preserves_first_assignment(candidate, change):
    args, path, *_ = candidate
    binding.assign_launch_candidate(**args)
    original = path.read_bytes()
    altered = dict(args)
    if change == "created_at":
        altered["created_at"] = "2026-09-07T00:00:00+00:00"
    else:
        body = json.loads(args["request_bytes"])
        body["task_goal"] = "different request packet"
        altered["request_bytes"] = reseal(body)
    for _ in range(2):
        with pytest.raises(binding.LaunchBindingError):
            binding.assign_launch_candidate(**altered)
        assert path.read_bytes() == original


@pytest.mark.parametrize("field,value", [
    ("job_id", "other_job"), ("attempt_id", "other_attempt"),
    ("header_sha256", "c" * 64), ("attempt_sha256", "c" * 64),
    ("request_id", "other_request"),
    ("admission_ref", ["other_admission", "c" * 64]),
    ("task_contract_ref", ["other_contract", "c" * 64]),
    ("execution_plan_ref", ["other_plan", "c" * 64]),
    ("allowed_scope", ["backend/other.py"]),
    ("admitted_capability_ids", ["cb.credentials"]),
    ("budget_ceilings", [999999, None, None, None]),
    ("human_gates", []), ("protocol_version", "other"),
    ("launch_authorized", True),
])
def test_invalid_request_binding_rejected(candidate, field, value):
    args, path, *_ = candidate
    body = json.loads(args["request_bytes"])
    body[field] = value
    args["request_bytes"] = reseal(body)
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(**args)
    assert not path.exists()


def test_tampered_request_digest_rejected(candidate):
    args, path, *_ = candidate
    body = json.loads(args["request_bytes"])
    body["task_goal"] = "tamper"
    args["request_bytes"] = canonical(body)
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(**args)
    assert not path.exists()


def test_superseded_attempt_rejected(candidate):
    args, path, store, inputs, _ = candidate
    attempt = inputs["attempt"]
    store.append_attempt(create_attempt_record(
        attempt_id="retry_attempt", job_id=attempt.job_id,
        attempt_number=2, owner_id=attempt.owner_id,
        started_at=TS, status="started", prior_attempt_id=attempt.attempt_id,
        header_sha256=attempt.header_sha256))
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(**args)
    assert not path.exists()


@pytest.mark.parametrize("source", ["header", "attempt"])
def test_bad_authoritative_source_rejected(candidate, source):
    args, path, store, *_ = candidate
    name = "header.json" if source == "header" else "attempts.jsonl"
    target = store.root / "jobs" / args["job_id"] / name
    body = json.loads(target.read_bytes())
    body["job_id"] = "different_job"
    field = "header_sha256" if source == "header" else "attempt_sha256"
    target.write_bytes(reseal(body, field))
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(**args)
    assert not path.exists()


@pytest.mark.parametrize("field", [
    "blueprint_id", "blueprint_version", "slice_id",
])
def test_wrong_product_relationship_rejected(candidate, field):
    args, path, *_ = candidate
    args[field] = "missing"
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(**args)
    assert not path.exists()


def test_existing_other_slice_cannot_override_request(candidate):
    args, path, _, _, database = candidate
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO builder_slices VALUES (?,?,?,?)",
                   ("blueprint_gpf4", "1", "other_slice", "1"))
    args["slice_id"] = "other_slice"
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(**args)
    assert not path.exists()


@pytest.mark.parametrize("field", ["job_id", "attempt_id", "slice_id"])
@pytest.mark.parametrize("bad", ["../escape", "/tmp/escape", "a/b", "..", ""])
def test_path_input_rejected(candidate, field, bad):
    args, *_ = candidate
    args[field] = bad
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(**args)


@pytest.mark.parametrize("target", ["root", "bindings", "job", "record", "db"])
def test_symlink_escape_rejected(candidate, monkeypatch, tmp_path, target):
    args, path, store, _, database = candidate
    if target == "root":
        link = tmp_path / "root-link"
        link.symlink_to(store.root, target_is_directory=True)
        monkeypatch.setattr(binding, "_AUTHORITATIVE_ROOT", link)
    elif target == "db":
        link = tmp_path / "db-link"
        link.symlink_to(database)
        monkeypatch.setattr(binding, "_PRODUCT_DATABASE", link)
    else:
        binding.assign_launch_candidate(**args)
        selected = {"bindings": path.parent.parent,
                    "job": path.parent, "record": path}[target]
        moved = selected.with_name(selected.name + "-moved")
        selected.rename(moved)
        selected.symlink_to(moved, target_is_directory=target != "record")
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(**args)


@pytest.mark.parametrize("bad", [
    "json", "digest", "flag", "extra", "identity",
])
def test_malformed_persisted_binding_rejected(candidate, bad):
    args, path, *_ = candidate
    binding.assign_launch_candidate(**args)
    body = json.loads(path.read_bytes())
    if bad == "json":
        raw = b"{"
    elif bad == "digest":
        body["binding_sha256"] = "0" * 64
        raw = canonical(body)
    else:
        field, value = {"flag": ("launch_authorized", True),
                        "extra": ("extra", 1),
                        "identity": ("job_id", "other_job")}[bad]
        body[field] = value
        raw = reseal(body, "binding_sha256")
    path.write_bytes(raw)
    with pytest.raises(binding.LaunchBindingError):
        load(args)
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(**args)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("kind", ["directory", "fifo", "hardlink"])
def test_unexpected_file_type_rejected(candidate, kind):
    args, path, *_ = candidate
    binding.assign_launch_candidate(**args)
    if kind == "hardlink":
        os.link(path, path.with_suffix(".alias"))
    else:
        path.unlink()
        if kind == "directory":
            path.mkdir()
        else:
            os.mkfifo(path)
    with pytest.raises(binding.LaunchBindingError):
        load(args)


@pytest.mark.parametrize("argument", [
    "root", "database_path", "correlation_verifier",
])
def test_caller_cannot_substitute_sources_or_callback(candidate, argument):
    args, *_ = candidate
    args[argument] = lambda *a: True
    with pytest.raises(TypeError):
        binding.assign_launch_candidate(**args)


def test_unconfigured_source_fails_closed(candidate, monkeypatch):
    args, path, *_ = candidate
    monkeypatch.setattr(binding, "_AUTHORITATIVE_ROOT", None)
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(**args)
    assert not path.exists()


def test_concurrent_conflicting_publish_has_one_winner(candidate):
    args, path, *_ = candidate
    other = dict(args, created_at="2026-09-08T00:00:00+00:00")

    def assign(values):
        try:
            return binding.assign_launch_candidate(**values)[0]
        except binding.LaunchBindingError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(assign, (args, other)))
    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    assert load(args) == winners[0]
    assert path.stat().st_nlink == 1


def test_durable_publish_failure_returns_no_binding(candidate, monkeypatch):
    args, path, *_ = candidate

    def fail(*args):
        raise OSError("synthetic fsync failure")

    monkeypatch.setattr(binding.os, "fsync", fail)
    with pytest.raises(binding.LaunchBindingError):
        binding.assign_launch_candidate(**args)
    assert not path.exists()


def test_tcb_and_minimal_import_closure():
    path = "backend/continuous_builder/gpf_launch_candidate_binding.py"
    component = create_mootos_tcb_registry_v1().component_for_path(path)
    assert component.component_id == "cb_launch_assignment_authority"
    assert component.change_policy == "human_only"
    result = evaluate_changed_paths_against_tcb((path,))
    assert result.outcome == OUTCOME_FORBIDDEN
    imports = set()
    for node in ast.walk(ast.parse(inspect.getsource(binding))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0
            imports.add(node.module)
    assert imports <= {
        "hashlib", "json", "os", "re", "secrets", "sqlite3", "stat",
        "contextlib", "dataclasses", "datetime", "pathlib",
    }
