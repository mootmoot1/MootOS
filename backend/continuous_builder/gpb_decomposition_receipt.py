"""GP-B7 -- Decomposition Receipt / Provenance.

Sealed provenance record for one decomposition run. Binds:
- frozen task contract identity + digest
- architecture baseline digest
- System Model identity
- Context Engine version + source digest (when provided)
- decomposer version
- node/edge counts, uncertainty/escalation counts
- plan digest

A valid receipt / plan is NOT approved to execute. Zero authority.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .context_engine import ENGINE_VERSION
from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    canonical_json,
    require_base_sha,
    require_no_authority,
    require_sha256,
    sha256_hex,
)
from .gpb_decomposer import DECOMPOSER_VERSION, ExecutionPlan
from .gpb_task_contract import FrozenTaskContract
from .system_model import SystemModel

RECEIPT_VERSION = "gpb-decomposition-receipt-v1"
CONTEXT_ENGINE_MODULE_PATH = "backend/continuous_builder/context_engine.py"
MAX_RECEIPT_BYTES = 32 * 1024

_TOKEN = object()


class DecompositionReceiptError(GPAEvalSchemaError):
    """Raised when a decomposition receipt cannot be sealed safely."""


@dataclass(frozen=True)
class DecompositionReceipt:
    """Sealed provenance for one planning-only decomposition."""

    schema_version: str
    task_contract_id: str
    contract_sha256: str
    architecture_baseline_sha256: str
    base_sha: str
    system_model_sha256: object
    system_model_version: object
    context_engine_version: str
    context_engine_source_sha256: object
    decomposer_version: str
    plan_id: str
    plan_sha256: str
    node_count: int
    edge_count: int
    uncertainty_count: int
    escalation_count: int
    requires_escalation: bool
    receipt_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    approved_to_execute: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise DecompositionReceiptError(
                "decomposition receipt requires trusted construction"
            )
        if self.schema_version != RECEIPT_VERSION:
            raise DecompositionReceiptError("schema_version is unsupported")
        if self.decomposer_version != DECOMPOSER_VERSION:
            raise DecompositionReceiptError("decomposer_version is unsupported")
        if self.context_engine_version != ENGINE_VERSION:
            raise DecompositionReceiptError(
                "context_engine_version is unsupported"
            )
        require_base_sha(self.base_sha, "base_sha")
        require_sha256(self.contract_sha256, "contract_sha256")
        require_sha256(
            self.architecture_baseline_sha256, "architecture_baseline_sha256"
        )
        require_sha256(self.plan_sha256, "plan_sha256")
        if self.system_model_sha256 is not None:
            require_sha256(self.system_model_sha256, "system_model_sha256")
        if self.context_engine_source_sha256 is not None:
            require_sha256(
                self.context_engine_source_sha256,
                "context_engine_source_sha256",
            )
        for name in (
            "node_count",
            "edge_count",
            "uncertainty_count",
            "escalation_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise DecompositionReceiptError(f"{name} is malformed")
        require_no_authority(self)
        if self.execution_authorized is not False:
            raise DecompositionReceiptError("cannot claim execution_authorized")
        if self.approved_to_execute is not False:
            raise DecompositionReceiptError(
                "valid plan receipt is never approved_to_execute"
            )
        require_sha256(self.receipt_sha256, "receipt_sha256")
        if self.receipt_sha256 != sha256_hex(canonical_json(self._body())):
            raise DecompositionReceiptError("receipt_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_RECEIPT_BYTES:
            raise DecompositionReceiptError("receipt exceeds byte bound")

    def _body(self):
        return {
            "architecture_baseline_sha256": self.architecture_baseline_sha256,
            "approved_to_execute": False,
            "base_sha": self.base_sha,
            "context_engine_source_sha256": self.context_engine_source_sha256,
            "context_engine_version": self.context_engine_version,
            "contract_sha256": self.contract_sha256,
            "decomposer_version": self.decomposer_version,
            "edge_count": self.edge_count,
            "escalation_count": self.escalation_count,
            "execution_authorized": False,
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "node_count": self.node_count,
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "requires_escalation": self.requires_escalation,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "system_model_sha256": self.system_model_sha256,
            "system_model_version": self.system_model_version,
            "task_contract_id": self.task_contract_id,
            "uncertainty_count": self.uncertainty_count,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["receipt_sha256"] = self.receipt_sha256
        return body


def _context_engine_source_digest(repo_root):
    if repo_root is None:
        return None
    path = Path(repo_root) / CONTEXT_ENGINE_MODULE_PATH
    try:
        return sha256_hex(path.read_bytes())
    except OSError as error:
        raise DecompositionReceiptError(
            "context_engine module source is unreadable"
        ) from error


def create_decomposition_receipt(
    contract,
    plan,
    *,
    model=None,
    repo_root=None,
    uncertainty_count=0,
):
    """Seal a provenance receipt for one decomposition plan.

    Never sets approved_to_execute. Planning success != execution permission.
    """
    if not isinstance(contract, FrozenTaskContract):
        raise DecompositionReceiptError("contract is invalid")
    if not isinstance(plan, ExecutionPlan):
        raise DecompositionReceiptError("plan is invalid")
    if plan.contract_sha256 != contract.contract_sha256:
        raise DecompositionReceiptError("plan/contract digest mismatch")
    if plan.task_contract_id != contract.task_contract_id:
        raise DecompositionReceiptError("plan/contract id mismatch")

    sm_sha = None
    sm_ver = None
    if model is not None:
        if not isinstance(model, SystemModel):
            raise DecompositionReceiptError("model is invalid")
        sm_sha = model.model_sha256
        sm_ver = model.model_version

    ce_digest = _context_engine_source_digest(repo_root)
    escalation_count = len(plan.escalation_reasons)
    # Count node-level uncertainties that are not the UNKNOWN sentinel alone
    # plus plan escalation; caller may pass an explicit uncertainty_count from
    # impact evidence.
    if type(uncertainty_count) is not int or uncertainty_count < 0:
        raise DecompositionReceiptError("uncertainty_count is malformed")

    values = {
        "schema_version": RECEIPT_VERSION,
        "task_contract_id": contract.task_contract_id,
        "contract_sha256": contract.contract_sha256,
        "architecture_baseline_sha256": contract.architecture_baseline_sha256,
        "base_sha": contract.base_sha,
        "system_model_sha256": sm_sha,
        "system_model_version": sm_ver,
        "context_engine_version": ENGINE_VERSION,
        "context_engine_source_sha256": ce_digest,
        "decomposer_version": DECOMPOSER_VERSION,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "node_count": len(plan.nodes),
        "edge_count": len(plan.edges),
        "uncertainty_count": uncertainty_count,
        "escalation_count": escalation_count,
        "requires_escalation": plan.requires_escalation,
        "execution_authorized": False,
        "approved_to_execute": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(DecompositionReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return DecompositionReceipt(
        **values,
        receipt_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def decomposition_receipt_is_planning_only():
    """TRUST REVIEW helper: True -- receipt never authorizes execution."""
    return True
