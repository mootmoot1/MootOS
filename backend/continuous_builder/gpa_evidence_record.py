"""GP-A4 -- Performance / Evidence Record Schema.

A provider-neutral, observational record of one worker run against one
eval case. This is NOT the adaptive router and NOT the Performance
Ledger -- it is the schema those will eventually be fed from.

Every optional field accepts either a validly typed value or the literal
sentinel ``"unknown"`` (:data:`gpa_eval_schema.UNKNOWN`). A record must
never substitute a fabricated zero, empty string, or ``False`` for data
that was not actually observed -- ``UNKNOWN`` is a first-class value,
never conflated with "measured and it was zero/false".

Every optional field that IS known must additionally declare, in
``field_provenance``, how it came to be known:

- ``measured_directly`` -- captured live from the run itself
- ``reconstructed`` -- derived after the fact from repository/history
  evidence (e.g. ``git diff --numstat`` on a merge commit)
- ``user_reported`` -- supplied by a human, not independently observed
- ``provider_reported`` -- taken from a provider's own self-reported
  telemetry (cost/token dashboards), not independently verified

This lets a reader immediately distinguish "we measured this" from "the
provider told us this" from "we reconstructed a plausible value" -- three
very different trust levels that must never be silently merged.

Observation only. Nothing in this record grants capability, authorizes a
worker, or overrides independent verifier evidence -- outcome/quality
fields here are exactly that: recorded evidence, not a re-judgment.
"""

from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    UNKNOWN,
    GPAEvalSchemaError,
    canonical_json,
    is_unknown,
    require_base_sha,
    require_bool_or_unknown,
    require_id,
    require_no_authority,
    require_numeric_or_unknown,
    require_sha256,
    sha256_hex,
)

EVIDENCE_SCHEMA_VERSION = "gpa-evidence-record-v1"
MAX_TEXT_FIELD_BYTES = 2048
MAX_PROVENANCE_ENTRIES = 64

PROVENANCE_CODES = frozenset(
    {
        "measured_directly",
        "reconstructed",
        "user_reported",
        "provider_reported",
    }
)

OUTCOME_STATES = frozenset({"completed", "failed", "timeout", "cancelled"})
VERIFIER_RESULTS = frozenset({"pass", "fail"})
HUMAN_ACCEPTANCE_STATES = frozenset({"accepted", "rejected"})
REGRESSION_RESULTS = frozenset({"pass", "fail", "not_run"})
HUMAN_REVIEW_OUTCOMES = frozenset({"accepted", "rejected", "not_reviewed"})

# name -> (minimum, maximum) for integer fields validated with
# require_numeric_or_unknown(integer=True).
_INT_FIELDS = {
    "repair_attempts": (0, 1000),
    "input_tokens": (0, 10**9),
    "output_tokens": (0, 10**9),
    "cached_tokens": (0, 10**9),
    "cost_usd_cents": (0, 10**9),
    "context_bytes_supplied": (0, 10**10),
    "supplement_request_count": (0, 10**6),
    "supplement_bytes": (0, 10**10),
    "files_changed": (0, 10**6),
    "additions": (0, 10**9),
    "deletions": (0, 10**9),
    "artifact_count": (0, 10**6),
    "artifact_bytes": (0, 10**11),
}
# name -> (minimum, maximum) for float-or-int fields.
_NUMERIC_FIELDS = {
    "wall_clock_seconds": (0, 10**7),
    "model_time_seconds": (0, 10**7),
}
_BOOL_FIELDS = (
    "first_pass_success",
    "success_after_repair",
    "crashed",
    "stalled",
    "timed_out",
    "scope_violation",
    "policy_violation",
    "cleanup_failure",
    "execution_state_uncertain",
)
# name -> allowed non-"unknown" enum members.
_ENUM_FIELDS = {
    "outcome_state": OUTCOME_STATES,
    "verifier_result": VERIFIER_RESULTS,
    "human_acceptance": HUMAN_ACCEPTANCE_STATES,
    "regression_result": REGRESSION_RESULTS,
    "human_review_outcome": HUMAN_REVIEW_OUTCOMES,
}
# name -> max byte length for free-text-or-unknown fields.
_TEXT_FIELDS = {
    "provider": 128,
    "model": 128,
    "harness_version": 128,
    "verifier_receipt_ref": 256,
    "human_review_reason": MAX_TEXT_FIELD_BYTES,
}

