"""Immutable BuildJob record and state machine for V0.4A Slice 1.

A BuildJob records the mechanics of an offline capability build. It grants
no runtime authority: creating, loading, or transitioning a job cannot make
a capability executable. Every state change is an explicit function call
with a non-blank actor and note, and every call returns a new value.

Records are stored as ``build_jobs/<job_id>/job.json``. The persisted
content hash detects accidental corruption or mismatched content; it is not
an authentication mechanism against a determined local editor.
"""

import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


class BuildJobError(ValueError):
    """Raised for an invalid BuildJob, transition, or persisted record."""


SCHEMA_VERSION = 1
MAX_FIX_ROUNDS = 2

STATE_DRAFTED = "drafted"
STATE_DISPATCHED = "dispatched"
STATE_RETURNED = "returned"
STATE_VALIDATED = "validated"
STATE_VERIFIED = "verified"
STATE_REVIEWED = "reviewed"
STATE_READY_FOR_PR = "ready_for_pr"
STATE_NEEDS_HUMAN = "needs_human"
STATE_CANCELLED = "cancelled"

FORWARD_STATES = (
    STATE_DRAFTED,
    STATE_DISPATCHED,
    STATE_RETURNED,
    STATE_VALIDATED,
    STATE_VERIFIED,
    STATE_REVIEWED,
    STATE_READY_FOR_PR,
)
TERMINAL_STATES = (STATE_NEEDS_HUMAN, STATE_CANCELLED)
BUILD_JOB_STATES = FORWARD_STATES + TERMINAL_STATES
_FORWARD_INDEX = {
    state: index for index, state in enumerate(FORWARD_STATES)
}

RETRY_VERIFICATION_FAILURE = "verification_failure"
RETRY_BLOCKING_FINDING = "blocking_finding"
RETRY_REASONS = (
    RETRY_VERIFICATION_FAILURE,
    RETRY_BLOCKING_FINDING,
)
_RETRY_REASON_BY_STATE = {
    STATE_VERIFIED: RETRY_VERIFICATION_FAILURE,
    STATE_REVIEWED: RETRY_BLOCKING_FINDING,
}

_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BuildJobError(
            f"{field_name} is required and cannot be blank"
        )
    return value


