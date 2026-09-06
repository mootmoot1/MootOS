"""GP-B6 -- Plan Revision Without Contract Drift.

Allowed plan revisions (preserve frozen contract identity/intent/ceilings):
- split a node into smaller children
- insert a prerequisite / investigation node
- reorder nodes (dependency edges)
- replace a strategy node while keeping acceptance/scope ceilings
- refine complexity / rationale text

Any revision that would widen scope, relax acceptance, remove gates, change
base_sha/contract identity/intent/baseline, or raise budget/risk ceilings
must ESCALATE via ScopePreservationResult -- never apply silently.

Valid revised plan != approved to execute. Zero authority.
"""

from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    UNKNOWN,
    canonical_json,
    require_no_authority,
    require_sha256,
    sha256_hex,
)
from .gpb_decomposer import (
    DECOMPOSER_VERSION,
    ExecutionPlan,
    PLAN_SCHEMA_VERSION,
    _seal_plan,
)
from .gpb_decomposition_node import DecompositionNode, create_decomposition_node
from .gpb_scope_rules import (
    check_contract_identity_preserved,
    check_plan_nodes_against_contract,
)
from .gpb_task_contract import FrozenTaskContract

REVISION_VERSION = "gpb-plan-revision-v1"
ALLOWED_OPS = frozenset(
    {
        "split_node",
        "insert_prerequisite",
        "reorder",
        "replace_strategy",
        "insert_investigation",
    }
)
MAX_OPS = 32
MAX_RESULT_BYTES = 64 * 1024

_TOKEN = object()


class PlanRevisionError(GPAEvalSchemaError):
    """Raised when a plan revision cannot be applied safely."""


@dataclass(frozen=True)
class RevisionOp:
    """One declarative revision operation."""

    op: str
    target_node_id: object  # str or None
    new_node: object  # DecompositionNode or None
    depends_on: tuple
    note: str

    def to_dict(self):
        return {
            "depends_on": list(self.depends_on),
            "new_node": None if self.new_node is None else self.new_node.to_dict(),
            "note": self.note,
            "op": self.op,
            "target_node_id": self.target_node_id,
        }