OPTIONAL_FIELD_NAMES = tuple(
    sorted(
        set(_INT_FIELDS)
        | set(_NUMERIC_FIELDS)
        | set(_BOOL_FIELDS)
        | set(_ENUM_FIELDS)
        | set(_TEXT_FIELDS)
    )
)

_TOKEN = object()


class EvidenceRecordError(GPAEvalSchemaError):
    """Raised when an evidence record is invalid."""


def _require_text_or_unknown(value, label, max_bytes):
    if is_unknown(value):
        return value
    if not isinstance(value, str) or not value:
        raise EvidenceRecordError(f"{label} must be text or '{UNKNOWN}'")
    if len(value.encode("utf-8")) > max_bytes:
        raise EvidenceRecordError(f"{label} exceeds byte bound")
    return value


def _validate_optional_fields(obj):
    for name, (minimum, maximum) in _INT_FIELDS.items():
        setattr_checked = require_numeric_or_unknown(
            getattr(obj, name), name, minimum=minimum, maximum=maximum,
            integer=True,
        )
        object.__setattr__(obj, name, setattr_checked)
    for name, (minimum, maximum) in _NUMERIC_FIELDS.items():
        object.__setattr__(
            obj,
            name,
            require_numeric_or_unknown(
                getattr(obj, name), name, minimum=minimum, maximum=maximum,
            ),
        )
    for name in _BOOL_FIELDS:
        object.__setattr__(
            obj, name, require_bool_or_unknown(getattr(obj, name), name)
        )
    for name, allowed in _ENUM_FIELDS.items():
        value = getattr(obj, name)
        if not is_unknown(value) and value not in allowed:
            raise EvidenceRecordError(f"{name} is not a supported value")
    for name, max_bytes in _TEXT_FIELDS.items():
        object.__setattr__(
            obj,
            name,
            _require_text_or_unknown(getattr(obj, name), name, max_bytes),
        )


def _validate_field_provenance(obj):
    if type(obj.field_provenance) is not tuple:
        raise EvidenceRecordError("field_provenance is malformed")
    if len(obj.field_provenance) > MAX_PROVENANCE_ENTRIES:
        raise EvidenceRecordError("field_provenance exceeds bound")
    seen_names = set()
    for entry in obj.field_provenance:
        if (
            type(entry) is not tuple
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not isinstance(entry[1], str)
        ):
            raise EvidenceRecordError("field_provenance entry is malformed")
        name, code = entry
        if name not in OPTIONAL_FIELD_NAMES:
            raise EvidenceRecordError(
                f"field_provenance names an unknown field: {name}"
            )
        if name in seen_names:
            raise EvidenceRecordError(
                f"field_provenance has a duplicate entry for {name}"
            )
        seen_names.add(name)
        if code not in PROVENANCE_CODES:
            raise EvidenceRecordError(f"provenance code is unsupported: {code}")
    names_with_provenance = frozenset(entry[0] for entry in obj.field_provenance)
    for name in OPTIONAL_FIELD_NAMES:
        known = not is_unknown(getattr(obj, name))
        has_provenance = name in names_with_provenance
        if known and not has_provenance:
            raise EvidenceRecordError(
                f"{name} is known but has no field_provenance entry"
            )
        if not known and has_provenance:
            raise EvidenceRecordError(
                f"{name} is '{UNKNOWN}' but has a field_provenance entry"
            )
    if obj.field_provenance != tuple(sorted(obj.field_provenance)):
        raise EvidenceRecordError("field_provenance is not canonically ordered")


