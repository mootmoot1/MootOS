"""GP-B5 -- Deterministic Decomposition Strategy.

Rule-based hierarchical task decomposition. NO LLM / provider calls.
Signals used (in order of preference):

- component boundaries from System Model impact evidence
- dependency order between affected components
- ownership / UNKNOWN ownership -> investigation first
- test vs implementation separation when both appear in scope
- migration / verification / TCB-adjacency flags
- acceptance checkpoints (preferred over arbitrary file/line counts)
- complexity bounds and uncertainty

Avoids ceremony: no max-3-files rule, no always-5-slices rule. Variable
depth: simple tasks stay goal->atomic; larger multi-component tasks become
goal->slice(s)->atomic; TCB-adjacent / high uncertainty inserts investigation
nodes and marks escalation.

Produces a sealed ExecutionPlan bound to a FrozenTaskContract. A valid plan
is NEVER approved to execute. Zero authority.
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
from .gpb_decomposition_node import create_decomposition_node
from .gpb_impact_evidence import (
    DecompositionImpactEvidence,
    collect_impact_evidence,
)
from .gpb_scope_rules import check_plan_nodes_against_contract
from .gpb_task_contract import FrozenTaskContract
from .system_model import SystemModel

DECOMPOSER_VERSION = "gpb-decomposer-v1"
PLAN_SCHEMA_VERSION = "gpb-execution-plan-v1"
MAX_NODES = 64
MAX_EDGES = 128
MAX_PLAN_BYTES = 256 * 1024

# Soft complexity hints -- never hard ceremony caps.
_MULTI_COMPONENT_SLICE_THRESHOLD = 2
_LARGE_SCOPE_PATH_THRESHOLD = 4

_TOKEN = object()


class DecomposerError(GPAEvalSchemaError):
    """Raised when deterministic decomposition cannot proceed safely."""


@dataclass(frozen=True)
class ExecutionPlan:
    """Sealed revisable execution plan bound to a frozen task contract.

    Plan revision (GP-B6) may change nodes/edges while preserving contract
    identity. This object never authorizes execution.
    """

    schema_version: str
    plan_id: str
    task_contract_id: str
    contract_sha256: str
    base_sha: str
    architecture_baseline_sha256: str
    decomposer_version: str
    nodes: tuple
    edges: tuple  # tuple of (from_id, to_id) dependency edges
    root_node_id: str
    requires_escalation: bool
    escalation_reasons: tuple
    impact_evidence_sha256: object  # str or None
    plan_sha256: str
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
            raise DecomposerError(
                "execution plan requires trusted construction"
            )
        if self.schema_version != PLAN_SCHEMA_VERSION:
            raise DecomposerError("schema_version is unsupported")
        if self.decomposer_version != DECOMPOSER_VERSION:
            raise DecomposerError("decomposer_version is unsupported")
        if type(self.nodes) is not tuple or not self.nodes:
            raise DecomposerError("nodes is malformed")
        if len(self.nodes) > MAX_NODES:
            raise DecomposerError("nodes exceeds bound")
        ids = [n.node_id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise DecomposerError("duplicate node IDs")
        if self.root_node_id not in ids:
            raise DecomposerError("root_node_id missing from nodes")
        if type(self.edges) is not tuple or len(self.edges) > MAX_EDGES:
            raise DecomposerError("edges is malformed")
        for edge in self.edges:
            if type(edge) is not tuple or len(edge) != 2:
                raise DecomposerError("edges entry malformed")
        if type(self.requires_escalation) is not bool:
            raise DecomposerError("requires_escalation must be bool")
        if type(self.escalation_reasons) is not tuple:
            raise DecomposerError("escalation_reasons is malformed")
        if self.requires_escalation and not self.escalation_reasons:
            raise DecomposerError("escalation requires reasons")
        if self.impact_evidence_sha256 is not None:
            require_sha256(
                self.impact_evidence_sha256, "impact_evidence_sha256"
            )
        require_no_authority(self)
        if self.execution_authorized is not False:
            raise DecomposerError("cannot claim execution_authorized")
        if self.approved_to_execute is not False:
            raise DecomposerError("valid plan is never approved_to_execute")
        require_sha256(self.plan_sha256, "plan_sha256")
        if self.plan_sha256 != sha256_hex(canonical_json(self._body())):
            raise DecomposerError("plan_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_PLAN_BYTES:
            raise DecomposerError("plan exceeds byte bound")

    def _body(self):
        return {
            "architecture_baseline_sha256": self.architecture_baseline_sha256,
            "approved_to_execute": False,
            "base_sha": self.base_sha,
            "contract_sha256": self.contract_sha256,
            "decomposer_version": self.decomposer_version,
            "edges": [list(edge) for edge in self.edges],
            "escalation_reasons": list(self.escalation_reasons),
            "execution_authorized": False,
            "github_authorized": False,
            "impact_evidence_sha256": self.impact_evidence_sha256,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "nodes": [n.to_dict() for n in self.nodes],
            "plan_id": self.plan_id,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "requires_escalation": self.requires_escalation,
            "result_trusted": False,
            "root_node_id": self.root_node_id,
            "schema_version": self.schema_version,
            "task_contract_id": self.task_contract_id,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["plan_sha256"] = self.plan_sha256
        return body


def _seal_plan(**values):
    values = dict(values)
    for name in AUTHORITY_FLAGS:
        values[name] = False
    values["execution_authorized"] = False
    values["approved_to_execute"] = False
    provisional = object.__new__(ExecutionPlan)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ExecutionPlan(
        **values,
        plan_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def _complexity_for_scope(path_count, component_count, evidence):
    if evidence and evidence.tcb_adjacent_paths:
        return "large"
    if component_count >= 3 or path_count >= _LARGE_SCOPE_PATH_THRESHOLD:
        return "large"
    if component_count >= 2 or path_count >= 2:
        return "medium"
    if path_count == 1:
        return "small"
    return "unknown"


def _is_test_path(path):
    name = path.rsplit("/", 1)[-1]
    return (
        path.startswith("tests/")
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _group_paths_by_component(evidence, paths):
    """Return deterministic {component_id: (paths...)} including UNKNOWN."""
    groups = {}
    # evidence.owning_components is a set of owners; map path->owner via
    # re-deriving from queried_paths order + owning list is lossy. Instead
    # group by simple path heuristics when UNKNOWN dominates, else one group
    # per known component using path prefixes from SM-style component ids.
    owners = [
        c for c in evidence.owning_components if c not in (UNKNOWN,)
    ]
    if not owners:
        groups[UNKNOWN] = tuple(paths)
        return groups
    if len(owners) == 1 and UNKNOWN not in evidence.owning_components:
        groups[owners[0]] = tuple(paths)
        return groups
    # Multi-owner / mixed: split test vs non-test as a deterministic fallback
    # when we cannot map each path (collect_impact_evidence stores unique
    # owners only). Prefer path-local split over inventing edges.
    impl = tuple(p for p in paths if not _is_test_path(p))
    tests = tuple(p for p in paths if _is_test_path(p))
    if impl and tests and len(paths) >= 2:
        groups["impl"] = impl
        groups["tests"] = tests
        return groups
    # Fall back to one slice per path for multi-path multi-owner cases.
    if len(paths) >= _MULTI_COMPONENT_SLICE_THRESHOLD:
        for idx, path in enumerate(paths):
            groups[f"path_{idx:02d}"] = (path,)
        return groups
    groups["scope"] = tuple(paths)
    return groups


def decompose_task_contract(contract, model=None, *, impact_evidence=None):
    """Deterministically decompose a frozen task contract into an execution plan.

    ``model`` is required unless ``impact_evidence`` is pre-supplied (tests).
    Never calls an LLM/provider. Never authorizes execution.
    """
    if not isinstance(contract, FrozenTaskContract):
        raise DecomposerError("contract is invalid")
    if impact_evidence is None:
        if not isinstance(model, SystemModel):
            raise DecomposerError("model is required without impact_evidence")
        impact_evidence = collect_impact_evidence(model, contract.allowed_scope)
    elif not isinstance(impact_evidence, DecompositionImpactEvidence):
        raise DecomposerError("impact_evidence is invalid")

    paths = tuple(contract.allowed_scope)
    forbidden = tuple(contract.forbidden_scope)
    escalation = []
    nodes = []
    edges = []

    known_components = tuple(
        c
        for c in impact_evidence.owning_components
        if c not in (UNKNOWN,)
    )
    complexity = _complexity_for_scope(
        len(paths), len(known_components), impact_evidence
    )

    if impact_evidence.tcb_adjacent_paths:
        escalation.append("tcb_adjacent_scope")
    if any(u.startswith("ownership:") for u in impact_evidence.uncertainties):
        escalation.append("ambiguous_or_unknown_ownership")
    if contract.taxonomy_class_id in (
        "tcb_adjacent_change",
        "security_sensitive_change",
        "migration_schema_change",
        "verifier_policy_sensitive_task",
    ):
        escalation.append(f"taxonomy:{contract.taxonomy_class_id}")

    root_id = "n_goal_001"
    plan_id = f"plan_{contract.task_contract_id}"

    # Investigation-first when ownership/TCB uncertainty is present.
    investigation_ids = []
    if impact_evidence.tcb_adjacent_paths or any(
        u.startswith(("ownership:", "tcb_uncertain:"))
        for u in impact_evidence.uncertainties
    ):
        inv_id = "n_invest_001"
        investigation_ids.append(inv_id)
        nodes.append(
            create_decomposition_node(
                node_id=inv_id,
                parent_id=root_id,
                level="investigation",
                node_type="investigate",
                title="Investigate ownership/TCB adjacency",
                objective=(
                    "Resolve UNKNOWN ownership and TCB adjacency before "
                    "implementation slices"
                ),
                rationale=(
                    "Uncertainty must be investigated first; never invent deps"
                ),
                affected_components=tuple(
                    impact_evidence.owning_components[:16]
                ),
                candidate_allowed_scope=paths,
                inherited_forbidden_scope=forbidden,
                acceptance_checkpoint=(
                    "ownership and TCB adjacency uncertainties documented",
                ),
                complexity_estimate="small",
                uncertainty=(
                    impact_evidence.uncertainties[0]
                    if impact_evidence.uncertainties
                    else UNKNOWN
                ),
                requires_escalation=bool(impact_evidence.tcb_adjacent_paths),
                escalation_reasons=(
                    ("tcb_adjacent_requires_human_review",)
                    if impact_evidence.tcb_adjacent_paths
                    else ()
                ),
                children=(),
            )
        )

    groups = _group_paths_by_component(impact_evidence, paths)
    child_ids = []
    atomic_ids = []

    # Simple path: single small scope -> one atomic under goal.
    simple = (
        len(paths) == 1
        and complexity in ("trivial", "small")
        and not impact_evidence.tcb_adjacent_paths
        and contract.taxonomy_class_id
        in (
            "narrow_bug_fix",
            "test_addition",
            "docs_spec_sync",
        )
    )

    if simple:
        atomic_id = "n_atomic_001"
        atomic_ids.append(atomic_id)
        child_ids.append(atomic_id)
        depends = tuple(investigation_ids)
        nodes.append(
            create_decomposition_node(
                node_id=atomic_id,
                parent_id=root_id,
                level="atomic",
                node_type="implement",
                title="Implement bounded fix",
                objective=contract.goal,
                rationale="Single-scope task; avoid over-decomposition",
                depends_on=depends,
                affected_components=tuple(
                    impact_evidence.owning_components[:8]
                ),
                candidate_allowed_scope=paths,
                inherited_forbidden_scope=forbidden,
                acceptance_checkpoint=tuple(contract.acceptance_criteria),
                complexity_estimate=complexity,
                uncertainty=(
                    impact_evidence.uncertainties[0]
                    if impact_evidence.uncertainties
                    else UNKNOWN
                ),
                children=(),
            )
        )
        for dep in depends:
            edges.append((atomic_id, dep))
    else:
        # Multi-slice: one slice per group, each with implement (+ test if split)
        for g_idx, (group_key, group_paths) in enumerate(sorted(groups.items())):
            slice_id = f"n_slice_{g_idx:03d}"
            child_ids.append(slice_id)
            is_test_group = group_key == "tests" or all(
                _is_test_path(p) for p in group_paths
            )
            atomic_id = f"n_atomic_{g_idx:03d}"
            atomic_ids.append(atomic_id)
            node_type = "test" if is_test_group else "implement"
            if any("migration" in p or "schema" in p for p in group_paths):
                node_type = "migrate"
            slice_depends = tuple(investigation_ids)
            # Test slices depend on impl slices when both exist.
            if is_test_group:
                impl_atomics = [
                    f"n_atomic_{i:03d}"
                    for i, (k, _) in enumerate(sorted(groups.items()))
                    if k == "impl" or (
                        k != "tests"
                        and not all(_is_test_path(p) for p in groups[k])
                    )
                ]
                # Only depend on atomics that will exist with lower index.
                slice_depends = tuple(
                    sorted(set(slice_depends + tuple(impl_atomics)))
                )

            nodes.append(
                create_decomposition_node(
                    node_id=slice_id,
                    parent_id=root_id,
                    level="slice",
                    node_type="decompose",
                    title=f"Slice for {group_key}",
                    objective=f"Bounded work for component group {group_key}",
                    rationale=(
                        "Component/test boundary decomposition; acceptance "
                        "checkpoints preferred over file-count ceremony"
                    ),
                    depends_on=tuple(investigation_ids),
                    affected_components=(
                        (group_key,)
                        if group_key not in ("impl", "tests", "scope")
                        and not group_key.startswith("path_")
                        else tuple(impact_evidence.owning_components[:4])
                    ),
                    candidate_allowed_scope=tuple(group_paths),
                    inherited_forbidden_scope=forbidden,
                    acceptance_checkpoint=(),
                    complexity_estimate=_complexity_for_scope(
                        len(group_paths), 1, impact_evidence
                    ),
                    uncertainty=UNKNOWN,
                    children=(atomic_id,),
                )
            )
            nodes.append(
                create_decomposition_node(
                    node_id=atomic_id,
                    parent_id=slice_id,
                    level="atomic",
                    node_type=node_type,
                    title=f"{node_type} {group_key}",
                    objective=contract.acceptance_criteria[0],
                    rationale="Atomic unit under slice; inherits forbidden scope",
                    depends_on=slice_depends,
                    affected_components=tuple(
                        impact_evidence.owning_components[:4]
                    ),
                    candidate_allowed_scope=tuple(group_paths),
                    inherited_forbidden_scope=forbidden,
                    acceptance_checkpoint=tuple(contract.acceptance_criteria),
                    complexity_estimate=_complexity_for_scope(
                        len(group_paths), 1, impact_evidence
                    ),
                    uncertainty=UNKNOWN,
                    children=(),
                )
            )
            for dep in slice_depends:
                edges.append((atomic_id, dep))
            edges.append((atomic_id, slice_id))  # structural; also parent

    # Optional verify node when contract requires gates.
    if "unit_tests" in contract.required_gates or contract.required_gates:
        verify_id = "n_verify_001"
        child_ids.append(verify_id)
        verify_depends = tuple(sorted(set(atomic_ids + investigation_ids)))
        nodes.append(
            create_decomposition_node(
                node_id=verify_id,
                parent_id=root_id,
                level="atomic",
                node_type="verify",
                title="Acceptance verification checkpoint",
                objective="Confirm acceptance criteria under required gates",
                rationale="Prefer acceptance checkpoints over line-count stops",
                depends_on=verify_depends,
                affected_components=tuple(
                    impact_evidence.owning_components[:8]
                ),
                candidate_allowed_scope=paths,
                inherited_forbidden_scope=forbidden,
                acceptance_checkpoint=tuple(contract.acceptance_criteria),
                complexity_estimate="small",
                uncertainty=UNKNOWN,
                children=(),
            )
        )
        for dep in verify_depends:
            edges.append((verify_id, dep))

    all_children = tuple(sorted(set(child_ids + investigation_ids)))
    root = create_decomposition_node(
        node_id=root_id,
        parent_id=None,
        level="goal",
        node_type="decompose",
        title="Goal",
        objective=contract.goal,
        rationale=contract.intent_summary,
        depends_on=(),
        affected_components=tuple(impact_evidence.owning_components[:16]),
        candidate_allowed_scope=paths,
        inherited_forbidden_scope=forbidden,
        acceptance_checkpoint=tuple(contract.acceptance_criteria),
        complexity_estimate=complexity,
        uncertainty=(
            impact_evidence.uncertainties[0]
            if impact_evidence.uncertainties
            else UNKNOWN
        ),
        requires_escalation=bool(escalation),
        escalation_reasons=tuple(sorted(set(escalation))) if escalation else (),
        children=all_children,
    )
    nodes.insert(0, root)

    # Deterministic node order by node_id.
    nodes = tuple(sorted(nodes, key=lambda n: n.node_id))
    edges = tuple(sorted(set(edges)))

    scope_result = check_plan_nodes_against_contract(contract, nodes, edges=edges)
    if not scope_result.preserved:
        escalation.extend(v.code for v in scope_result.violations)

    escalation = tuple(sorted(set(escalation)))
    return _seal_plan(
        schema_version=PLAN_SCHEMA_VERSION,
        plan_id=plan_id,
        task_contract_id=contract.task_contract_id,
        contract_sha256=contract.contract_sha256,
        base_sha=contract.base_sha,
        architecture_baseline_sha256=contract.architecture_baseline_sha256,
        decomposer_version=DECOMPOSER_VERSION,
        nodes=nodes,
        edges=edges,
        root_node_id=root_id,
        requires_escalation=bool(escalation),
        escalation_reasons=escalation,
        impact_evidence_sha256=impact_evidence.evidence_sha256,
    )


def decomposer_is_planning_only():
    """TRUST REVIEW helper: True -- decomposer never executes or launches."""
    return True


def decomposer_uses_no_llm():
    """TRUST REVIEW helper: True -- strategy is purely rule-based."""
    return True
