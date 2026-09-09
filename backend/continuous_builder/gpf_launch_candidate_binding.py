"""System-owned, write-once product/job assignment; never launch authority.

Only the isolated coordinator may invoke this writer. Python imports, record
constructors and hashes do not enforce caller identity. F10 must deny ordinary
workers access to these sources and the writer capability. Source locations
are protected configuration, intentionally unprovisioned in this offline slice.
"""

import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path

# Human-reviewed system provisioning only; no environment or caller override.
# Root contains jobs/ and launch_bindings/; it must already exist securely.
_AUTHORITATIVE_ROOT = None
_PRODUCT_DATABASE = None
VERSION = "gpf-launch-candidate-binding-v1"
MAX_RECORD = 128 * 1024
MAX_ATTEMPTS = 1024
_FLAGS = (
    "launch_authorized", "dispatch_authorized", "publication_authorized",
    "github_authorized", "merge_authorized", "main_advancement_authorized",
    "queue_transition_authorized", "result_trusted", "worker_output_trusted",
)


class LaunchBindingError(ValueError):
    """Fail-closed assignment failure; contains no source contents."""


def _check(condition, reason):
    if not condition:
        raise LaunchBindingError(reason)


def _id(value):
    _check(type(value) is str and
           re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value), "invalid identity")
    return value


def _text(value):
    _check(type(value) is str and
           re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value),
           "invalid product identity")
    return value


def _sha(value):
    _check(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value),
           "invalid digest")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _check(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise LaunchBindingError("invalid JSON constant")


def _json(raw):
    _check(type(raw) is bytes and 0 < len(raw) <= MAX_RECORD,
           "record byte bound/type")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                            parse_constant=_reject_constant)
        _check(type(result) is dict, "record is not an object")
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise LaunchBindingError("invalid JSON record") from None


def _sealed(raw, digest_field):
    body = _json(raw)
    _sha(body.get(digest_field))
    payload = {k: v for k, v in body.items() if k != digest_field}
    _check(body[digest_field] == _digest(_canonical(payload)),
           "source digest mismatch")
    for key, value in body.items():
        if key.endswith("_authorized") or key in _FLAGS:
            _check(value is False, "source authority promotion")
    return body


@contextmanager
def _directory(path):
    _check(path is not None, "authoritative sources unconfigured")
    path = Path(path)
    _check(path.is_absolute() and
           all(p not in (".", "..") for p in path.parts),
           "invalid configured source")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        _check(info.st_uid == os.getuid() and not info.st_mode & 0o022,
               "source directory ownership/permissions")
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _child(parent, name, create=False):
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                 dir_fd=parent)
    try:
        info = os.fstat(fd)
        _check(info.st_uid == os.getuid() and not info.st_mode & 0o022,
               "unsafe source directory")
        yield fd
    finally:
        os.close(fd)