def _integer(value: Any, field_name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BuildJobError(f"{field_name} must be an integer")
    if value < minimum:
        raise BuildJobError(
            f"{field_name} must be at least {minimum}"
        )
    return value


@dataclass(frozen=True)
class BuildBudgets:
    """Locked V0.4A budget defaults from ADR-036 section 23."""

    max_fix_rounds: int = MAX_FIX_ROUNDS
    max_new_files: int = 4
    max_existing_files_edited: int = 2
    max_net_added_lines: int = 300
    max_changed_lines_per_existing_file: int = 150
    max_bytes_per_file: int = 64 * 1024
    max_bytes_per_diff: int = 256 * 1024
    max_characters_per_line: int = 500

    def __post_init__(self) -> None:
        if self.max_fix_rounds != MAX_FIX_ROUNDS:
            raise BuildJobError(
                "max_fix_rounds is fixed at 2 and has no override"
            )
        for field_name in (
            "max_new_files",
            "max_existing_files_edited",
            "max_net_added_lines",
            "max_changed_lines_per_existing_file",
            "max_bytes_per_file",
            "max_bytes_per_diff",
            "max_characters_per_line",
        ):
            _integer(getattr(self, field_name), field_name, minimum=1)

    def to_dict(self) -> dict:
        return {
            "max_fix_rounds": self.max_fix_rounds,
            "max_new_files": self.max_new_files,
            "max_existing_files_edited": (
                self.max_existing_files_edited
            ),
            "max_net_added_lines": self.max_net_added_lines,
            "max_changed_lines_per_existing_file": (
                self.max_changed_lines_per_existing_file
            ),
            "max_bytes_per_file": self.max_bytes_per_file,
            "max_bytes_per_diff": self.max_bytes_per_diff,
            "max_characters_per_line": (
                self.max_characters_per_line
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BuildBudgets":
        if not isinstance(data, Mapping):
            raise BuildJobError("budgets must be a JSON object")
        expected = set(cls().to_dict())
        unknown = set(data) - expected
        missing = expected - set(data)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise BuildJobError(f"Unknown budget field(s): {names}")
        if missing:
            names = ", ".join(sorted(missing))
            raise BuildJobError(f"Missing budget field(s): {names}")
        return cls(**{name: data[name] for name in expected})


@dataclass(frozen=True)
class BuildJobEvent:
    """One append-only, attributed BuildJob state transition."""

    from_state: Optional[str]
    to_state: str
    actor: str
    note: str
    at: str
    fix_round: int
    retry_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.from_state is not None and (
            self.from_state not in BUILD_JOB_STATES
        ):
            raise BuildJobError(
                f"Unknown event source state: {self.from_state!r}"
            )
        if self.to_state not in BUILD_JOB_STATES:
            raise BuildJobError(
                f"Unknown event target state: {self.to_state!r}"
            )
        _required_text(self.actor, "actor")
        _required_text(self.note, "note")
        _required_text(self.at, "timestamp")
        _integer(self.fix_round, "event fix_round", minimum=0)
        if self.retry_reason is not None:
            if self.retry_reason not in RETRY_REASONS:
                raise BuildJobError(
                    f"Unknown retry reason: {self.retry_reason!r}"
                )

    def to_dict(self) -> dict:
        return {
            "from_state": self.from_state,
            "to_state": self.to_state,
            "actor": self.actor,
            "note": self.note,
            "at": self.at,
            "fix_round": self.fix_round,
            "retry_reason": self.retry_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BuildJobEvent":
        if not isinstance(data, Mapping):
            raise BuildJobError("Each history event must be a JSON object")
        fields = {
            "from_state",
            "to_state",
            "actor",
            "note",
            "at",
            "fix_round",
            "retry_reason",
        }
        unknown = set(data) - fields
        missing = fields - set(data)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise BuildJobError(f"Unknown history field(s): {names}")
        if missing:
            names = ", ".join(sorted(missing))
            raise BuildJobError(f"Missing history field(s): {names}")
        return cls(**{name: data[name] for name in fields})


@dataclass(frozen=True)
class BuildJob:
    """An immutable offline build-process record with replayable history."""

    job_id: str
    capability_id: str
    spec_sha256: str
    base_sha: str
    state: str
    fix_round: int = 0
    budgets: BuildBudgets = field(default_factory=BuildBudgets)
    history: tuple = field(default_factory=tuple)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_job_identity(self)
        _validate_history(self)

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "capability_id": self.capability_id,
            "spec_sha256": self.spec_sha256,
            "base_sha": self.base_sha,
            "state": self.state,
            "fix_round": self.fix_round,
            "budgets": self.budgets.to_dict(),
            "history": [event.to_dict() for event in self.history],
        }

    @property
    def content_sha256(self) -> str:
        return _content_hash(self._content_dict())

    def to_dict(self) -> dict:
        data = self._content_dict()
        data["content_sha256"] = self.content_sha256
        return data

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False
        ) + "\n"


def _validate_job_identity(job: BuildJob) -> None:
    if job.schema_version != SCHEMA_VERSION:
        raise BuildJobError(
            f"Unsupported BuildJob schema version: {job.schema_version!r}"
        )
    _required_text(job.job_id, "job_id")
    if not _JOB_ID_PATTERN.fullmatch(job.job_id):
        raise BuildJobError(
            "job_id may contain only letters, digits, dot, underscore, "
            "and hyphen"
        )
    _required_text(job.capability_id, "capability_id")
    if not _SHA256_PATTERN.fullmatch(job.spec_sha256):
        raise BuildJobError(
            "spec_sha256 must be a lowercase 64-character SHA-256"
        )
    if not _GIT_SHA_PATTERN.fullmatch(job.base_sha):
        raise BuildJobError(
            "base_sha must be a lowercase hexadecimal Git object ID"
        )
    if job.state not in BUILD_JOB_STATES:
        raise BuildJobError(f"Unknown BuildJob state: {job.state!r}")
    _integer(job.fix_round, "fix_round", minimum=0)
    if not isinstance(job.budgets, BuildBudgets):
        raise BuildJobError("budgets must be a BuildBudgets value")
    if job.fix_round > job.budgets.max_fix_rounds:
        raise BuildJobError("fix_round exceeds max_fix_rounds")
    if not isinstance(job.history, tuple):
        raise BuildJobError("history must be an immutable tuple")


def _validate_history(job: BuildJob) -> None:
    if not job.history:
        raise BuildJobError(
            "BuildJob history cannot be empty; direct construction cannot "
            "bypass the drafted event"
        )
    for event in job.history:
        if not isinstance(event, BuildJobEvent):
            raise BuildJobError(
                "history may contain only BuildJobEvent values"
            )

    current_state: Optional[str] = None
    current_round = 0
    for index, event in enumerate(job.history):
        if index == 0:
            if (
                event.from_state is not None
                or event.to_state != STATE_DRAFTED
                or event.fix_round != 0
                or event.retry_reason is not None
            ):
                raise BuildJobError(
                    "The first history event must create drafted at fix "
                    "round 0"
                )
            current_state = STATE_DRAFTED
            continue

        if event.from_state != current_state:
            raise BuildJobError(
                "History event source does not match the previous state"
            )
        current_state, current_round = _replay_event(
            current_state, current_round, event, job.budgets
        )

    if current_state != job.state:
        raise BuildJobError("BuildJob state does not match its history")
    if current_round != job.fix_round:
        raise BuildJobError("BuildJob fix_round does not match its history")


def _replay_event(
    current_state: str,
    current_round: int,
    event: BuildJobEvent,
    budgets: BuildBudgets,
) -> tuple:
    if current_state in TERMINAL_STATES:
        raise BuildJobError("Terminal BuildJob states cannot transition")

    if event.to_state in TERMINAL_STATES:
        if event.retry_reason is not None or event.fix_round != current_round:
            raise BuildJobError(
                "Terminal transitions cannot be retry events"
            )
        return event.to_state, current_round

    next_index = _FORWARD_INDEX[current_state] + 1
    if (
        current_state in _FORWARD_INDEX
        and next_index < len(FORWARD_STATES)
        and event.to_state == FORWARD_STATES[next_index]
    ):
        if event.retry_reason is not None or event.fix_round != current_round:
            raise BuildJobError(
                "Forward transitions cannot change the fix round"
            )
        return event.to_state, current_round

    expected_reason = _RETRY_REASON_BY_STATE.get(current_state)
    if event.to_state == STATE_DISPATCHED and expected_reason is not None:
        if event.retry_reason != expected_reason:
            raise BuildJobError(
                f"Retry from {current_state!r} requires reason "
                f"{expected_reason!r}"
            )
        if current_round >= budgets.max_fix_rounds:
            raise BuildJobError(
                "Fix-round limit reached; transition to needs_human"
            )
        if event.fix_round != current_round + 1:
            raise BuildJobError(
                "A permitted retry must increment fix_round exactly once"
            )
        return event.to_state, current_round + 1

    raise BuildJobError(
        f"Invalid BuildJob transition from {current_state!r} to "
        f"{event.to_state!r}"
    )


def new_job(
    capability_id: str,
    spec_sha256: str,
    base_sha: str,
    *,
    actor: str,
    note: str,
    budgets: Optional[BuildBudgets] = None,
    job_id: Optional[str] = None,
) -> BuildJob:
    """Create a new BuildJob in ``drafted`` with one attributed event."""
    _required_text(actor, "actor")
    _required_text(note, "note")
    actual_job_id = job_id or uuid.uuid4().hex
    event = BuildJobEvent(
        from_state=None,
        to_state=STATE_DRAFTED,
        actor=actor,
        note=note,
        at=_now(),
        fix_round=0,
    )
    return BuildJob(
        job_id=actual_job_id,
        capability_id=capability_id,
        spec_sha256=spec_sha256,
        base_sha=base_sha,
        state=STATE_DRAFTED,
        budgets=budgets or BuildBudgets(),
        history=(event,),
    )


def transition(
    job: BuildJob,
    new_state: str,
    *,
    actor: str,
    note: str,
) -> BuildJob:
    """Move one step forward or explicitly enter an escape state.

    Retry edges are deliberately excluded; callers must use ``retry`` and
    name the qualifying failure reason.
    """
    _required_text(actor, "actor")
    _required_text(note, "note")
    if new_state not in BUILD_JOB_STATES:
        raise BuildJobError(f"Unknown BuildJob state: {new_state!r}")
    if job.state in TERMINAL_STATES:
        raise BuildJobError("Terminal BuildJob states cannot transition")

    allowed = new_state in TERMINAL_STATES
    current_index = _FORWARD_INDEX[job.state]
    if current_index + 1 < len(FORWARD_STATES):
        allowed = allowed or (
            new_state == FORWARD_STATES[current_index + 1]
        )
    if not allowed:
        raise BuildJobError(
            f"Invalid BuildJob transition from {job.state!r} to "
            f"{new_state!r}"
        )

    event = BuildJobEvent(
        from_state=job.state,
        to_state=new_state,
        actor=actor,
        note=note,
        at=_now(),
        fix_round=job.fix_round,
    )
    return _with_event(job, event)


def retry(
    job: BuildJob,
    *,
    reason: str,
    actor: str,
    note: str,
) -> BuildJob:
    """Return a verified failure or blocking review to ``dispatched``."""
    _required_text(actor, "actor")
    _required_text(note, "note")
    if job.state in TERMINAL_STATES:
        raise BuildJobError("Terminal BuildJob states cannot transition")
    expected_reason = _RETRY_REASON_BY_STATE.get(job.state)
    if expected_reason is None or reason != expected_reason:
        raise BuildJobError(
            f"State {job.state!r} cannot retry for reason {reason!r}"
        )
    if job.fix_round >= job.budgets.max_fix_rounds:
        raise BuildJobError(
            "Fix-round limit reached; transition to needs_human"
        )

    event = BuildJobEvent(
        from_state=job.state,
        to_state=STATE_DISPATCHED,
        actor=actor,
        note=note,
        at=_now(),
        fix_round=job.fix_round + 1,
        retry_reason=reason,
    )
    return _with_event(job, event)


def _with_event(job: BuildJob, event: BuildJobEvent) -> BuildJob:
    return BuildJob(
        job_id=job.job_id,
        capability_id=job.capability_id,
        spec_sha256=job.spec_sha256,
        base_sha=job.base_sha,
        state=event.to_state,
        fix_round=event.fix_round,
        budgets=job.budgets,
        history=job.history + (event,),
        schema_version=job.schema_version,
    )


def job_from_dict(data: Mapping[str, Any]) -> BuildJob:
    """Validate and reconstruct one hash-bound persisted BuildJob."""
    if not isinstance(data, Mapping):
        raise BuildJobError("A BuildJob must be a JSON object")
    fields = {
        "schema_version",
        "job_id",
        "capability_id",
        "spec_sha256",
        "base_sha",
        "state",
        "fix_round",
        "budgets",
        "history",
        "content_sha256",
    }
    unknown = set(data) - fields
    missing = fields - set(data)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise BuildJobError(f"Unknown BuildJob field(s): {names}")
    if missing:
        names = ", ".join(sorted(missing))
        raise BuildJobError(f"Missing BuildJob field(s): {names}")

    supplied_hash = data["content_sha256"]
    if not isinstance(supplied_hash, str):
        raise BuildJobError("content_sha256 must be a string")
    content = {name: data[name] for name in fields - {"content_sha256"}}
    expected_hash = _content_hash(content)
    if not hmac.compare_digest(supplied_hash, expected_hash):
        raise BuildJobError("BuildJob content hash mismatch")

    history_data = data["history"]
    if not isinstance(history_data, list):
        raise BuildJobError("history must be a JSON array")
    return BuildJob(
        job_id=data["job_id"],
        capability_id=data["capability_id"],
        spec_sha256=data["spec_sha256"],
        base_sha=data["base_sha"],
        state=data["state"],
        fix_round=data["fix_round"],
        budgets=BuildBudgets.from_dict(data["budgets"]),
        history=tuple(
            BuildJobEvent.from_dict(item) for item in history_data
        ),
        schema_version=data["schema_version"],
    )


def job_path(job_id: str, root: Any = "build_jobs") -> Path:
    """Return the fixed persistence path for ``job_id`` under ``root``."""
    _required_text(job_id, "job_id")
    if not _JOB_ID_PATTERN.fullmatch(job_id):
        raise BuildJobError("Invalid job_id for persistence path")
    return Path(root) / job_id / "job.json"


def save_job(job: BuildJob, root: Any = "build_jobs") -> Path:
    """Persist ``job`` under ``root/<job_id>/job.json``."""
    path = job_path(job.job_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(job.to_json(), encoding="utf-8")
    return path


def load_job(job_id: str, root: Any = "build_jobs") -> BuildJob:
    """Load and validate ``root/<job_id>/job.json``."""
    path = job_path(job_id, root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        message = f"{path}: cannot load BuildJob: {error}"
        raise BuildJobError(message) from error
    job = job_from_dict(data)
    if job.job_id != job_id:
        raise BuildJobError(
            "Persisted BuildJob job_id does not match its directory"
        )
    return job


def _content_hash(data: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
