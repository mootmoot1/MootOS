"""GP-C2 -- Trusted Capability Admission Input.

Binds proposals that GP-C may evaluate:
- FrozenTaskContract + digest / base_sha / baseline
- ExecutionPlan + digest / escalation flag
- scope-preservation evidence (allowed/forbidden)
- System Model identity (optional)
- trusted policy identity / version + TCB registry digest
- sealed CapabilityRequest tuple

Rejects stale / tampered / mismatched bindings fail-closed. Never grants
capability. Never executes. Does not mutate trusted_policy / TCB.
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
    sha256_hex,
)
from .gpb_decomposer import ExecutionPlan
from .gpb_task_contract import FrozenTaskContract
from .gpc_capability_vocabulary import (
    MAX_REQUESTS,
    CapabilityRequest,
    VOCABULARY_VERSION,
    create_gpc_capability_vocabulary_v1,
)
from .trusted_policy import (
    POLICY_VERSION as TRUSTED_POLICY_VERSION,
    REGISTRY_VERSION,
    create_mootos_tcb_registry_v1,
    create_trusted_policy_snapshot,
)

ADMISSION_INPUT_VERSION = "gpc-admission-input-v1"
GENERATOR_VERSION = "gpc-admission-input-generator-v1"
MAX_INPUT_BYTES = 512 * 1024

_TOKEN = object()


class AdmissionInputError(GPAEvalSchemaError):
    """Raised when admission input cannot be sealed safely."""


@dataclass(frozen=True)
class AdmissionInput:
    """Sealed admission evaluation input. Grants no capability."""

    schema_version: str
    admission_input_id: str
    task_contract_id: str
    contract_sha256: str
    plan_id: str
    plan_sha256: str
    base_sha: str
    architecture_baseline_sha256: str
    allowed_scope: tuple
    forbidden_scope: tuple
    required_gates: tuple
    risk_ceiling_indicators: tuple
    budget_ceiling_wall_clock_seconds: object
    budget_ceiling_input_tokens: object
    budget_ceiling_output_tokens: object
    budget_ceiling_cost_usd_cents: object
    plan_requires_escalation: bool
    plan_escalation_reasons: tuple
    system_model_sha256: object
    system_model_version: object
    trusted_policy_version: str
    tcb_registry_version: str
    tcb_registry_sha256: str
    tcb_protected_path_count: int
    tcb_snapshot_sha256: str
    vocabulary_version: str
    vocabulary_sha256: str
    capability_requests: tuple
    generator_version: str
    input_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    capability_granted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise AdmissionInputError(
                "admission input requires trusted construction"
            )
        if self.schema_version != ADMISSION_INPUT_VERSION:
            raise AdmissionInputError("schema_version unsupported")
        if self.generator_version != GENERATOR_VERSION:
            raise AdmissionInputError("generator_version unsupported")
        require_id(self.admission_input_id, "admission_input_id")
        require_id(self.task_contract_id, "task_contract_id")
        require_id(self.plan_id, "plan_id")
        require_sha256(self.contract_sha256, "contract_sha256")
        require_sha256(self.plan_sha256, "plan_sha256")
        require_base_sha(self.base_sha, "base_sha")
        require_sha256(
            self.architecture_baseline_sha256, "architecture_baseline_sha256"
        )
        if type(self.allowed_scope) is not tuple or not self.allowed_scope:
            raise AdmissionInputError("allowed_scope malformed")
        if type(self.forbidden_scope) is not tuple:
            raise AdmissionInputError("forbidden_scope malformed")
        if type(self.required_gates) is not tuple:
            raise AdmissionInputError("required_gates malformed")
        if type(self.risk_ceiling_indicators) is not tuple:
            raise AdmissionInputError("risk_ceiling_indicators malformed")
        if type(self.plan_requires_escalation) is not bool:
            raise AdmissionInputError("plan_requires_escalation must be bool")
        if type(self.plan_escalation_reasons) is not tuple:
            raise AdmissionInputError("plan_escalation_reasons malformed")
        if self.plan_requires_escalation and not self.plan_escalation_reasons:
            raise AdmissionInputError("escalation requires reasons")
        if self.system_model_sha256 is not None:
            require_sha256(self.system_model_sha256, "system_model_sha256")
        if self.trusted_policy_version != TRUSTED_POLICY_VERSION:
            raise AdmissionInputError("trusted_policy_version mismatch")
        if self.tcb_registry_version != REGISTRY_VERSION:
            raise AdmissionInputError("tcb_registry_version mismatch")
        require_sha256(self.tcb_registry_sha256, "tcb_registry_sha256")
        require_sha256(self.tcb_snapshot_sha256, "tcb_snapshot_sha256")
        if (
            type(self.tcb_protected_path_count) is not int
            or self.tcb_protected_path_count < 1
        ):
            raise AdmissionInputError("tcb_protected_path_count malformed")
        if self.vocabulary_version != VOCABULARY_VERSION:
            raise AdmissionInputError("vocabulary_version mismatch")
        require_sha256(self.vocabulary_sha256, "vocabulary_sha256")
        if type(self.capability_requests) is not tuple:
            raise AdmissionInputError("capability_requests malformed")
        if not self.capability_requests:
            raise AdmissionInputError("capability_requests must be non-empty")
        if len(self.capability_requests) > MAX_REQUESTS:
            raise AdmissionInputError("capability_requests exceeds bound")
        ids = []
        for req in self.capability_requests:
            if not isinstance(req, CapabilityRequest):
                raise AdmissionInputError("capability_requests entry invalid")
            if req.task_contract_id != self.task_contract_id:
                raise AdmissionInputError("request contract id mismatch")
            if req.contract_sha256 != self.contract_sha256:
                raise AdmissionInputError("request contract digest mismatch")
            if req.plan_id != self.plan_id:
                raise AdmissionInputError("request plan id mismatch")
            if req.plan_sha256 != self.plan_sha256:
                raise AdmissionInputError("request plan digest mismatch")
            ids.append(req.request_id)
        if len(ids) != len(set(ids)):
            raise AdmissionInputError("duplicate capability request ids")
        require_no_authority(self)
        if self.execution_authorized is not False:
            raise AdmissionInputError("cannot claim execution_authorized")
        if self.capability_granted is not False:
            raise AdmissionInputError("cannot claim capability_granted")
        require_sha256(self.input_sha256, "input_sha256")
        if self.input_sha256 != sha256_hex(canonical_json(self._body())):
            raise AdmissionInputError("input_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_INPUT_BYTES:
            raise AdmissionInputError("admission input exceeds byte bound")

    def _body(self):
        return {
            "admission_input_id": self.admission_input_id,
            "allowed_scope": list(self.allowed_scope),
            "architecture_baseline_sha256": self.architecture_baseline_sha256,
            "base_sha": self.base_sha,
            "budget_ceiling_cost_usd_cents": self.budget_ceiling_cost_usd_cents,
            "budget_ceiling_input_tokens": self.budget_ceiling_input_tokens,
            "budget_ceiling_output_tokens": self.budget_ceiling_output_tokens,
            "budget_ceiling_wall_clock_seconds": (
                self.budget_ceiling_wall_clock_seconds
            ),
            "capability_granted": False,
            "capability_requests": [
                r.to_dict() for r in self.capability_requests
            ],
            "contract_sha256": self.contract_sha256,
            "execution_authorized": False,
            "forbidden_scope": list(self.forbidden_scope),
            "generator_version": self.generator_version,
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "plan_escalation_reasons": list(self.plan_escalation_reasons),
            "plan_id": self.plan_id,
            "plan_requires_escalation": self.plan_requires_escalation,
            "plan_sha256": self.plan_sha256,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "required_gates": list(self.required_gates),
            "result_trusted": False,
            "risk_ceiling_indicators": list(self.risk_ceiling_indicators),
            "schema_version": self.schema_version,
            "system_model_sha256": self.system_model_sha256,
            "system_model_version": self.system_model_version,
            "task_contract_id": self.task_contract_id,
            "tcb_protected_path_count": self.tcb_protected_path_count,
            "tcb_registry_sha256": self.tcb_registry_sha256,
            "tcb_registry_version": self.tcb_registry_version,
            "tcb_snapshot_sha256": self.tcb_snapshot_sha256,
            "trusted_policy_version": self.trusted_policy_version,
            "vocabulary_sha256": self.vocabulary_sha256,
            "vocabulary_version": self.vocabulary_version,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["input_sha256"] = self.input_sha256
        return body


def create_admission_input(
    *,
    admission_input_id,
    contract,
    plan,
    capability_requests,
    system_model_sha256=None,
    system_model_version=None,
    expected_base_sha=None,
    expected_tcb_registry_sha256=None,
    expected_vocabulary_sha256=None,
):
    """Seal admission input from GP-B contract/plan + capability requests.

    Fail-closed on digest / identity / policy / TCB mismatches. Queries the
    live canonical TCB registry for identity -- never mutates it.
    """
    if not isinstance(contract, FrozenTaskContract):
        raise AdmissionInputError("contract is invalid")
    if not isinstance(plan, ExecutionPlan):
        raise AdmissionInputError("plan is invalid")
    if plan.task_contract_id != contract.task_contract_id:
        raise AdmissionInputError("plan/contract id mismatch")
    if plan.contract_sha256 != contract.contract_sha256:
        raise AdmissionInputError("plan/contract digest mismatch")
    if plan.base_sha != contract.base_sha:
        raise AdmissionInputError("plan/contract base_sha mismatch")
    if (
        plan.architecture_baseline_sha256
        != contract.architecture_baseline_sha256
    ):
        raise AdmissionInputError("plan/contract baseline mismatch")
    if expected_base_sha is not None and contract.base_sha != expected_base_sha:
        raise AdmissionInputError("stale or mismatched base_sha")

    registry = create_mootos_tcb_registry_v1()
    snapshot = create_trusted_policy_snapshot()
    if snapshot.registry_sha256 != registry.registry_sha256:
        raise AdmissionInputError("tcb snapshot/registry digest drift")
    if (
        expected_tcb_registry_sha256 is not None
        and registry.registry_sha256 != expected_tcb_registry_sha256
    ):
        raise AdmissionInputError("stale or mismatched tcb_registry_sha256")

    vocabulary = create_gpc_capability_vocabulary_v1()
    if (
        expected_vocabulary_sha256 is not None
        and vocabulary.vocabulary_sha256 != expected_vocabulary_sha256
    ):
        raise AdmissionInputError("stale or mismatched vocabulary_sha256")

    requests = tuple(capability_requests)
    values = {
        "schema_version": ADMISSION_INPUT_VERSION,
        "admission_input_id": admission_input_id,
        "task_contract_id": contract.task_contract_id,
        "contract_sha256": contract.contract_sha256,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "base_sha": contract.base_sha,
        "architecture_baseline_sha256": contract.architecture_baseline_sha256,
        "allowed_scope": tuple(contract.allowed_scope),
        "forbidden_scope": tuple(contract.forbidden_scope),
        "required_gates": tuple(contract.required_gates),
        "risk_ceiling_indicators": tuple(contract.risk_ceiling_indicators),
        "budget_ceiling_wall_clock_seconds": (
            contract.budget_ceiling_wall_clock_seconds
        ),
        "budget_ceiling_input_tokens": contract.budget_ceiling_input_tokens,
        "budget_ceiling_output_tokens": contract.budget_ceiling_output_tokens,
        "budget_ceiling_cost_usd_cents": contract.budget_ceiling_cost_usd_cents,
        "plan_requires_escalation": plan.requires_escalation,
        "plan_escalation_reasons": tuple(plan.escalation_reasons),
        "system_model_sha256": system_model_sha256,
        "system_model_version": system_model_version,
        "trusted_policy_version": TRUSTED_POLICY_VERSION,
        "tcb_registry_version": REGISTRY_VERSION,
        "tcb_registry_sha256": registry.registry_sha256,
        "tcb_protected_path_count": len(registry.protected_paths),
        "tcb_snapshot_sha256": snapshot.snapshot_sha256,
        "vocabulary_version": VOCABULARY_VERSION,
        "vocabulary_sha256": vocabulary.vocabulary_sha256,
        "capability_requests": requests,
        "generator_version": GENERATOR_VERSION,
        "capability_granted": False,
        "execution_authorized": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(AdmissionInput)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return AdmissionInput(
        **values,
        input_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def admission_input_is_proposal_only():
    """TRUST REVIEW helper: True -- input never admits capability."""
    return True
