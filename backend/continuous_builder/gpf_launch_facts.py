"""Fresh assignment/source identity facts; NOT a launch-eligibility decision.

No cached record is authoritative. Revalidation rebuilds from fixed sources.
Tokens detect changes to observed representations, not a global transaction.
Lifecycle/admission/approval evaluation is deliberately not asserted here.
"""

import os
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from . import gpf_launch_candidate_binding as source
from .gpc_trusted_admission_core import create_gpc_policy_matrix_v1
from .trusted_policy import (
    POLICY_VERSION, create_mootos_tcb_registry_v1,
    create_trusted_policy_snapshot,
)

VERSION = "gpf-launch-source-facts-v1"
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_ROWS = 4096
_FILES = (
    ("header.json", "header_sha256", True),
    ("events.jsonl", "event_digest", True),
    ("attempts.jsonl", "attempt_sha256", True),
    ("leases.jsonl", "lease_sha256", False),
    ("heartbeats.jsonl", "heartbeat_sha256", False),
    ("checkpoints.jsonl", "checkpoint_sha256", False),
    ("side_effects.jsonl", "side_effect_sha256", False),
    ("reconciliations.jsonl", "reconciliation_sha256", False),
)


class LaunchFactsError(ValueError):
    """Missing, inconsistent or stale source facts; no authorization."""


class LaunchFactsStale(LaunchFactsError):
    """Rebuild facts; at least one bound representation no longer agrees."""

    facts_stale = True


def _check(condition, reason):
    if not condition:
        raise LaunchFactsError(reason)


def _hash(value):
    return source._digest(source._canonical(value))


def _manifest_entry(name, raw):
    return (name, raw is not None, len(raw) if raw is not None else None,
            source._digest(raw) if raw is not None else None)


def _gpd_token(bound):
    manifest = []
    attempt_ids = []
    with source._directory(source._AUTHORITATIVE_ROOT) as root, \
            source._child(root, "jobs") as jobs, \
            source._child(jobs, bound.job_id) as job:
        for name, digest_field, required in _FILES:
            try:
                raw = source._read(job, name, MAX_SOURCE_BYTES)
            except FileNotFoundError:
                _check(not required, "required GP-D source missing")
                raw = None
            manifest.append(_manifest_entry(name, raw))
            if raw is None:
                continue
            lines = raw.splitlines() if name.endswith("jsonl") else [raw]
            _check(len(lines) <= MAX_ROWS, "GP-D source row bound")
            if required:
                _check(bool(lines), "empty required GP-D source")
            previous = None
            for sequence, line in enumerate(lines, 1):
                row = source._sealed(line, digest_field)
                _check(row.get("job_id") == bound.job_id,
                       "GP-D source belongs to another job")
                if name == "attempts.jsonl":
                    attempt_ids.append(source._id(row.get("attempt_id")))
                if name == "events.jsonl":
                    _check(type(row.get("sequence")) is int and
                           row["sequence"] == sequence and
                           row.get("previous_event_digest") == previous,
                           "GP-D event chain mismatch")
                    previous = row["event_digest"]
        # Cover every attempt reservation, including newly added attempts.
        try:
            with source._child(job, "attempts") as attempts:
                directory_ids = os.listdir(attempts)
                _check(set(directory_ids) <= set(attempt_ids),
                       "unrecorded attempt directory")
                for attempt_id in sorted(set(attempt_ids)):
                    raw = None
                    if attempt_id in directory_ids:
                        with source._child(attempts, attempt_id) as attempt:
                            try:
                                raw = source._read(
                                    attempt, "dispatch_reservation.json")
                            except FileNotFoundError:
                                pass
                    if raw is not None:
                        row = source._sealed(raw, "reservation_sha256")
                        _check((row.get("job_id"), row.get("attempt_id")) ==
                               (bound.job_id, attempt_id),
                               "reservation source identity mismatch")
                    name = ("attempts/" + attempt_id +
                            "/dispatch_reservation.json")
                    manifest.append(_manifest_entry(name, raw))
        except FileNotFoundError:
            for attempt_id in sorted(set(attempt_ids)):
                name = "attempts/" + attempt_id + "/dispatch_reservation.json"
                manifest.append(_manifest_entry(name, None))
    return _hash(("gpf-gpd-sources-v1", sorted(manifest)))


def _product_token(bound):
    # Fixed configured source; no live DB helper/environment/callback imports.
    source._product(bound.blueprint_id, bound.blueprint_version,
                    bound.slice_id)
    path = Path(source._PRODUCT_DATABASE)
    with source._directory(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=parent)
        try:
            before = os.fstat(fd)
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            try:
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
                projection = []
                # Whole blueprint coverage conservatively includes dependencies
                # and other slices: no omitted dependency changes can pass.
                for table in ("builder_blueprints", "builder_slices",
                              "builder_events", "builder_attempts",
                              "builder_leases"):
                    if table == "builder_leases":
                        query = (
                            "SELECT l.* FROM builder_leases l "
                            "JOIN builder_attempts a USING (attempt_id) "
                            "WHERE a.blueprint_id=? AND "
                            "a.blueprint_version=? LIMIT ?")
                    else:
                        query = ("SELECT * FROM " + table +
                                 " WHERE blueprint_id=? AND "
                                 "blueprint_version=? LIMIT ?")
                    cursor = connection.execute(
                        query, (bound.blueprint_id, bound.blueprint_version,
                                MAX_ROWS + 1))
                    rows = cursor.fetchall()
                    _check(len(rows) <= MAX_ROWS, "product row bound")
                    columns = [item[0] for item in cursor.description]
                    projection.append((table, columns, sorted(
                        rows, key=source._canonical)))
                raw = source._canonical(projection)
                _check(len(raw) <= MAX_SOURCE_BYTES, "product byte bound")
                after = os.stat(path.name, dir_fd=parent,
                                follow_symlinks=False)
                _check((before.st_dev, before.st_ino) ==
                       (after.st_dev, after.st_ino),
                       "product database replaced")
                return _hash(("gpf-product-sources-v1", projection))
            finally:
                connection.close()
        finally:
            os.close(fd)


