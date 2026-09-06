"""GP-A3 -- Frozen Evaluation Case Contract.

One immutable benchmark task, structurally split into two halves so a
worker-facing adapter can never accidentally leak the answer:

- ``EvalCaseWorkerView`` -- everything a worker is allowed to see: the
  goal, allowed/forbidden scope, context inputs, required artifacts, and
  descriptive budget caps.
- ``EvalCaseEvaluatorView`` -- evaluator-only ground truth: acceptance
  criteria, expected verification commands, ground-truth notes, and known
  uncertainties. This half is never included in
  :func:`to_worker_visible_dict`.

``EvalCase`` binds both halves plus identity (case ID, schema version,
taxonomy class, base SHA/fixture identity) under one deterministic digest,
so a tampered or resealed case is detectable.

Read-only. No network. No model call. Zero authority: an eval case
describes a benchmark task, it does not grant scope, authorize a worker,
or trust any claimed outcome.
"""

from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    canonical_json,
    require_base_sha,
    require_id,
    require_no_authority,
    require_sha256,
    require_sorted_unique_paths,
    require_text,
    sha256_hex,
)
from .gpa_task_taxonomy import create_gpa_task_taxonomy_v1

EVAL_CASE_VERSION = "gpa-eval-case-v1"

MAX_GOAL_BYTES = 4096
MAX_TEXT_ITEM_BYTES = 2048
MAX_SCOPE_PATHS = 64
MAX_CONTEXT_INPUTS = 32
MAX_ARTIFACTS = 16
MAX_ACCEPTANCE_ITEMS = 16
MAX_VERIFICATION_COMMANDS = 16
MAX_UNCERTAINTIES = 16
MAX_NOTES_BYTES = 4096
MAX_BUDGET_VALUE = 10**9

_KNOWN_TAXONOMY_CLASS_IDS = frozenset(
    item.class_id for item in create_gpa_task_taxonomy_v1().classes
)

# Keys that must never appear in a worker-visible payload.
EVALUATOR_ONLY_KEYS = frozenset(
    {
        "evaluator_view",
        "acceptance_criteria",
        "expected_verification_commands",
        "ground_truth_notes",
        "known_uncertainties",
        "evaluator_view_sha256",
    }
)

_WORKER_TOKEN = object()
_EVALUATOR_TOKEN = object()
_CASE_TOKEN = object()


class EvalCaseError(GPAEvalSchemaError):
    """Raised when an eval case contract is invalid."""


def _require_text_tuple(values, label, maximum, *, allow_empty=True):
    if type(values) is not tuple:
        raise EvalCaseError(f"{label} is malformed")
    if not allow_empty and not values:
        raise EvalCaseError(f"{label} must be non-empty")
    if len(values) > maximum:
        raise EvalCaseError(f"{label} exceeds bound")
    return tuple(require_text(v, label, MAX_TEXT_ITEM_BYTES) for v in values)


def _require_budget(value, label):
    if value is None:
        return None
    if type(value) is not int or isinstance(value, bool):
        raise EvalCaseError(f"{label} must be an int or None")
    if value <= 0 or value > MAX_BUDGET_VALUE:
        raise EvalCaseError(f"{label} is out of bounds")
    return value


