"""GP-B3 -- Scope Preservation Rules.

Deterministic checks that a child decomposition node (or revised plan)
never exceeds its parent / frozen task-contract envelope.

Detected widenings (always escalate; never silently accept):
- new path outside contract/parent allowed scope
- forbidden-path inclusion in candidate scope
- relaxed acceptance (dropped or weaker checkpoint vs parent/contract)
- increased budget ceiling vs contract
- increased descriptive risk ceiling vs contract
- removed required gate
- changed base_sha / contract identity / intent
- changed architecture baseline binding
- out-of-scope dependency reference

A violation yields an explicit escalation record. Planning success is never
execution permission. Read-only. No network. No model call. Zero authority.
"""

from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    canonical_json,
    require_no_authority,
    require_sha256,
    sha256_hex,
)
from .gpb_decomposition_node import DecompositionNode
from .gpb_task_contract import FrozenTaskContract

SCOPE_RULES_VERSION = "gpb-scope-rules-v1"
MAX_VIOLATIONS = 64
MAX_REASON_BYTES = 512
MAX_RESULT_BYTES = 32 * 1024

VIOLATION_CODES = frozenset(
    {
        "new_path_outside_envelope",
        "forbidden_path_inclusion",
        "relaxed_acceptance",
        "increased_budget",
        "increased_risk_ceiling",
        "removed_gate",
        "changed_base_sha",
        "changed_contract_identity",
        "changed_intent",
        "changed_architecture_baseline",
        "out_of_scope_dependency",
        "parent_envelope_exceeded",
        "duplicate_node_id",
        "cycle_detected",
        "unsupported_schema",
    }
)

_TOKEN = object()


class ScopeRulesError(GPAEvalSchemaError):
    """Raised when scope-preservation evidence cannot be produced safely."""


@dataclass(frozen=True)
class ScopeViolation:
    """One explicit scope/contract envelope violation."""

    code: str
    subject: str
    detail: str

    def to_dict(self):
        return {
            "code": self.code,
            "detail": self.detail,
            "subject": self.subject,
        }