def _read(parent, name, maximum=MAX_RECORD):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                 dir_fd=parent)
    try:
        info = os.fstat(fd)
        _check(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
               info.st_uid == os.getuid() and not info.st_mode & 0o022 and
               info.st_size <= maximum, "unsafe source file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        _check(len(raw) <= maximum, "source exceeds byte bound")
        return raw
    finally:
        os.close(fd)


@dataclass(frozen=True)
class LaunchCandidateBinding:
    schema_version: str
    job_id: str
    header_sha256: str
    attempt_id: str
    request_id: str
    request_sha256: str
    blueprint_id: str
    blueprint_version: str
    blueprint_sha256: str
    slice_id: str
    slice_version: str
    admission_decision_id: str
    admission_decision_sha256: str
    created_at: str
    binding_sha256: str

    def __post_init__(self):
        _check(self.schema_version == VERSION, "unsupported binding schema")
        for name in ("job_id", "attempt_id", "request_id",
                     "admission_decision_id"):
            _id(getattr(self, name))
        for name in ("header_sha256", "request_sha256", "blueprint_sha256",
                     "admission_decision_sha256", "binding_sha256"):
            _sha(getattr(self, name))
        for name in ("blueprint_id", "blueprint_version", "slice_id",
                     "slice_version"):
            _text(getattr(self, name))
        _check(type(self.created_at) is str and len(self.created_at) <= 128,
               "invalid creation time")
        stamp = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        _check(stamp.utcoffset() is not None, "creation time needs timezone")
        body = self.to_dict()
        body.pop("binding_sha256")
        _check(self.binding_sha256 == _digest(_canonical(body)),
               "binding digest mismatch")

    def __getattr__(self, name):
        if name in _FLAGS:
            return False
        raise AttributeError(name)

    def to_dict(self):
        body = {f.name: getattr(self, f.name) for f in fields(self)}
        body.update({name: False for name in _FLAGS})
        return body


def _decode_binding(raw):
    body = _sealed(raw, "binding_sha256")
    expected = {f.name for f in fields(LaunchCandidateBinding)}
    _check(set(body) == expected | set(_FLAGS), "binding fields mismatch")
    _check(raw == _canonical(body), "noncanonical persisted binding")
    return LaunchCandidateBinding(**{k: body[k] for k in expected})


def _product(blueprint_id, blueprint_version, slice_id):
    _check(_PRODUCT_DATABASE is not None, "product source unconfigured")
    path = Path(_PRODUCT_DATABASE)
    with _directory(path.parent) as parent:
        # Reject symlink/nonregular DB before sqlite opens its fixed URI.
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            before = os.fstat(fd)
            _check(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                   before.st_uid == os.getuid() and not before.st_mode & 0o022,
                   "unsafe product database")
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            try:
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
                rows = connection.execute(
                    "SELECT b.content_digest, s.slice_version "
                    "FROM builder_blueprints b JOIN builder_slices s "
                    "USING (blueprint_id, blueprint_version) "
                    "WHERE b.blueprint_id=? AND b.blueprint_version=? "
                    "AND s.slice_id=? LIMIT 2",
                    (blueprint_id, blueprint_version, slice_id),
                ).fetchall()
                _check(len(rows) == 1, "product membership missing/ambiguous")
                digest, version = rows[0]
                _sha(digest)
                _text(version)
                after = os.stat(path.name, dir_fd=parent,
                                follow_symlinks=False)
                _check((before.st_dev, before.st_ino) ==
                       (after.st_dev, after.st_ino), "product source replaced")
                return digest, version
            finally:
                connection.close()
        finally:
            os.close(fd)


def _candidate(job_id, attempt_id, request_bytes):
    request = _sealed(request_bytes, "digest")
    _check(request_bytes == _canonical(request), "noncanonical request")
    _check(request.get("protocol_version") == "gpe-worker-v1" and
           request.get("kind") == "worker_request", "wrong request protocol")
    expected_id = "gpe_" + _digest(_canonical(
        ["gpe-worker-v1", job_id, attempt_id]))[:60]
    _check(request.get("job_id") == job_id and
           request.get("attempt_id") == attempt_id and
           request.get("request_id") == expected_id,
           "request identity mismatch")
    with _directory(_AUTHORITATIVE_ROOT) as root, \
            _child(root, "jobs") as jobs, _child(jobs, job_id) as job:
        header = _sealed(_read(job, "header.json"), "header_sha256")
        _check(header.get("schema_version") == "gpd-job-header-v1" and
               header.get("job_id") == job_id, "header identity mismatch")
        raw_attempts = _read(job, "attempts.jsonl", MAX_RECORD * MAX_ATTEMPTS)
        lines = raw_attempts.splitlines()
        _check(0 < len(lines) <= MAX_ATTEMPTS, "attempt count bound")
        prior = None
        attempt = None
        seen_ids = set()
        for number, line in enumerate(lines, 1):
            item = _sealed(line, "attempt_sha256")
            _id(item.get("attempt_id"))
            _check(item["attempt_id"] not in seen_ids, "duplicate attempt")
            seen_ids.add(item["attempt_id"])
            _check(item.get("schema_version") == "gpd-attempt-v1" and
                   item.get("job_id") == job_id and
                   item.get("header_sha256") == header["header_sha256"] and
                   type(item.get("attempt_number")) is int and
                   item["attempt_number"] == number and
                   item.get("prior_attempt_id") == prior,
                   "attempt chain mismatch")
            prior, attempt = item["attempt_id"], item
        _check(attempt["attempt_id"] == attempt_id and
               attempt.get("status") == "started", "stale/noninitial attempt")
        _check(request.get("attempt_sha256") == attempt["attempt_sha256"] and
               request.get("header_sha256") == header["header_sha256"],
               "request header/attempt mismatch")
        for ref, prefix in (("task_contract_ref", "task_contract"),
                            ("execution_plan_ref", "execution_plan"),
                            ("admission_ref", "admission_decision")):
            expected_ref = [header[prefix + "_id"],
                            header[prefix + "_sha256"]]
            _check(request.get(ref) == expected_ref,
                   "request contract/admission mismatch")
        for req, head in (("repository_identity", "repository_identity"),
                          ("base_sha", "base_sha"),
                          ("allowed_scope", "approved_scope_ceiling"),
                          ("forbidden_scope", "forbidden_scope"),
                          ("admitted_capability_ids",
                           "admitted_capability_ids"),
                          ("human_gates", "required_gates")):
            _check(request.get(req) == header[head],
                   "request ceiling mismatch")
        budgets = [header["budget_ceiling_" + name] for name in (
            "wall_clock_seconds", "input_tokens", "output_tokens",
            "cost_usd_cents")]
        _check(request.get("budget_ceilings") == budgets,
               "request budget mismatch")
    return request, header


def _publish(job, name, raw):
    # Atomic create-if-absent, unlike replace(), which can overwrite a winner.
    temporary = ".binding-" + secrets.token_hex(16)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(temporary, flags, 0o600, dir_fd=job)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, name, src_dir_fd=job, dst_dir_fd=job,
                    follow_symlinks=False)
        except FileExistsError:
            existing = _read(job, name)
            _decode_binding(existing)
            _check(existing == raw, "permanent binding conflict")
            return "replay"
        return "new"
    finally:
        os.unlink(temporary, dir_fd=job)
        os.fsync(job)


