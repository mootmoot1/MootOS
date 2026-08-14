"""Pure authoritative BuildJob binding input for MootOS V0.4B Slice 4.

This module validates inert data required by a future BuildJob-creation
adapter. It does not import or create BuildJob, advance workflow, access
files or networks, invoke Git or GitHub, execute code, register or install
capabilities, or exercise backend, runtime, deployment, or autonomous
authority.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


class JobBindingError(ValueError):
    """Raised when binding state cannot be represented safely."""


SCHEMA_VERSION = 1
STATUS_READY_FOR_JOB_CREATION = "ready_for_job_creation"
STATUS_BLOCKED = "blocked"
BINDING_STATUSES = (
    STATUS_READY_FOR_JOB_CREATION,
    STATUS_BLOCKED,
)

MAX_JOB_ID_BYTES = 128
MAX_CAPABILITY_ID_BYTES = 200
MAX_ACTOR_BYTES = 200
MAX_NOTE_BYTES = 2_000
MAX_BINDING_SUMMARY_BYTES = 16 * 1024

_JOB_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_CAPABILITY_ID_PATTERN = (
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$"
)
_SPEC_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_BASE_SHA_PATTERN = r"^[0-9a-f]{7,64}$"

_REQUIRED_REASON = {
    "job_id": "job_id is required.",
    "capability_id": "capability_id is required.",
    "spec_sha256": "spec_sha256 is required.",
    "base_sha": "base_sha is required.",
    "actor": "actor is required.",
    "note": "note is required.",
}


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFC", value)
    without_controls = "".join(
        " " if unicodedata.category(character) == "Cc" else character
        for character in normalized
    )
    return " ".join(without_controls.split())


def _secret_shape(value: str) -> bool:
    lowered = value.casefold()
    for prefix, required in (
        ("sk-", 16),
        ("ghp_", 20),
        ("gho_", 20),
        ("ghu_", 20),
        ("ghs_", 20),
        ("ghr_", 20),
        ("akia", 16),
    ):
        start = 0
        while True:
            index = lowered.find(prefix, start)
            if index < 0:
                break
            suffix = lowered[index + len(prefix):]
            count = 0
            for character in suffix:
                if not (character.isalnum() or character in "_-"):
                    break
                count += 1
            if count >= required:
                return True
            start = index + len(prefix)

    for marker in (
        "api key",
        "api_key",
        "access token",
        "access_token",
        "password",
        "secret key",
        "secret_key",
        "session secret",
        "session_secret",
    ):
        index = lowered.find(marker)
        if index < 0:
            continue
        tail = lowered[index + len(marker):].lstrip()
        if not tail or tail[0] not in "=:":
            continue
        candidate = tail[1:].lstrip()
        if candidate[:1] in ("'", '"'):
            candidate = candidate[1:]
        count = 0
        for character in candidate:
            if not (character.isalnum() or character in "_-/+"):
                break
            count += 1
        if count >= 16:
            return True
    return False


def _text_field(
    value: Any,
    field_name: str,
    maximum_bytes: int,
) -> tuple:
    reasons = []
    if not isinstance(value, str):
        normalized = ""
        if value is not None:
            reasons.append(f"{field_name} must be text.")
    else:
        normalized = _normalize_text(value)
    if not normalized and not reasons:
        reasons.append(_REQUIRED_REASON[field_name])
    if len(normalized.encode("utf-8")) > maximum_bytes:
        reasons.append(f"{field_name} exceeds {maximum_bytes} bytes.")
        normalized = ""
    if normalized and _secret_shape(normalized):
        reasons.append(f"{field_name} contains secret-like material.")
        normalized = ""
    return normalized, tuple(reasons)


def _identifier_field(
    value: Any,
    field_name: str,
    maximum_bytes: int,
    pattern: str,
) -> tuple:
    normalized, reasons = _text_field(
        value, field_name, maximum_bytes
    )
    if normalized and not re.fullmatch(pattern, normalized):
        reasons += (f"{field_name} has an invalid format.",)
        normalized = ""
    return normalized, reasons


def _hash_field(
    value: Any,
    field_name: str,
    pattern: str,
) -> tuple:
    normalized, reasons = _text_field(
        value,
        field_name,
        MAX_BINDING_SUMMARY_BYTES,
    )
    if normalized and not re.fullmatch(pattern, normalized):
        reasons += (f"{field_name} has an invalid format.",)
        normalized = ""
    return normalized, reasons


def _stable_reasons(values: tuple) -> tuple:
    return tuple(
        sorted(set(values), key=lambda reason: (reason.casefold(), reason))
    )


@dataclass(frozen=True)
class BuildJobBinding:
    """Immutable validated inputs for a future BuildJob creation step."""

    job_id: Any
    capability_id: Any
    spec_sha256: Any
    base_sha: Any
    actor: Any
    note: Any
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    status: str = field(init=False)
    blocking_reasons: tuple = field(init=False)
    ready_for_job_creation: bool = field(init=False)
    offline_only: bool = field(default=True, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        job_id, job_reasons = _identifier_field(
            self.job_id,
            "job_id",
            MAX_JOB_ID_BYTES,
            _JOB_ID_PATTERN,
        )
        capability_id, capability_reasons = _identifier_field(
            self.capability_id,
            "capability_id",
            MAX_CAPABILITY_ID_BYTES,
            _CAPABILITY_ID_PATTERN,
        )
        spec_sha256, spec_reasons = _hash_field(
            self.spec_sha256,
            "spec_sha256",
            _SPEC_SHA256_PATTERN,
        )
        base_sha, base_reasons = _hash_field(
            self.base_sha,
            "base_sha",
            _BASE_SHA_PATTERN,
        )
        actor, actor_reasons = _text_field(
            self.actor, "actor", MAX_ACTOR_BYTES
        )
        note, note_reasons = _text_field(
            self.note, "note", MAX_NOTE_BYTES
        )
        reasons = _stable_reasons(
            job_reasons
            + capability_reasons
            + spec_reasons
            + base_reasons
            + actor_reasons
            + note_reasons
        )
        status = (
            STATUS_BLOCKED
            if reasons
            else STATUS_READY_FOR_JOB_CREATION
        )

        object.__setattr__(self, "job_id", job_id)
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "spec_sha256", spec_sha256)
        object.__setattr__(self, "base_sha", base_sha)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "note", note)
        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "ready_for_job_creation",
            status == STATUS_READY_FOR_JOB_CREATION,
        )

        if len(self.summary().encode("utf-8")) > MAX_BINDING_SUMMARY_BYTES:
            raise JobBindingError(
                "job-binding summary exceeds "
                f"{MAX_BINDING_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic validated binding data for human review."""
        return {
            "actor": self.actor,
            "authority": {
                "autonomous": self.autonomous,
                "offline_only": self.offline_only,
                "runtime_authority": self.runtime_authority,
            },
            "base_sha": self.base_sha,
            "blocking_reasons": list(self.blocking_reasons),
            "capability_id": self.capability_id,
            "job_id": self.job_id,
            "note": self.note,
            "ready_for_job_creation": self.ready_for_job_creation,
            "schema_version": self.schema_version,
            "spec_sha256": self.spec_sha256,
            "status": self.status,
        }

    def summary(self) -> str:
        """Return stable bounded JSON without operational artifacts."""
        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"
