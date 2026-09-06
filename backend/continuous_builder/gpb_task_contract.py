"""GP-B1 -- Frozen Task Intent Contract.

Sealed, immutable contract that freezes the approved intent of one coding
task before any decomposition or execution planning occurs.

THE SYSTEM OWNS TRUTH. THE WORKER ONLY PROPOSES. This module plans nothing
and executes nothing: it only seals a contract. A valid contract does not
authorize decomposition execution, provider launch, merge, Main advancement,
capability grants, or any production mutation.

FROZEN TASK CONTRACT vs REVISABLE EXECUTION PLAN
------------------------------------------------
This sealed object is the FROZEN half. Downstream GP-B modules may revise an
execution plan (split/reorder/insert investigation nodes) but must never
silently revise this contract's identity, intent, scope envelope, acceptance,
budget ceiling, risk ceiling, required gates, or base_sha binding. Any such
widening requires an explicit contract-change / escalation request (GP-C+).

Risk / capability fields here are DESCRIPTIVE ONLY. Trusted capability
admission is owned by GP-C / ``trusted_policy``; this contract never grants,
restricts, or implies capability. Risk ceilings are marked
``risk_classification_descriptive_only=True`` and
``capability_admission_deferred_to_gpc=True``.

Reuses GP-A primitives (``gpa_eval_schema``) and architecture-baseline
binding. Does NOT create a competing taxonomy, baseline, or evidence
framework. Read-only. No network. No model call. Zero authority.
"""

from dataclasses import dataclass, field

from .gpa_architecture_baseline import REPOSITORY_IDENTITY
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
from .gpa_task_taxonomy import RISK_INDICATORS, create_gpa_task_taxonomy_v1

TASK_CONTRACT_VERSION = "gpb-task-contract-v1"
GENERATOR_VERSION = "gpb-task-contract-generator-v1"

MAX_GOAL_BYTES = 4096
MAX_INTENT_BYTES = 4096
MAX_TEXT_ITEM_BYTES = 2048
MAX_SCOPE_PATHS = 64
MAX_ACCEPTANCE_ITEMS = 16
MAX_GATES = 16
MAX_CONSTRAINTS = 32
MAX_UNCERTAINTIES = 16
MAX_BUDGET_VALUE = 10**9
MAX_CONTRACT_BYTES = 64 * 1024

_KNOWN_TAXONOMY_CLASS_IDS = frozenset(
    item.class_id for item in create_gpa_task_taxonomy_v1().classes
)

_TOKEN = object()


class TaskContractError(GPAEvalSchemaError):
    """Raised when a frozen task contract cannot be sealed safely."""


def _require_text_tuple(values, label, maximum, *, allow_empty=True):
    if type(values) is not tuple:
        raise TaskContractError(f"{label} is malformed")
    if not allow_empty and not values:
        raise TaskContractError(f"{label} must be non-empty")
    if len(values) > maximum:
        raise TaskContractError(f"{label} exceeds bound")
    return tuple(require_text(v, label, MAX_TEXT_ITEM_BYTES) for v in values)


def _require_budget(value, label):
    if value is None:
        return None
    if type(value) is not int or isinstance(value, bool):
        raise TaskContractError(f"{label} must be an int or None")
    if value <= 0 or value > MAX_BUDGET_VALUE:
        raise TaskContractError(f"{label} is out of bounds")
    return value


def _require_sorted_unique_text(values, label, maximum, allowed=None):
    if type(values) is not tuple:
        raise TaskContractError(f"{label} is malformed")
    if len(values) > maximum:
        raise TaskContractError(f"{label} exceeds bound")
    normalized = tuple(require_text(v, label, MAX_TEXT_ITEM_BYTES) for v in values)
    if normalized != tuple(sorted(set(normalized))):
        raise TaskContractError(f"{label} is not canonical")
    if allowed is not None and any(v not in allowed for v in normalized):
        raise TaskContractError(f"{label} contains an unsupported value")
    return normalized