def assign_launch_candidate(*, job_id, attempt_id, request_bytes,
                            blueprint_id, blueprint_version, slice_id,
                            created_at):
    """Coordinator-only assignment; returns (durable binding, new/replay).

    Inputs select product identity as part of the system assignment operation,
    never through worker/human-approval/correlation APIs. The coordinator must
    obtain this successful durable result before downstream preparation. An
    exception (including fsync failure) means dispatch remains ineligible.
    This validates assignment identity, not the entire GP-E execution contract.
    """
    _id(job_id)
    _id(attempt_id)
    for value in (blueprint_id, blueprint_version, slice_id):
        _text(value)
    try:
        request, header = _candidate(job_id, attempt_id, request_bytes)
        digest, slice_version = _product(
            blueprint_id, blueprint_version, slice_id)
        correlation = request.get("correlation")
        _check(type(correlation) is dict, "missing request correlation")
        _sealed(_canonical(correlation), "digest")
        for name, expected in (
            ("blueprint_id", blueprint_id), ("blueprint_sha256", digest),
            ("slice_id", slice_id), ("job_id", job_id),
            ("header_sha256", header["header_sha256"]),
        ):
            _check(correlation.get(name) == expected,
                   "assignment differs from request correlation")
        values = dict(
            schema_version=VERSION, job_id=job_id,
            header_sha256=header["header_sha256"], attempt_id=attempt_id,
            request_id=request["request_id"], request_sha256=request["digest"],
            blueprint_id=blueprint_id, blueprint_version=blueprint_version,
            blueprint_sha256=digest, slice_id=slice_id,
            slice_version=slice_version,
            admission_decision_id=header["admission_decision_id"],
            admission_decision_sha256=header["admission_decision_sha256"],
            created_at=created_at,
        )
        body = dict(values, **{name: False for name in _FLAGS})
        binding = LaunchCandidateBinding(
            **values, binding_sha256=_digest(_canonical(body)))
        with _directory(_AUTHORITATIVE_ROOT) as root, \
                _child(root, "launch_bindings", True) as bindings, \
                _child(bindings, job_id, True) as job:
            status = _publish(job, request["request_id"] + ".json",
                              _canonical(binding.to_dict()))
        # Recheck source identities before returning to the coordinator.
        # A racing source change leaves historical assignment, not permission.
        fresh = _candidate(job_id, attempt_id, request_bytes)
        _check(fresh == (request, header),
               "candidate changed during assignment")
        fresh_product = _product(blueprint_id, blueprint_version, slice_id)
        _check(fresh_product ==
               (digest, slice_version), "product changed during assignment")
        return binding, status
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        raise LaunchBindingError("assignment failed closed") from None


def load_launch_candidate_binding(*, job_id, request_id):
    """Read only from the fixed authoritative sidecar; never caller objects."""
    _id(job_id)
    _id(request_id)
    try:
        with _directory(_AUTHORITATIVE_ROOT) as root, \
                _child(root, "launch_bindings") as bindings, \
                _child(bindings, job_id) as job:
            binding = _decode_binding(_read(job, request_id + ".json"))
        _check((binding.job_id, binding.request_id) == (job_id, request_id),
               "persisted path/identity mismatch")
        return binding
    except (OSError, ValueError, KeyError, TypeError):
        raise LaunchBindingError("binding unavailable or invalid") from None