@dataclass(frozen=True)
class EvalCaseWorkerView:
    """Everything a worker is permitted to see for one eval case."""

    goal: str
    allowed_scope: tuple
    forbidden_scope: tuple
    context_inputs: tuple
    required_artifacts: tuple
    max_wall_clock_seconds: object
    max_input_tokens: object
    max_output_tokens: object
    max_cost_usd_cents: object
    worker_view_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _WORKER_TOKEN:
            raise EvalCaseError(
                "worker view requires trusted construction"
            )
        require_text(self.goal, "goal", MAX_GOAL_BYTES)
        allowed = require_sorted_unique_paths(
            self.allowed_scope, "allowed_scope", MAX_SCOPE_PATHS
        )
        if not allowed:
            raise EvalCaseError("allowed_scope must be non-empty")
        object.__setattr__(self, "allowed_scope", allowed)
        forbidden = require_sorted_unique_paths(
            self.forbidden_scope, "forbidden_scope", MAX_SCOPE_PATHS
        )
        object.__setattr__(self, "forbidden_scope", forbidden)
        if set(allowed) & set(forbidden):
            raise EvalCaseError("allowed_scope and forbidden_scope overlap")
        object.__setattr__(
            self,
            "context_inputs",
            _require_text_tuple(
                self.context_inputs, "context_inputs", MAX_CONTEXT_INPUTS
            ),
        )
        object.__setattr__(
            self,
            "required_artifacts",
            _require_text_tuple(
                self.required_artifacts, "required_artifacts", MAX_ARTIFACTS
            ),
        )
        for name in (
            "max_wall_clock_seconds",
            "max_input_tokens",
            "max_output_tokens",
            "max_cost_usd_cents",
        ):
            object.__setattr__(
                self, name, _require_budget(getattr(self, name), name)
            )
        require_sha256(self.worker_view_sha256, "worker_view_sha256")
        if self.worker_view_sha256 != sha256_hex(canonical_json(self._body())):
            raise EvalCaseError("worker_view_sha256 mismatch")

    def _body(self):
        return {
            "allowed_scope": list(self.allowed_scope),
            "context_inputs": list(self.context_inputs),
            "forbidden_scope": list(self.forbidden_scope),
            "goal": self.goal,
            "max_cost_usd_cents": self.max_cost_usd_cents,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_wall_clock_seconds": self.max_wall_clock_seconds,
            "required_artifacts": list(self.required_artifacts),
        }

    def to_dict(self):
        body = self._body()
        body["worker_view_sha256"] = self.worker_view_sha256
        return body


def _seal_worker_view(**values):
    provisional = object.__new__(EvalCaseWorkerView)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return EvalCaseWorkerView(
        **values,
        worker_view_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_WORKER_TOKEN,
    )


@dataclass(frozen=True)
class EvalCaseEvaluatorView:
    """Evaluator-only ground truth for one eval case. Never worker-visible."""

    acceptance_criteria: tuple
    expected_verification_commands: tuple
    ground_truth_notes: str
    known_uncertainties: tuple
    evaluator_view_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _EVALUATOR_TOKEN:
            raise EvalCaseError(
                "evaluator view requires trusted construction"
            )
        object.__setattr__(
            self,
            "acceptance_criteria",
            _require_text_tuple(
                self.acceptance_criteria,
                "acceptance_criteria",
                MAX_ACCEPTANCE_ITEMS,
                allow_empty=False,
            ),
        )
        object.__setattr__(
            self,
            "expected_verification_commands",
            _require_text_tuple(
                self.expected_verification_commands,
                "expected_verification_commands",
                MAX_VERIFICATION_COMMANDS,
            ),
        )
        if not isinstance(self.ground_truth_notes, str):
            raise EvalCaseError("ground_truth_notes must be text")
        if len(self.ground_truth_notes.encode("utf-8")) > MAX_NOTES_BYTES:
            raise EvalCaseError("ground_truth_notes exceeds byte bound")
        object.__setattr__(
            self,
            "known_uncertainties",
            _require_text_tuple(
                self.known_uncertainties,
                "known_uncertainties",
                MAX_UNCERTAINTIES,
            ),
        )
        require_sha256(self.evaluator_view_sha256, "evaluator_view_sha256")
        if self.evaluator_view_sha256 != sha256_hex(
            canonical_json(self._body())
        ):
            raise EvalCaseError("evaluator_view_sha256 mismatch")

    def _body(self):
        return {
            "acceptance_criteria": list(self.acceptance_criteria),
            "expected_verification_commands": list(
                self.expected_verification_commands
            ),
            "ground_truth_notes": self.ground_truth_notes,
            "known_uncertainties": list(self.known_uncertainties),
        }

    def to_dict(self):
        body = self._body()
        body["evaluator_view_sha256"] = self.evaluator_view_sha256
        return body


def _seal_evaluator_view(**values):
    provisional = object.__new__(EvalCaseEvaluatorView)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return EvalCaseEvaluatorView(
        **values,
        evaluator_view_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_EVALUATOR_TOKEN,
    )