@dataclass(frozen=True)
class FrozenTaskContract:
    """Sealed intent contract for one coding task. Grants no authority.

    Planning success is never execution permission. Every authority flag is
    structurally False. Risk ceilings are descriptive only (GP-C deferred).
    """

    schema_version: str
    task_contract_id: str
    repository_identity: str
    base_sha: str
    architecture_baseline_sha256: str
    taxonomy_class_id: str
    goal: str
    intent_summary: str
    allowed_scope: tuple
    forbidden_scope: tuple
    acceptance_criteria: tuple
    budget_ceiling_wall_clock_seconds: object
    budget_ceiling_input_tokens: object
    budget_ceiling_output_tokens: object
    budget_ceiling_cost_usd_cents: object
    risk_ceiling_indicators: tuple
    risk_classification_descriptive_only: bool
    capability_admission_deferred_to_gpc: bool
    required_gates: tuple
    constraints: tuple
    uncertainties: tuple
    generator_version: str
    contract_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    # Explicit zero-authority planning flags (never True on a contract).
    execution_authorized: bool = False
    decomposition_execution_authorized: bool = False
    provider_launch_authorized: bool = False
    scope_expansion_authorized: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise TaskContractError(
                "frozen task contract requires trusted construction"
            )
        if self.schema_version != TASK_CONTRACT_VERSION:
            raise TaskContractError("schema_version is unsupported")
        if self.generator_version != GENERATOR_VERSION:
            raise TaskContractError("generator_version is unsupported")
        if self.repository_identity != REPOSITORY_IDENTITY:
            raise TaskContractError("repository_identity is unsupported")
        require_id(self.task_contract_id, "task_contract_id")
        require_base_sha(self.base_sha, "base_sha")
        require_sha256(
            self.architecture_baseline_sha256, "architecture_baseline_sha256"
        )
        if self.taxonomy_class_id not in _KNOWN_TAXONOMY_CLASS_IDS:
            raise TaskContractError("taxonomy_class_id is unknown")
        require_text(self.goal, "goal", MAX_GOAL_BYTES)
        require_text(self.intent_summary, "intent_summary", MAX_INTENT_BYTES)
        allowed = require_sorted_unique_paths(
            self.allowed_scope, "allowed_scope", MAX_SCOPE_PATHS
        )
        forbidden = require_sorted_unique_paths(
            self.forbidden_scope, "forbidden_scope", MAX_SCOPE_PATHS
        )
        if not allowed:
            raise TaskContractError("allowed_scope must be non-empty")
        if set(allowed) & set(forbidden):
            raise TaskContractError(
                "forbidden_scope overlaps allowed_scope"
            )
        _require_text_tuple(
            self.acceptance_criteria,
            "acceptance_criteria",
            MAX_ACCEPTANCE_ITEMS,
            allow_empty=False,
        )
        _require_budget(
            self.budget_ceiling_wall_clock_seconds,
            "budget_ceiling_wall_clock_seconds",
        )
        _require_budget(
            self.budget_ceiling_input_tokens, "budget_ceiling_input_tokens"
        )
        _require_budget(
            self.budget_ceiling_output_tokens, "budget_ceiling_output_tokens"
        )
        _require_budget(
            self.budget_ceiling_cost_usd_cents, "budget_ceiling_cost_usd_cents"
        )
        _require_sorted_unique_text(
            self.risk_ceiling_indicators,
            "risk_ceiling_indicators",
            8,
            allowed=RISK_INDICATORS,
        )
        if self.risk_classification_descriptive_only is not True:
            raise TaskContractError(
                "risk_classification_descriptive_only must be True "
                "(GP-C owns trusted capability admission)"
            )
        if self.capability_admission_deferred_to_gpc is not True:
            raise TaskContractError(
                "capability_admission_deferred_to_gpc must be True"
            )
        _require_sorted_unique_text(
            self.required_gates, "required_gates", MAX_GATES
        )
        _require_text_tuple(self.constraints, "constraints", MAX_CONSTRAINTS)
        _require_text_tuple(
            self.uncertainties, "uncertainties", MAX_UNCERTAINTIES
        )
        require_no_authority(self)
        for name in (
            "execution_authorized",
            "decomposition_execution_authorized",
            "provider_launch_authorized",
            "scope_expansion_authorized",
        ):
            if getattr(self, name) is not False:
                raise TaskContractError(
                    f"GP-B contract cannot claim {name}"
                )
        require_sha256(self.contract_sha256, "contract_sha256")
        if self.contract_sha256 != sha256_hex(canonical_json(self._body())):
            raise TaskContractError("contract_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_CONTRACT_BYTES:
            raise TaskContractError("contract exceeds byte bound")

    def _body(self):
        return {
            "acceptance_criteria": list(self.acceptance_criteria),
            "allowed_scope": list(self.allowed_scope),
            "architecture_baseline_sha256": self.architecture_baseline_sha256,
            "base_sha": self.base_sha,
            "budget_ceiling_cost_usd_cents": self.budget_ceiling_cost_usd_cents,
            "budget_ceiling_input_tokens": self.budget_ceiling_input_tokens,
            "budget_ceiling_output_tokens": self.budget_ceiling_output_tokens,
            "budget_ceiling_wall_clock_seconds": (
                self.budget_ceiling_wall_clock_seconds
            ),
            "capability_admission_deferred_to_gpc": True,
            "constraints": list(self.constraints),
            "decomposition_execution_authorized": False,
            "execution_authorized": False,
            "forbidden_scope": list(self.forbidden_scope),
            "generator_version": self.generator_version,
            "github_authorized": False,
            "goal": self.goal,
            "intent_summary": self.intent_summary,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "provider_launch_authorized": False,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "repository_identity": self.repository_identity,
            "required_gates": list(self.required_gates),
            "result_trusted": False,
            "risk_ceiling_indicators": list(self.risk_ceiling_indicators),
            "risk_classification_descriptive_only": True,
            "schema_version": self.schema_version,
            "scope_expansion_authorized": False,
            "task_contract_id": self.task_contract_id,
            "taxonomy_class_id": self.taxonomy_class_id,
            "uncertainties": list(self.uncertainties),
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["contract_sha256"] = self.contract_sha256
        return body


def create_frozen_task_contract(
    *,
    task_contract_id,
    base_sha,
    architecture_baseline_sha256,
    taxonomy_class_id,
    goal,
    intent_summary,
    allowed_scope,
    forbidden_scope=(),
    acceptance_criteria,
    budget_ceiling_wall_clock_seconds=None,
    budget_ceiling_input_tokens=None,
    budget_ceiling_output_tokens=None,
    budget_ceiling_cost_usd_cents=None,
    risk_ceiling_indicators=("none",),
    required_gates=(),
    constraints=(),
    uncertainties=(),
):
    """Seal a frozen task intent contract. Never grants execution authority."""
    values = {
        "schema_version": TASK_CONTRACT_VERSION,
        "task_contract_id": task_contract_id,
        "repository_identity": REPOSITORY_IDENTITY,
        "base_sha": base_sha,
        "architecture_baseline_sha256": architecture_baseline_sha256,
        "taxonomy_class_id": taxonomy_class_id,
        "goal": goal,
        "intent_summary": intent_summary,
        "allowed_scope": tuple(allowed_scope),
        "forbidden_scope": tuple(forbidden_scope),
        "acceptance_criteria": tuple(acceptance_criteria),
        "budget_ceiling_wall_clock_seconds": budget_ceiling_wall_clock_seconds,
        "budget_ceiling_input_tokens": budget_ceiling_input_tokens,
        "budget_ceiling_output_tokens": budget_ceiling_output_tokens,
        "budget_ceiling_cost_usd_cents": budget_ceiling_cost_usd_cents,
        "risk_ceiling_indicators": tuple(sorted(set(risk_ceiling_indicators))),
        "risk_classification_descriptive_only": True,
        "capability_admission_deferred_to_gpc": True,
        "required_gates": tuple(sorted(set(required_gates))),
        "constraints": tuple(constraints),
        "uncertainties": tuple(uncertainties),
        "generator_version": GENERATOR_VERSION,
        "execution_authorized": False,
        "decomposition_execution_authorized": False,
        "provider_launch_authorized": False,
        "scope_expansion_authorized": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(FrozenTaskContract)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return FrozenTaskContract(
        **values,
        contract_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def task_contract_is_planning_only():
    """TRUST REVIEW helper: True -- contract grants no execution authority."""
    return True


def task_contract_risk_is_descriptive_only():
    """TRUST REVIEW helper: True -- risk fields never admit capability."""
    return True
