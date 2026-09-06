"""Shared canonical-serialization and validation primitives for GP-A.

GP-A ("Architecture Baseline & Evaluation Corpus") adds several small
sealed-contract modules: architecture baseline manifest, task taxonomy,
frozen eval case contract, provider-neutral evidence record, the eval
corpus, the offline harness, and baseline evidence capture. Each of those
modules follows the same canonical-JSON / SHA-256 / zero-authority idiom
already used throughout ``backend/continuous_builder`` (see
``trusted_policy.py``, ``system_model.py``, ``context_engine.py``). Rather
than re-implementing that idiom independently in every new GP-A module,
they share the primitives defined here.

This module does NOT reimplement path canonicalization or TCB/System Model
facts -- ``canonicalize_repo_path`` is re-exported from ``.paths``, and TCB
authority flags are re-exported from ``.trusted_policy``. Every GP-A record
built on top of this module is observational evidence only: nothing here
grants capability, transitions queue/GitHub/merge/Main state, or trusts
worker-reported output.

GP-A is not an autonomy phase. No function in this module (or in any module
that imports it) executes a coding provider, makes a network call, or
mutates trusted policy.
"""

import hashlib
import json
import re

from .paths import PathCanonicalizationError, canonicalize_repo_path
from .trusted_policy import AUTHORITY_FLAGS

__all__ = [
    "GPAEvalSchemaError",
    "GPA_SCHEMA_SUITE_VERSION",
    "UNKNOWN",
    "PROVENANCE_CODES",
    "AUTHORITY_FLAGS",
    "canonical_json",
    "sha256_hex",
    "require_sha256",
    "require_base_sha",
    "require_no_authority",
    "require_repo_path",
    "require_text",
    "require_sorted_unique_paths",
    "require_id",
    "is_unknown",
    "require_numeric_or_unknown",
    "require_bool_or_unknown",
    "require_enum_or_unknown",
]


class GPAEvalSchemaError(ValueError):
    """Raised when GP-A evaluation evidence cannot be produced safely."""


# Single shared suite version. Individual GP-A record kinds (taxonomy, eval
# case, evidence record, ...) additionally carry their own narrower
# ``*_VERSION`` constant; this suite version is what the architecture
# baseline manifest binds so a benchmark result can name "which evaluation
# schema generation" produced it without enumerating every sub-schema.
GPA_SCHEMA_SUITE_VERSION = "gpa-eval-schema-suite-v1"

# The literal sentinel for "not knowable", distinct from any real value
# (including zero, False, or an empty string). Every optional observational
# field in GP-A4's evidence record (and GP-A7's historical observations)
# accepts either a validly typed value or exactly this sentinel -- never a
# fabricated zero/False standing in for missing data.
UNKNOWN = "unknown"

# How a known (non-UNKNOWN) observational field value was obtained. Shared
# by GP-A4 (EvidenceRecord.field_provenance) and GP-A7 (historical PR
# observations) so both use one vocabulary instead of two.
PROVENANCE_CODES = frozenset(
    {
        "measured_directly",
        "reconstructed",
        "user_reported",
        "provider_reported",
    }
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def canonical_json(value):
    """Deterministic canonical JSON bytes: sorted keys, no whitespace."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def require_sha256(value, label):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GPAEvalSchemaError(f"{label} is malformed")


def require_base_sha(value, label="base_sha"):
    """Accept a git commit SHA-1 (40 hex) or a content SHA-256 (64 hex)."""
    if not isinstance(value, str) or not (
        _GIT_SHA.fullmatch(value) or _SHA256.fullmatch(value)
    ):
        raise GPAEvalSchemaError(f"{label} is malformed")


def require_no_authority(obj):
    for name in AUTHORITY_FLAGS:
        if getattr(obj, name, False) is not False:
            raise GPAEvalSchemaError("GP-A evidence cannot claim authority")


def require_repo_path(value, label="path", max_bytes=4096):
    if not isinstance(value, str) or not value:
        raise GPAEvalSchemaError(f"{label} is malformed")
    if len(value.encode("utf-8")) > max_bytes:
        raise GPAEvalSchemaError(f"{label} exceeds byte bound")
    try:
        canonical = canonicalize_repo_path(value)
    except PathCanonicalizationError as error:
        raise GPAEvalSchemaError(f"{label} is unsafe") from error
    if canonical != value:
        raise GPAEvalSchemaError(f"{label} is not canonical")
    return canonical


def require_text(value, label, max_bytes):
    if not isinstance(value, str) or not value:
        raise GPAEvalSchemaError(f"{label} must be nonblank text")
    if len(value.encode("utf-8")) > max_bytes:
        raise GPAEvalSchemaError(f"{label} exceeds byte bound")
    return value


def require_id(value, label, max_bytes=64):
    if (
        not isinstance(value, str)
        or _ID.fullmatch(value) is None
        or len(value.encode("utf-8")) > max_bytes
    ):
        raise GPAEvalSchemaError(f"{label} is malformed")
    return value


def require_sorted_unique_paths(values, label, maximum, max_bytes=4096):
    if type(values) is not tuple:
        raise GPAEvalSchemaError(f"{label} is malformed")
    if len(values) > maximum:
        raise GPAEvalSchemaError(f"{label} exceeds bound")
    normalized = tuple(
        require_repo_path(value, label, max_bytes) for value in values
    )
    if normalized != tuple(sorted(set(normalized))):
        raise GPAEvalSchemaError(f"{label} is not canonical")
    if len({value.casefold() for value in normalized}) != len(normalized):
        raise GPAEvalSchemaError(f"{label} collides by case")
    return normalized


def is_unknown(value):
    return value == UNKNOWN


def require_numeric_or_unknown(
    value, label, *, minimum=0, maximum=None, integer=False,
):
    """Validate a numeric evidence field that may instead be ``UNKNOWN``.

    Never coerces a missing value to 0 -- callers that lack real telemetry
    must pass ``UNKNOWN`` explicitly.
    """
    if is_unknown(value):
        return value
    if integer:
        if type(value) is not int:
            raise GPAEvalSchemaError(f"{label} must be int or '{UNKNOWN}'")
    elif type(value) not in (int, float) or isinstance(value, bool):
        raise GPAEvalSchemaError(f"{label} must be numeric or '{UNKNOWN}'")
    if value < minimum:
        raise GPAEvalSchemaError(f"{label} is out of bounds")
    if maximum is not None and value > maximum:
        raise GPAEvalSchemaError(f"{label} exceeds bound")
    return value


def require_bool_or_unknown(value, label):
    if is_unknown(value):
        return value
    if type(value) is not bool:
        raise GPAEvalSchemaError(f"{label} must be bool or '{UNKNOWN}'")
    return value


def require_enum_or_unknown(value, label, allowed):
    if is_unknown(value):
        return value
    if value not in allowed:
        raise GPAEvalSchemaError(f"{label} is not a supported value")
    return value