def _policy_token():
    return _hash(("gpf-policy-sources-v1",
                  create_mootos_tcb_registry_v1().to_dict(),
                  create_gpc_policy_matrix_v1().to_dict()))


def _tokens(bound):
    current = source.load_launch_candidate_binding(
        job_id=bound.job_id, request_id=bound.request_id)
    return (current.binding_sha256, _gpd_token(current),
            _product_token(current), _policy_token())


@dataclass(frozen=True)
class TrustedLaunchFacts:
    """Source identity/currentness evidence only; no eligibility assertion."""

    schema_version: str
    job_id: str
    attempt_id: str
    request_id: str
    request_sha256: str
    header_sha256: str
    binding_sha256: str
    source_tokens: tuple
    allowed_scope_sha256: str
    forbidden_scope_sha256: str
    admitted_capability_sha256: str
    budget_sha256: str
    facts_created_at: str
    facts_sha256: str

    def __getattr__(self, name):
        if name in source._FLAGS:
            return False
        raise AttributeError(name)

    def to_dict(self):
        body = {f.name: getattr(self, f.name) for f in fields(self)}
        body.update({flag: False for flag in source._FLAGS})
        return body


def _identity(bound, request_bytes):
    request, header = source._candidate(
        bound.job_id, bound.attempt_id, request_bytes)
    _check(request["digest"] == bound.request_sha256 and
           request["request_id"] == bound.request_id and
           header["header_sha256"] == bound.header_sha256 and
           request["admission_ref"] == [bound.admission_decision_id,
                                        bound.admission_decision_sha256],
           "candidate differs from immutable assignment")
    _check(source._product(bound.blueprint_id, bound.blueprint_version,
                           bound.slice_id) ==
           (bound.blueprint_sha256, bound.slice_version),
           "product differs from immutable assignment")
    registry = create_mootos_tcb_registry_v1()
    _check(header["trusted_policy_version"] == POLICY_VERSION and
           header["tcb_registry_sha256"] == registry.registry_sha256 and
           header["tcb_snapshot_sha256"] ==
           create_trusted_policy_snapshot().snapshot_sha256,
           "candidate needs readmission under current TCB")
    return request


def capture_launch_facts(*, job_id, request_id, request_bytes):
    """Before/read/after tokens; any mismatch requires rebuilding facts.

    Currentness of identity is not semantic validation of lifecycle/admission.
    Neither this function nor revalidation can authorize a launch.
    """
    try:
        bound = source.load_launch_candidate_binding(
            job_id=job_id, request_id=request_id)
        before = _tokens(bound)
        request = _identity(bound, request_bytes)
        after = _tokens(bound)
        if before != after or bound.binding_sha256 != after[0]:
            raise LaunchFactsStale("sources changed during facts capture")
        values = dict(
            schema_version=VERSION, job_id=job_id, attempt_id=bound.attempt_id,
            request_id=request_id, request_sha256=bound.request_sha256,
            header_sha256=bound.header_sha256,
            binding_sha256=bound.binding_sha256,
            source_tokens=after,
            allowed_scope_sha256=_hash(request["allowed_scope"]),
            forbidden_scope_sha256=_hash(request["forbidden_scope"]),
            admitted_capability_sha256=_hash(
                request["admitted_capability_ids"]),
            budget_sha256=_hash(request["budget_ceilings"]),
            facts_created_at=datetime.now(timezone.utc).isoformat(),
        )
        body = dict(values, **{flag: False for flag in source._FLAGS})
        return TrustedLaunchFacts(**values, facts_sha256=_hash(body))
    except LaunchFactsStale:
        raise
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        raise LaunchFactsError("facts source invalid or unavailable") from None


def revalidate_launch_facts(facts, *, request_bytes):
    """Rebuild immediately at consumption and return only the fresh record.

    No reconstructed caller record is trusted as a bearer token, even if its
    public hash is correct. This does not prevent changes after return.
    """
    if type(facts) is not TrustedLaunchFacts:
        raise LaunchFactsStale("invalid facts record")
    try:
        fresh = capture_launch_facts(
            job_id=facts.job_id, request_id=facts.request_id,
            request_bytes=request_bytes)
        for field in fields(TrustedLaunchFacts):
            if field.name in ("facts_created_at", "facts_sha256"):
                continue
            old, new = getattr(facts, field.name), getattr(fresh, field.name)
            if type(old) is not type(new) or old != new:
                raise LaunchFactsStale("bound source facts changed")
        body = facts.to_dict()
        digest = body.pop("facts_sha256")
        if _hash(body) != digest:
            raise LaunchFactsStale("facts integrity mismatch")
        return fresh
    except (ValueError, KeyError, TypeError, AttributeError):
        raise LaunchFactsStale("facts stale or unverified; rebuild") from None