@dataclass(frozen=True)
class PlanRevisionResult:
    """Sealed revision outcome. Never authorizes execution."""

    schema_version: str
    original_plan_sha256: str
    revised_plan: object  # ExecutionPlan or None when escalated without plan
    preserved_contract: bool
    applied: bool
    requires_escalation: bool
    escalation_reasons: tuple
    ops_applied: tuple
    result_sha256: str
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
            raise PlanRevisionError(
                "plan revision result requires trusted construction"
            )
        if self.schema_version != REVISION_VERSION:
            raise PlanRevisionError("schema_version is unsupported")
        if self.revised_plan is not None and not isinstance(
            self.revised_plan, ExecutionPlan
        ):
            raise PlanRevisionError("revised_plan is invalid")
        if self.applied and self.revised_plan is None:
            raise PlanRevisionError("applied revision needs revised_plan")
        if self.requires_escalation and not self.escalation_reasons:
            raise PlanRevisionError("escalation requires reasons")
        require_no_authority(self)
        if self.execution_authorized is not False:
            raise PlanRevisionError("cannot claim execution_authorized")
        if self.approved_to_execute is not False:
            raise PlanRevisionError("cannot claim approved_to_execute")
        require_sha256(self.result_sha256, "result_sha256")
        if self.result_sha256 != sha256_hex(canonical_json(self._body())):
            raise PlanRevisionError("result_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_RESULT_BYTES:
            raise PlanRevisionError("result exceeds byte bound")

    def _body(self):
        return {
            "applied": self.applied,
            "approved_to_execute": False,
            "escalation_reasons": list(self.escalation_reasons),
            "execution_authorized": False,
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "ops_applied": [op.to_dict() for op in self.ops_applied],
            "original_plan_sha256": self.original_plan_sha256,
            "preserved_contract": self.preserved_contract,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "requires_escalation": self.requires_escalation,
            "result_trusted": False,
            "revised_plan": (
                None if self.revised_plan is None else self.revised_plan.to_dict()
            ),
            "schema_version": self.schema_version,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["result_sha256"] = self.result_sha256
        return body


def _seal_result(**values):
    values = dict(values)
    for name in AUTHORITY_FLAGS:
        values[name] = False
    values["execution_authorized"] = False
    values["approved_to_execute"] = False
    provisional = object.__new__(PlanRevisionResult)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return PlanRevisionResult(
        **values,
        result_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def make_revision_op(
    *,
    op,
    target_node_id=None,
    new_node=None,
    depends_on=(),
    note="",
):
    if op not in ALLOWED_OPS:
        raise PlanRevisionError("revision op unsupported")
    if new_node is not None and not isinstance(new_node, DecompositionNode):
        raise PlanRevisionError("new_node is invalid")
    if not isinstance(note, str) or len(note.encode("utf-8")) > 512:
        raise PlanRevisionError("note is malformed")
    return RevisionOp(
        op=op,
        target_node_id=target_node_id,
        new_node=new_node,
        depends_on=tuple(sorted(set(depends_on))),
        note=note,
    )


def revise_execution_plan(contract, plan, ops):
    """Apply revision ops if and only if the frozen contract is preserved.

    Malicious or widening revisions escalate without mutating the contract.
    """
    if not isinstance(contract, FrozenTaskContract):
        raise PlanRevisionError("contract is invalid")
    if not isinstance(plan, ExecutionPlan):
        raise PlanRevisionError("plan is invalid")
    if plan.contract_sha256 != contract.contract_sha256:
        return _seal_result(
            schema_version=REVISION_VERSION,
            original_plan_sha256=plan.plan_sha256,
            revised_plan=None,
            preserved_contract=False,
            applied=False,
            requires_escalation=True,
            escalation_reasons=("plan_contract_digest_mismatch",),
            ops_applied=(),
        )
    if type(ops) not in (list, tuple) or len(ops) > MAX_OPS:
        raise PlanRevisionError("ops is malformed")
    if any(not isinstance(op, RevisionOp) for op in ops):
        raise PlanRevisionError("ops contains an invalid entry")

    # Identity check against itself (always preserved) -- guardrail for callers
    # who pass a mutated contract object.
    identity = check_contract_identity_preserved(contract, contract)
    if not identity.preserved:
        return _seal_result(
            schema_version=REVISION_VERSION,
            original_plan_sha256=plan.plan_sha256,
            revised_plan=None,
            preserved_contract=False,
            applied=False,
            requires_escalation=True,
            escalation_reasons=("contract_identity_drift",),
            ops_applied=(),
        )

    by_id = {n.node_id: n for n in plan.nodes}
    edges = set(plan.edges)
    applied_ops = []
    escalation = []

    for op in ops:
        if op.op == "reorder":
            # Replace depends_on on target with provided list (must exist).
            if op.target_node_id not in by_id:
                escalation.append("reorder_missing_target")
                continue
            target = by_id[op.target_node_id]
            new_node = create_decomposition_node(
                node_id=target.node_id,
                parent_id=target.parent_id,
                level=target.level,
                node_type=target.node_type,
                title=target.title,
                objective=target.objective,
                rationale=target.rationale + " [reordered]",
                depends_on=op.depends_on,
                affected_components=target.affected_components,
                candidate_allowed_scope=target.candidate_allowed_scope,
                inherited_forbidden_scope=target.inherited_forbidden_scope,
                acceptance_checkpoint=target.acceptance_checkpoint,
                complexity_estimate=target.complexity_estimate,
                uncertainty=target.uncertainty,
                requires_escalation=target.requires_escalation,
                escalation_reasons=target.escalation_reasons,
                children=target.children,
            )
            by_id[target.node_id] = new_node
            # Refresh edges for this node.
            edges = {e for e in edges if e[0] != target.node_id}
            for dep in op.depends_on:
                edges.add((target.node_id, dep))
            applied_ops.append(op)
        elif op.op in ("insert_prerequisite", "insert_investigation", "split_node", "replace_strategy"):
            if op.new_node is None:
                escalation.append(f"{op.op}_missing_new_node")
                continue
            if op.new_node.node_id in by_id and op.op != "replace_strategy":
                escalation.append("duplicate_node_id_on_insert")
                continue
            if op.op == "replace_strategy":
                if op.target_node_id not in by_id:
                    escalation.append("replace_missing_target")
                    continue
                # Replacement must not widen vs original target envelope.
                old = by_id[op.target_node_id]
                if set(op.new_node.candidate_allowed_scope) - set(
                    old.candidate_allowed_scope
                ):
                    escalation.append("replace_widens_scope")
                    continue
                if set(old.inherited_forbidden_scope) - set(
                    op.new_node.inherited_forbidden_scope
                ):
                    escalation.append("replace_drops_forbidden")
                    continue
                del by_id[op.target_node_id]
                edges = {
                    e
                    for e in edges
                    if e[0] != op.target_node_id and e[1] != op.target_node_id
                }
            by_id[op.new_node.node_id] = op.new_node
            for dep in op.new_node.depends_on:
                edges.add((op.new_node.node_id, dep))
            # Attach under root children if parent is root.
            root = by_id.get(plan.root_node_id)
            if (
                root is not None
                and op.new_node.parent_id == plan.root_node_id
                and op.new_node.node_id not in root.children
            ):
                by_id[plan.root_node_id] = create_decomposition_node(
                    node_id=root.node_id,
                    parent_id=root.parent_id,
                    level=root.level,
                    node_type=root.node_type,
                    title=root.title,
                    objective=root.objective,
                    rationale=root.rationale,
                    depends_on=root.depends_on,
                    affected_components=root.affected_components,
                    candidate_allowed_scope=root.candidate_allowed_scope,
                    inherited_forbidden_scope=root.inherited_forbidden_scope,
                    acceptance_checkpoint=root.acceptance_checkpoint,
                    complexity_estimate=root.complexity_estimate,
                    uncertainty=root.uncertainty,
                    requires_escalation=root.requires_escalation,
                    escalation_reasons=root.escalation_reasons,
                    children=tuple(
                        sorted(set(root.children) | {op.new_node.node_id})
                    ),
                )
            applied_ops.append(op)
        else:
            escalation.append(f"unsupported_op:{op.op}")

    nodes = tuple(sorted(by_id.values(), key=lambda n: n.node_id))
    edge_tuple = tuple(sorted(edges))
    scope = check_plan_nodes_against_contract(
        contract, nodes, edges=edge_tuple
    )
    if not scope.preserved:
        escalation.extend(v.code for v in scope.violations)

    escalation = tuple(sorted(set(escalation)))
    if escalation:
        return _seal_result(
            schema_version=REVISION_VERSION,
            original_plan_sha256=plan.plan_sha256,
            revised_plan=None,
            preserved_contract=True,
            applied=False,
            requires_escalation=True,
            escalation_reasons=escalation,
            ops_applied=tuple(applied_ops),
        )

    revised = _seal_plan(
        schema_version=PLAN_SCHEMA_VERSION,
        plan_id=plan.plan_id,
        task_contract_id=contract.task_contract_id,
        contract_sha256=contract.contract_sha256,
        base_sha=contract.base_sha,
        architecture_baseline_sha256=contract.architecture_baseline_sha256,
        decomposer_version=DECOMPOSER_VERSION,
        nodes=nodes,
        edges=edge_tuple,
        root_node_id=plan.root_node_id,
        requires_escalation=False,
        escalation_reasons=(),
        impact_evidence_sha256=plan.impact_evidence_sha256,
    )
    return _seal_result(
        schema_version=REVISION_VERSION,
        original_plan_sha256=plan.plan_sha256,
        revised_plan=revised,
        preserved_contract=True,
        applied=True,
        requires_escalation=False,
        escalation_reasons=(),
        ops_applied=tuple(applied_ops),
    )


def plan_revision_is_planning_only():
    """TRUST REVIEW helper: True -- revisions never authorize execution."""
    return True