@dataclass(frozen=True)
class EvidenceRecord:
    """One provider-neutral, observational record of a worker run.

    Zero authority: nothing here grants capability. ``result_trusted`` and
    ``worker_output_trusted`` remain structurally False even when
    ``outcome_state`` is ``"completed"`` -- authority is decided elsewhere,
    never inferred from a performance record.
    """

    schema_version: str
    run_id: str
    eval_case_id: str
    eval_case_sha256: str
    architecture_baseline_sha256: str
    base_sha: str
    provider: object
    model: object
    harness_version: object
    outcome_state: str
    verifier_result: str
    human_acceptance: str
    first_pass_success: object
    success_after_repair: object
    repair_attempts: object
    wall_clock_seconds: object
    model_time_seconds: object
    input_tokens: object
    output_tokens: object
    cached_tokens: object
    cost_usd_cents: object
    context_bytes_supplied: object
    supplement_request_count: object
    supplement_bytes: object
    files_changed: object
    additions: object
    deletions: object
    artifact_count: object
    artifact_bytes: object
    crashed: object
    stalled: object
    timed_out: object
    scope_violation: object
    policy_violation: object
    cleanup_failure: object
    execution_state_uncertain: object
    verifier_receipt_ref: object
    regression_result: str
    human_review_outcome: str
    human_review_reason: object
    field_provenance: tuple
    record_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise EvidenceRecordError(
                "evidence record requires trusted construction"
            )
        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise EvidenceRecordError("schema_version is unsupported")
        require_id(self.run_id, "run_id")
        require_id(self.eval_case_id, "eval_case_id")
        for value, label in (
            (self.eval_case_sha256, "eval_case_sha256"),
            (self.architecture_baseline_sha256, "architecture_baseline_sha256"),
            (self.record_sha256, "record_sha256"),
        ):
            require_sha256(value, label)
        require_base_sha(self.base_sha, "base_sha")
        _validate_optional_fields(self)
        _validate_field_provenance(self)
        require_no_authority(self)
        if self.record_sha256 != sha256_hex(canonical_json(self._body())):
            raise EvidenceRecordError("record_sha256 mismatch")

    def _body(self):
        body = {
            "architecture_baseline_sha256": self.architecture_baseline_sha256,
            "base_sha": self.base_sha,
            "eval_case_id": self.eval_case_id,
            "eval_case_sha256": self.eval_case_sha256,
            "field_provenance": [list(item) for item in self.field_provenance],
            "github_authorized": False,
            "human_acceptance": self.human_acceptance,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "outcome_state": self.outcome_state,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "verifier_result": self.verifier_result,
            "worker_output_trusted": False,
        }
        for name in OPTIONAL_FIELD_NAMES:
            body[name] = getattr(self, name)
        return body

    def to_dict(self):
        body = self._body()
        body["record_sha256"] = self.record_sha256
        return body


def create_evidence_record(
    *,
    run_id,
    eval_case_id,
    eval_case_sha256,
    architecture_baseline_sha256,
    base_sha,
    outcome_state,
    verifier_result=UNKNOWN,
    human_acceptance=UNKNOWN,
    regression_result=UNKNOWN,
    human_review_outcome=UNKNOWN,
    field_provenance=(),
    **optional_fields,
):
    """Seal one evidence record. Every optional field defaults to UNKNOWN.

    Callers pass only the optional fields they actually know (by keyword);
    everything else is recorded as ``UNKNOWN``, never as a fabricated zero.
    ``field_provenance`` must name exactly the optional fields that were
    given a real (non-``UNKNOWN``) value.
    """
    unexpected = set(optional_fields) - set(OPTIONAL_FIELD_NAMES)
    if unexpected:
        raise EvidenceRecordError(
            f"unexpected optional field(s): {sorted(unexpected)}"
        )
    # These five enum fields are also part of OPTIONAL_FIELD_NAMES (they
    # need the same known/UNKNOWN + provenance handling), but they are
    # exposed as named keyword parameters rather than via **optional_fields
    # for API discoverability. Set them first and do not let the generic
    # fill-in loop below clobber them back to UNKNOWN.
    values = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "run_id": run_id,
        "eval_case_id": eval_case_id,
        "eval_case_sha256": eval_case_sha256,
        "architecture_baseline_sha256": architecture_baseline_sha256,
        "base_sha": base_sha,
        "outcome_state": outcome_state,
        "verifier_result": verifier_result,
        "human_acceptance": human_acceptance,
        "regression_result": regression_result,
        "human_review_outcome": human_review_outcome,
    }
    for name in OPTIONAL_FIELD_NAMES:
        if name in values:
            continue
        values[name] = optional_fields.get(name, UNKNOWN)
    values["field_provenance"] = tuple(
        sorted(tuple(item) for item in field_provenance)
    )
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(EvidenceRecord)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return EvidenceRecord(
        **values,
        record_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def evidence_record_is_observational_only():
    """TRUST REVIEW helper: True -- a performance record grants no capability."""
    return True