@dataclass(frozen=True)
class ScopePreservationResult:
    """Sealed outcome of envelope checks. Never authorizes execution."""

    schema_version: str
    contract_id: str
    contract_sha256: str
    preserved: bool
    requires_escalation: bool
    violations: tuple
    checked_node_ids: tuple
    result_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    scope_expansion_authorized: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise ScopeRulesError(
                "scope preservation result requires trusted construction"
            )
        if self.schema_version != SCOPE_RULES_VERSION:
            raise ScopeRulesError("schema_version is unsupported")
        if type(self.violations) is not tuple:
            raise ScopeRulesError("violations is malformed")
        if len(self.violations) > MAX_VIOLATIONS:
            raise ScopeRulesError("violations exceeds bound")
        if any(not isinstance(v, ScopeViolation) for v in self.violations):
            raise ScopeRulesError("violations contains an invalid entry")
        if self.preserved and self.violations:
            raise ScopeRulesError("preserved cannot coexist with violations")
        if not self.preserved and not self.violations:
            raise ScopeRulesError("non-preserved result needs violations")
        if self.requires_escalation != (not self.preserved):
            raise ScopeRulesError("requires_escalation inconsistent")
        require_no_authority(self)
        if self.execution_authorized is not False:
            raise ScopeRulesError("cannot claim execution_authorized")
        if self.scope_expansion_authorized is not False:
            raise ScopeRulesError("cannot claim scope_expansion_authorized")
        require_sha256(self.result_sha256, "result_sha256")
        if self.result_sha256 != sha256_hex(canonical_json(self._body())):
            raise ScopeRulesError("result_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_RESULT_BYTES:
            raise ScopeRulesError("result exceeds byte bound")

    def _body(self):
        return {
            "checked_node_ids": list(self.checked_node_ids),
            "contract_id": self.contract_id,
            "contract_sha256": self.contract_sha256,
            "execution_authorized": False,
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "preserved": self.preserved,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "requires_escalation": self.requires_escalation,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "scope_expansion_authorized": False,
            "violations": [v.to_dict() for v in self.violations],
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["result_sha256"] = self.result_sha256
        return body


def _seal_result(*, contract, preserved, violations, checked_node_ids):
    violations = tuple(violations)
    values = {
        "schema_version": SCOPE_RULES_VERSION,
        "contract_id": contract.task_contract_id,
        "contract_sha256": contract.contract_sha256,
        "preserved": preserved,
        "requires_escalation": not preserved,
        "violations": violations,
        "checked_node_ids": tuple(sorted(set(checked_node_ids))),
        "execution_authorized": False,
        "scope_expansion_authorized": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(ScopePreservationResult)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ScopePreservationResult(
        **values,
        result_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def _violation(code, subject, detail):
    if code not in VIOLATION_CODES:
        raise ScopeRulesError("violation code unsupported")
    if len(detail.encode("utf-8")) > MAX_REASON_BYTES:
        detail = detail.encode("utf-8")[:MAX_REASON_BYTES].decode(
            "utf-8", errors="ignore"
        )
    return ScopeViolation(code=code, subject=subject, detail=detail)


def _path_within_envelope(path, allowed_paths):
    """True if path equals an allowed path or is under an allowed directory prefix.

    Contract scopes are exact repo-relative file paths (GP-A idiom). A child
    may only use a subset of those exact paths -- never invent new ones.
    """
    return path in allowed_paths


def check_node_against_contract(contract, node, *, parent_node=None):
    """Check one node against the frozen contract (and optional parent)."""
    if not isinstance(contract, FrozenTaskContract):
        raise ScopeRulesError("contract is invalid")
    if not isinstance(node, DecompositionNode):
        raise ScopeRulesError("node is invalid")
    if parent_node is not None and not isinstance(parent_node, DecompositionNode):
        raise ScopeRulesError("parent_node is invalid")

    violations = []
    contract_allowed = set(contract.allowed_scope)
    contract_forbidden = set(contract.forbidden_scope)

    for path in node.candidate_allowed_scope:
        if path in contract_forbidden:
            violations.append(
                _violation(
                    "forbidden_path_inclusion",
                    node.node_id,
                    f"candidate scope includes forbidden path {path}",
                )
            )
        elif not _path_within_envelope(path, contract_allowed):
            violations.append(
                _violation(
                    "new_path_outside_envelope",
                    node.node_id,
                    f"candidate scope path outside contract: {path}",
                )
            )

    # Inherited forbidden must be a superset of contract forbidden (never drop).
    if not contract_forbidden.issubset(set(node.inherited_forbidden_scope)):
        violations.append(
            _violation(
                "forbidden_path_inclusion",
                node.node_id,
                "inherited_forbidden_scope dropped a contract forbidden path",
            )
        )

    # Acceptance: child checkpoint must not drop contract criteria silently.
    # Empty checkpoint on a non-atomic intermediate node is allowed; atomic /
    # implement / verify nodes should retain at least one contract criterion
    # or an explicit subset.
    if node.level in ("atomic",) or node.node_type in ("implement", "verify"):
        if node.acceptance_checkpoint:
            contract_acc = set(contract.acceptance_criteria)
            child_acc = set(node.acceptance_checkpoint)
            # Allow subset or equal; reject if child invents relaxed/empty vs
            # claiming coverage while dropping all contract criteria.
            if child_acc and not child_acc.intersection(contract_acc):
                # Completely disjoint acceptance text is treated as relaxed
                # unless it is clearly a refinement containing contract text.
                # Heuristic: if no contract criterion is preserved, escalate.
                violations.append(
                    _violation(
                        "relaxed_acceptance",
                        node.node_id,
                        "acceptance checkpoint shares no contract criteria",
                    )
                )

    if parent_node is not None:
        parent_allowed = set(parent_node.candidate_allowed_scope)
        if parent_allowed:
            for path in node.candidate_allowed_scope:
                if path not in parent_allowed and path not in contract_forbidden:
                    if path in contract_allowed:
                        # Still within contract but outside parent envelope.
                        violations.append(
                            _violation(
                                "parent_envelope_exceeded",
                                node.node_id,
                                f"path {path} exceeds parent node envelope",
                            )
                        )

    return _seal_result(
        contract=contract,
        preserved=not violations,
        violations=violations,
        checked_node_ids=(node.node_id,),
    )


def check_plan_nodes_against_contract(contract, nodes, *, edges=()):
    """Check a full node set for envelope preservation, cycles, duplicates."""
    if not isinstance(contract, FrozenTaskContract):
        raise ScopeRulesError("contract is invalid")
    if type(nodes) not in (list, tuple):
        raise ScopeRulesError("nodes is malformed")

    violations = []
    checked = []
    by_id = {}
    for node in nodes:
        if not isinstance(node, DecompositionNode):
            raise ScopeRulesError("nodes contains an invalid entry")
        checked.append(node.node_id)
        if node.node_id in by_id:
            violations.append(
                _violation(
                    "duplicate_node_id",
                    node.node_id,
                    "duplicate node_id in plan",
                )
            )
            continue
        by_id[node.node_id] = node

    # Parent map + cycle detection via DFS.
    adjacency = {nid: set() for nid in by_id}
    for node in by_id.values():
        for dep in node.depends_on:
            if dep not in by_id:
                violations.append(
                    _violation(
                        "out_of_scope_dependency",
                        node.node_id,
                        f"depends_on unknown node {dep}",
                    )
                )
            else:
                adjacency[node.node_id].add(dep)
        if node.parent_id is not None and node.parent_id not in by_id:
            violations.append(
                _violation(
                    "out_of_scope_dependency",
                    node.node_id,
                    f"parent_id unknown node {node.parent_id}",
                )
            )

    if type(edges) not in (list, tuple):
        raise ScopeRulesError("edges is malformed")
    for edge in edges:
        if type(edge) not in (list, tuple) or len(edge) != 2:
            raise ScopeRulesError("edges entry malformed")
        src, dst = edge
        if src not in by_id or dst not in by_id:
            violations.append(
                _violation(
                    "out_of_scope_dependency",
                    str(src),
                    f"edge references unknown node ({src}->{dst})",
                )
            )
        else:
            adjacency[src].add(dst)

    visiting = set()
    visited = set()

    def _dfs(nid):
        if nid in visiting:
            violations.append(
                _violation("cycle_detected", nid, "dependency cycle detected")
            )
            return
        if nid in visited:
            return
        visiting.add(nid)
        for dep in adjacency.get(nid, ()):
            _dfs(dep)
        visiting.remove(nid)
        visited.add(nid)

    for nid in sorted(by_id):
        _dfs(nid)

    # Per-node envelope checks.
    for node in by_id.values():
        parent = by_id.get(node.parent_id) if node.parent_id else None
        result = check_node_against_contract(contract, node, parent_node=parent)
        violations.extend(result.violations)

    # Deduplicate violation dicts while preserving deterministic order.
    seen = set()
    unique = []
    for item in violations:
        key = (item.code, item.subject, item.detail)
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return _seal_result(
        contract=contract,
        preserved=not unique,
        violations=unique,
        checked_node_ids=checked,
    )


def check_contract_identity_preserved(original, candidate):
    """Detect silent contract identity / intent / baseline / gate drift."""
    if not isinstance(original, FrozenTaskContract):
        raise ScopeRulesError("original contract is invalid")
    if not isinstance(candidate, FrozenTaskContract):
        raise ScopeRulesError("candidate contract is invalid")

    violations = []
    if candidate.task_contract_id != original.task_contract_id:
        violations.append(
            _violation(
                "changed_contract_identity",
                candidate.task_contract_id,
                "task_contract_id changed",
            )
        )
    if candidate.contract_sha256 != original.contract_sha256:
        # Dig deeper for specific codes.
        if candidate.base_sha != original.base_sha:
            violations.append(
                _violation(
                    "changed_base_sha",
                    candidate.task_contract_id,
                    "base_sha changed",
                )
            )
        if (
            candidate.architecture_baseline_sha256
            != original.architecture_baseline_sha256
        ):
            violations.append(
                _violation(
                    "changed_architecture_baseline",
                    candidate.task_contract_id,
                    "architecture_baseline_sha256 changed",
                )
            )
        if (
            candidate.goal != original.goal
            or candidate.intent_summary != original.intent_summary
        ):
            violations.append(
                _violation(
                    "changed_intent",
                    candidate.task_contract_id,
                    "goal or intent_summary changed",
                )
            )
        if set(candidate.required_gates) < set(original.required_gates):
            violations.append(
                _violation(
                    "removed_gate",
                    candidate.task_contract_id,
                    "required_gates removed items",
                )
            )
        if set(candidate.acceptance_criteria) < set(
            original.acceptance_criteria
        ):
            violations.append(
                _violation(
                    "relaxed_acceptance",
                    candidate.task_contract_id,
                    "acceptance_criteria dropped items",
                )
            )
        for field_name in (
            "budget_ceiling_wall_clock_seconds",
            "budget_ceiling_input_tokens",
            "budget_ceiling_output_tokens",
            "budget_ceiling_cost_usd_cents",
        ):
            old = getattr(original, field_name)
            new = getattr(candidate, field_name)
            if old is not None and (new is None or new > old):
                violations.append(
                    _violation(
                        "increased_budget",
                        candidate.task_contract_id,
                        f"{field_name} increased or uncapped",
                    )
                )
        # Descriptive risk ceiling: adding risk indicators beyond original
        # (except when original is exactly {"none"}) is an increase.
        old_risk = set(original.risk_ceiling_indicators)
        new_risk = set(candidate.risk_ceiling_indicators)
        if new_risk - old_risk and new_risk != {"none"}:
            if not new_risk.issubset(old_risk):
                violations.append(
                    _violation(
                        "increased_risk_ceiling",
                        candidate.task_contract_id,
                        "risk_ceiling_indicators widened",
                    )
                )
        if set(candidate.allowed_scope) - set(original.allowed_scope):
            violations.append(
                _violation(
                    "new_path_outside_envelope",
                    candidate.task_contract_id,
                    "allowed_scope widened",
                )
            )
        if set(original.forbidden_scope) - set(candidate.forbidden_scope):
            violations.append(
                _violation(
                    "forbidden_path_inclusion",
                    candidate.task_contract_id,
                    "forbidden_scope narrowed",
                )
            )
        if not violations:
            violations.append(
                _violation(
                    "changed_contract_identity",
                    candidate.task_contract_id,
                    "contract digest changed",
                )
            )

    return _seal_result(
        contract=original,
        preserved=not violations,
        violations=violations,
        checked_node_ids=(),
    )


def scope_rules_are_planning_only():
    """TRUST REVIEW helper: True -- rules never authorize scope expansion."""
    return True
