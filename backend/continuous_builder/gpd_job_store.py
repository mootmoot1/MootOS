"""GP-D durable file-backed job ledger store.

Reuses filesystem durability (atomic rename + append-only JSONL) so GP-D
does **not** require a SQLite schema migration in this phase. Process-local
memory alone is never claimed complete: callers must supply a ledger root.

Layout::
    <root>/jobs/<job_id>/header.json
    <root>/jobs/<job_id>/events.jsonl
    <root>/jobs/<job_id>/attempts.jsonl
    <root>/jobs/<job_id>/leases.jsonl
    <root>/jobs/<job_id>/heartbeats.jsonl
    <root>/jobs/<job_id>/checkpoints.jsonl
    <root>/jobs/<job_id>/side_effects.jsonl
    <root>/jobs/<job_id>/reconciliations.jsonl
    <root>/jobs/<job_id>/attempts/<attempt_id>/dispatch_reservation.json
    <root>/jobs/<job_id>/attempts/<attempt_id>/supervisor_decisions.jsonl

No GitHub / provider / worker execution occurs here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .gpd_attempt_ledger import AttemptRecord, create_attempt_record
from .gpd_checkpoint import CheckpointContract, create_checkpoint_contract
from .gpd_heartbeat_lease import (
    HeartbeatEvidence,
    LeaseRecord,
    create_heartbeat_evidence,
    create_lease_record,
)
from .gpd_job_events import JobEvent, JobEventError, create_job_event
from .gpd_job_header import DurableJobHeader, JobHeaderError, create_durable_job_header
from .gpd_side_effect import (
    ReconciliationRecord,
    SideEffectIdentity,
    create_reconciliation_record,
    create_side_effect_identity,
    detect_duplicate_side_effect_identity,
)
from .gpa_eval_schema import canonical_json


class JobStoreError(RuntimeError):
    """Raised when durable ledger IO or integrity fails closed."""


def _job_dir(root, job_id):
    path = Path(root) / "jobs" / job_id
    return path


def _atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = canonical_json(payload)
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.write(b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _append_jsonl(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json(payload) + b"\n"
    with open(path, "ab") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _read_json(path):
    path = Path(path)
    if not path.is_file():
        raise JobStoreError(f"missing durable file: {path}")
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def _read_jsonl(path):
    path = Path(path)
    if not path.is_file():
        return []
    rows = []
    with open(path, "rb") as handle:
        for raw in handle.splitlines() if False else handle:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


class JobLedgerStore:
    """Durable control-plane ledger. Not an execution engine."""

    def __init__(self, root):
        if not isinstance(root, (str, Path)) or not str(root):
            raise JobStoreError("ledger root is required")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_header(self, header):
        if not isinstance(header, DurableJobHeader):
            raise JobStoreError("header invalid")
        job_dir = _job_dir(self.root, header.job_id)
        header_path = job_dir / "header.json"
        if header_path.exists():
            existing = self.load_header(header.job_id)
            if existing.header_sha256 != header.header_sha256:
                raise JobStoreError("refusing to mutate durable job header")
            return existing
        _atomic_write_json(header_path, header.to_dict())
        return header

    def load_header(self, job_id):
        data = _read_json(_job_dir(self.root, job_id) / "header.json")
        data = dict(data)
        digest = data.pop("header_sha256")
        header = create_durable_job_header(**{
            k: tuple(v) if k in (
                "approved_scope_ceiling", "forbidden_scope",
                "admitted_capability_ids", "required_gates",
            ) and isinstance(v, list) else v
            for k, v in data.items()
        })
        if header.header_sha256 != digest:
            raise JobStoreError("header digest drift on load")
        return header

    def append_event(self, event):
        if not isinstance(event, JobEvent):
            raise JobStoreError("event invalid")
        header = self.load_header(event.job_id)
        if event.job_id != header.job_id:
            raise JobStoreError("event job binding mismatch")
        existing = self.load_events(event.job_id)
        ids = {item.event_id for item in existing}
        if event.event_id in ids:
            raise JobStoreError("duplicate durable event identity")
        expected_seq = len(existing) + 1
        if event.sequence != expected_seq:
            raise JobStoreError("sequence violation")
        prev = None if not existing else existing[-1].event_digest
        if event.previous_event_digest != prev:
            raise JobStoreError("event digest chain break")
        path = _job_dir(self.root, event.job_id) / "events.jsonl"
        _append_jsonl(path, event.to_dict())
        return event

    def load_events(self, job_id):
        rows = _read_jsonl(_job_dir(self.root, job_id) / "events.jsonl")
        events = []
        for row in rows:
            data = dict(row)
            digest = data.pop("event_digest")
            event = create_job_event(**data)
            if event.event_digest != digest:
                raise JobStoreError("event digest drift on load")
            events.append(event)
        return events

    def append_attempt(self, attempt):
        if not isinstance(attempt, AttemptRecord):
            raise JobStoreError("attempt invalid")
        from .gpd_attempt_ledger import assert_new_attempt_identity
        existing = self.load_attempts(attempt.job_id)
        assert_new_attempt_identity(existing, attempt)
        path = _job_dir(self.root, attempt.job_id) / "attempts.jsonl"
        _append_jsonl(path, attempt.to_dict())
        return attempt

    def load_attempts(self, job_id):
        rows = _read_jsonl(_job_dir(self.root, job_id) / "attempts.jsonl")
        out = []
        for row in rows:
            data = dict(row)
            digest = data.pop("attempt_sha256")
            attempt = create_attempt_record(**data)
            if attempt.attempt_sha256 != digest:
                raise JobStoreError("attempt digest drift on load")
            out.append(attempt)
        return out

    def append_lease(self, lease):
        if not isinstance(lease, LeaseRecord):
            raise JobStoreError("lease invalid")
        from .gpd_heartbeat_lease import assert_single_active_lease
        existing = self.load_leases(lease.job_id)
        probe = list(existing) + [lease]
        assert_single_active_lease(probe, lease.job_id)
        path = _job_dir(self.root, lease.job_id) / "leases.jsonl"
        _append_jsonl(path, lease.to_dict())
        return lease

    def load_leases(self, job_id):
        rows = _read_jsonl(_job_dir(self.root, job_id) / "leases.jsonl")
        out = []
        for row in rows:
            data = dict(row)
            digest = data.pop("lease_sha256")
            lease = create_lease_record(**data)
            if lease.lease_sha256 != digest:
                raise JobStoreError("lease digest drift on load")
            out.append(lease)
        return out

    def append_heartbeat(self, heartbeat):
        if not isinstance(heartbeat, HeartbeatEvidence):
            raise JobStoreError("heartbeat invalid")
        path = _job_dir(self.root, heartbeat.job_id) / "heartbeats.jsonl"
        _append_jsonl(path, heartbeat.to_dict())
        return heartbeat

    def load_heartbeats(self, job_id):
        rows = _read_jsonl(_job_dir(self.root, job_id) / "heartbeats.jsonl")
        out = []
        for row in rows:
            data = dict(row)
            digest = data.pop("heartbeat_sha256")
            hb = create_heartbeat_evidence(**data)
            if hb.heartbeat_sha256 != digest:
                raise JobStoreError("heartbeat digest drift on load")
            out.append(hb)
        return out

    def append_checkpoint(self, checkpoint):
        if not isinstance(checkpoint, CheckpointContract):
            raise JobStoreError("checkpoint invalid")
        path = _job_dir(self.root, checkpoint.job_id) / "checkpoints.jsonl"
        _append_jsonl(path, checkpoint.to_dict())
        return checkpoint

    def load_checkpoints(self, job_id):
        rows = _read_jsonl(_job_dir(self.root, job_id) / "checkpoints.jsonl")
        out = []
        for row in rows:
            data = dict(row)
            digest = data.pop("checkpoint_sha256")
            notes = data.get("notes", [])
            digests = data.get("evidence_digests", [])
            data["notes"] = tuple(notes)
            data["evidence_digests"] = tuple(digests)
            cp = create_checkpoint_contract(**data)
            if cp.checkpoint_sha256 != digest:
                raise JobStoreError("checkpoint digest drift on load")
            out.append(cp)
        return out

    def append_side_effect(self, side_effect):
        if not isinstance(side_effect, SideEffectIdentity):
            raise JobStoreError("side_effect invalid")
        existing = self.load_side_effects(side_effect.job_id)
        detect_duplicate_side_effect_identity(existing, side_effect)
        path = _job_dir(self.root, side_effect.job_id) / "side_effects.jsonl"
        _append_jsonl(path, side_effect.to_dict())
        return side_effect

    def load_side_effects(self, job_id):
        rows = _read_jsonl(_job_dir(self.root, job_id) / "side_effects.jsonl")
        out = []
        for row in rows:
            data = dict(row)
            digest = data.pop("side_effect_sha256")
            se = create_side_effect_identity(**data)
            if se.side_effect_sha256 != digest:
                raise JobStoreError("side_effect digest drift on load")
            out.append(se)
        return out

    def append_reconciliation(self, record):
        if not isinstance(record, ReconciliationRecord):
            raise JobStoreError("reconciliation invalid")
        path = _job_dir(self.root, record.job_id) / "reconciliations.jsonl"
        _append_jsonl(path, record.to_dict())
        return record

    def load_reconciliations(self, job_id):
        rows = _read_jsonl(
            _job_dir(self.root, job_id) / "reconciliations.jsonl"
        )
        out = []
        for row in rows:
            data = dict(row)
            digest = data.pop("reconciliation_sha256")
            rec = create_reconciliation_record(**data)
            if rec.reconciliation_sha256 != digest:
                raise JobStoreError("reconciliation digest drift on load")
            out.append(rec)
        return out

    # -- GP-F1: durable dispatch reservation / replay prevention --------
    #
    # One reservation slot per (job_id, attempt_id), mirroring
    # write_header's own idempotent-write idiom: an identical reservation
    # already on disk is a no-op (replay); a differing one is refused
    # (fail closed), never silently overwritten. This is the smallest
    # extension of the existing durable ledger needed to answer "has this
    # exact WorkerRequest already been dispatched for this attempt?" -- it
    # grants no launch authority on its own.

    def _dispatch_reservation_path(self, job_id, attempt_id):
        return (
            _job_dir(self.root, job_id)
            / "attempts" / attempt_id / "dispatch_reservation.json"
        )

    def write_dispatch_reservation(self, reservation):
        from .gpf_dispatch_reservation import (
            DispatchReservation,
            classify_reservation_attempt,
        )

        if not isinstance(reservation, DispatchReservation):
            raise JobStoreError("dispatch reservation invalid")
        path = self._dispatch_reservation_path(
            reservation.job_id, reservation.attempt_id
        )
        if path.exists():
            existing = self.load_dispatch_reservation(
                reservation.job_id, reservation.attempt_id
            )
            if classify_reservation_attempt(existing, reservation) == "conflict":
                raise JobStoreError(
                    "refusing to overwrite a conflicting dispatch reservation"
                )
            return existing, "replay"
        _atomic_write_json(path, reservation.to_dict())
        return reservation, "new"

    def load_dispatch_reservation(self, job_id, attempt_id):
        from .gpf_dispatch_reservation import (
            reseal_dispatch_reservation_from_storage,
        )

        path = self._dispatch_reservation_path(job_id, attempt_id)
        if not path.is_file():
            return None
        data = dict(_read_json(path))
        digest = data.pop("reservation_sha256")
        reservation = reseal_dispatch_reservation_from_storage(**data)
        if reservation.reservation_sha256 != digest:
            raise JobStoreError("dispatch reservation digest drift on load")
        return reservation

    # -- GP-F3: supervisor control decisions (append-only evidence) -----
    #
    # A SupervisorControlDecision is a pure re-derivation of current
    # truth (see gpf_supervisor.py) -- unlike the dispatch reservation,
    # it is not a one-time fact, so it is appended, not idempotently
    # written: each evaluation is its own history entry, mirroring how
    # heartbeats/checkpoints are recorded. Restart never has to trust an
    # old decision -- gpf_supervisor.evaluate_supervisor_control() can
    # always recompute a fresh one from the same authoritative evidence.

    def append_supervisor_decision(self, decision):
        from .gpf_supervisor import SupervisorControlDecision

        if not isinstance(decision, SupervisorControlDecision):
            raise JobStoreError("supervisor decision invalid")
        path = (
            _job_dir(self.root, decision.job_id)
            / "attempts" / decision.attempt_id / "supervisor_decisions.jsonl"
        )
        _append_jsonl(path, decision.to_dict())
        return decision

    def load_supervisor_decisions(self, job_id, attempt_id):
        from .gpf_supervisor import reseal_supervisor_decision_from_storage

        path = (
            _job_dir(self.root, job_id)
            / "attempts" / attempt_id / "supervisor_decisions.jsonl"
        )
        rows = _read_jsonl(path)
        out = []
        for row in rows:
            data = dict(row)
            digest = data.pop("decision_sha256")
            decision = reseal_supervisor_decision_from_storage(**data)
            if decision.decision_sha256 != digest:
                raise JobStoreError("supervisor decision digest drift on load")
            out.append(decision)
        return out