@dataclass(frozen=True)
class EvalCase:
    """One frozen, sealed benchmark task. Zero authority."""

    eval_case_id: str
    schema_version: str
    taxonomy_class_id: str
    base_sha: str
    worker_view: EvalCaseWorkerView
    evaluator_view: EvalCaseEvaluatorView
    case_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _CASE_TOKEN:
            raise EvalCaseError("eval case requires trusted construction")
        require_id(self.eval_case_id, "eval_case_id")
        if self.schema_version != EVAL_CASE_VERSION:
            raise EvalCaseError("schema_version is unsupported")
        if self.taxonomy_class_id not in _KNOWN_TAXONOMY_CLASS_IDS:
            raise EvalCaseError("taxonomy_class_id is unknown")
        require_base_sha(self.base_sha, "base_sha")
        if not isinstance(self.worker_view, EvalCaseWorkerView):
            raise EvalCaseError("worker_view is invalid")
        if not isinstance(self.evaluator_view, EvalCaseEvaluatorView):
            raise EvalCaseError("evaluator_view is invalid")
        require_no_authority(self)
        require_sha256(self.case_sha256, "case_sha256")
        if self.case_sha256 != sha256_hex(canonical_json(self._body())):
            raise EvalCaseError("case_sha256 mismatch")

    def _body(self):
        return {
            "base_sha": self.base_sha,
            "eval_case_id": self.eval_case_id,
            "evaluator_view": self.evaluator_view.to_dict(),
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "taxonomy_class_id": self.taxonomy_class_id,
            "worker_output_trusted": False,
            "worker_view": self.worker_view.to_dict(),
        }

    def to_dict(self):
        body = self._body()
        body["case_sha256"] = self.case_sha256
        return body


def create_eval_case(
    *,
    eval_case_id,
    taxonomy_class_id,
    base_sha,
    goal,
    allowed_scope,
    forbidden_scope=(),
    context_inputs=(),
    required_artifacts=(),
    max_wall_clock_seconds=None,
    max_input_tokens=None,
    max_output_tokens=None,
    max_cost_usd_cents=None,
    acceptance_criteria,
    expected_verification_commands=(),
    ground_truth_notes="",
    known_uncertainties=(),
):
    """Seal one frozen eval case from plain worker/evaluator inputs."""
    worker_view = _seal_worker_view(
        goal=goal,
        allowed_scope=tuple(allowed_scope),
        forbidden_scope=tuple(forbidden_scope),
        context_inputs=tuple(context_inputs),
        required_artifacts=tuple(required_artifacts),
        max_wall_clock_seconds=max_wall_clock_seconds,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        max_cost_usd_cents=max_cost_usd_cents,
    )
    evaluator_view = _seal_evaluator_view(
        acceptance_criteria=tuple(acceptance_criteria),
        expected_verification_commands=tuple(expected_verification_commands),
        ground_truth_notes=ground_truth_notes,
        known_uncertainties=tuple(known_uncertainties),
    )
    values = {
        "eval_case_id": eval_case_id,
        "schema_version": EVAL_CASE_VERSION,
        "taxonomy_class_id": taxonomy_class_id,
        "base_sha": base_sha,
        "worker_view": worker_view,
        "evaluator_view": evaluator_view,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(EvalCase)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return EvalCase(
        **values,
        case_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_CASE_TOKEN,
    )


def to_worker_visible_dict(case):
    """Serialize only the half of ``case`` a worker is allowed to see.

    Structurally excludes ``evaluator_view`` -- there is no parameter or
    code path that can add it back in. Callers that need the full case
    (the offline harness, evidence capture) use ``case.to_dict()``
    directly instead of this function.
    """
    if not isinstance(case, EvalCase):
        raise EvalCaseError("case is invalid")
    return {
        "eval_case_id": case.eval_case_id,
        "schema_version": case.schema_version,
        "taxonomy_class_id": case.taxonomy_class_id,
        "base_sha": case.base_sha,
        "worker_view": case.worker_view.to_dict(),
    }


def verify_no_evaluator_leakage(worker_payload):
    """True iff ``worker_payload`` contains no evaluator-only key, anywhere.

    Recurses into nested dicts/lists so a caller that accidentally nests an
    evaluator view inside another structure is still caught.
    """

    def _walk(value):
        if isinstance(value, dict):
            if EVALUATOR_ONLY_KEYS & value.keys():
                return False
            return all(_walk(v) for v in value.values())
        if isinstance(value, (list, tuple)):
            return all(_walk(v) for v in value)
        return True

    return _walk(worker_payload)


def eval_case_is_descriptive_only():
    """TRUST REVIEW helper: True -- an eval case grants no capability."""
    return True
