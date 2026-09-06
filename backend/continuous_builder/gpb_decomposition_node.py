"""GP-B2 -- Decomposition Node Contract.

One sealed node in a hierarchical decomposition tree. Depth is variable:
goal -> ... -> atomic, or goal -> slice -> atomic. No forced ceremony depth
(no max-3-files / always-5-slices rules).

A node proposes work under a parent / frozen contract envelope. It never
grants execution authority, never widens scope silently, and never mutates
the frozen task contract. Candidate allowed scope is advisory relative to
the contract envelope and is validated by GP-B3 scope-preservation rules.

Read-only planning artifact. No network. No model call. Zero authority.
"""

from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    UNKNOWN,
    canonical_json,
    is_unknown,
    require_id,
    require_no_authority,
    require_sha256,
    require_sorted_unique_paths,
    require_text,
    sha256_hex,
)

NODE_SCHEMA_VERSION = "gpb-decomposition-node-v1"
GENERATOR_VERSION = "gpb-decomposition-node-generator-v1"

NODE_LEVELS = frozenset(
    {
        "goal",
        "program",
        "milestone",
        "phase",
        "feature",
        "slice",
        "atomic",
        "investigation",
    }
)
NODE_TYPES = frozenset(
    {
        "decompose",
        "implement",
        "verify",
        "investigate",
        "migrate",
        "document",
        "test",
        "refactor",
    }
)
COMPLEXITY_ESTIMATES = frozenset(
    {"trivial", "small", "medium", "large", "unknown"}
)

MAX_TITLE_BYTES = 256
MAX_OBJECTIVE_BYTES = 2048
MAX_RATIONALE_BYTES = 2048
MAX_TEXT_ITEM_BYTES = 512
MAX_DEPS = 32
MAX_COMPONENTS = 64
MAX_SCOPE_PATHS = 64
MAX_ACCEPTANCE = 16
MAX_CHILDREN = 64
MAX_UNCERTAINTY_BYTES = 1024
MAX_NODE_BYTES = 32 * 1024

_TOKEN = object()


class DecompositionNodeError(GPAEvalSchemaError):
    """Raised when a decomposition node cannot be sealed safely."""


def _require_text_tuple(values, label, maximum, *, allow_empty=True):
    if type(values) is not tuple:
        raise DecompositionNodeError(f"{label} is malformed")
    if not allow_empty and not values:
        raise DecompositionNodeError(f"{label} must be non-empty")
    if len(values) > maximum:
        raise DecompositionNodeError(f"{label} exceeds bound")
    return tuple(require_text(v, label, MAX_TEXT_ITEM_BYTES) for v in values)


def _require_sorted_unique_ids(values, label, maximum):
    if type(values) is not tuple:
        raise DecompositionNodeError(f"{label} is malformed")
    if len(values) > maximum:
        raise DecompositionNodeError(f"{label} exceeds bound")
    for value in values:
        require_id(value, label)
    if values != tuple(sorted(set(values))):
        raise DecompositionNodeError(f"{label} is not canonical")
    return values


@dataclass(frozen=True)
class DecompositionNode:
    """One sealed decomposition node. Grants no execution authority."""

    schema_version: str
    node_id: str
    parent_id: object  # str or None for root
    level: str
    node_type: str
    title: str
    objective: str
    rationale: str
    depends_on: tuple
    affected_components: tuple
    candidate_allowed_scope: tuple
    inherited_forbidden_scope: tuple
    acceptance_checkpoint: tuple
    complexity_estimate: str
    uncertainty: object  # str or UNKNOWN
    requires_escalation: bool
    escalation_reasons: tuple
    children: tuple
    generator_version: str
    node_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise DecompositionNodeError(
                "decomposition node requires trusted construction"
            )
        if self.schema_version != NODE_SCHEMA_VERSION:
            raise DecompositionNodeError("schema_version is unsupported")
        if self.generator_version != GENERATOR_VERSION:
            raise DecompositionNodeError("generator_version is unsupported")
        require_id(self.node_id, "node_id")
        if self.parent_id is not None:
            require_id(self.parent_id, "parent_id")
            if self.parent_id == self.node_id:
                raise DecompositionNodeError("node cannot parent itself")
        if self.level not in NODE_LEVELS:
            raise DecompositionNodeError("level is unsupported")
        if self.node_type not in NODE_TYPES:
            raise DecompositionNodeError("node_type is unsupported")
        require_text(self.title, "title", MAX_TITLE_BYTES)
        require_text(self.objective, "objective", MAX_OBJECTIVE_BYTES)
        require_text(self.rationale, "rationale", MAX_RATIONALE_BYTES)
        _require_sorted_unique_ids(self.depends_on, "depends_on", MAX_DEPS)
        if self.node_id in self.depends_on:
            raise DecompositionNodeError("node cannot depend on itself")
        affected = self.affected_components
        if type(affected) is not tuple or len(affected) > MAX_COMPONENTS:
            raise DecompositionNodeError("affected_components is malformed")
        for item in affected:
            if is_unknown(item):
                continue
            require_text(item, "affected_components", MAX_TEXT_ITEM_BYTES)
        if affected != tuple(sorted(set(affected))):
            raise DecompositionNodeError("affected_components is not canonical")
        require_sorted_unique_paths(
            self.candidate_allowed_scope,
            "candidate_allowed_scope",
            MAX_SCOPE_PATHS,
        )
        require_sorted_unique_paths(
            self.inherited_forbidden_scope,
            "inherited_forbidden_scope",
            MAX_SCOPE_PATHS,
        )
        if set(self.candidate_allowed_scope) & set(self.inherited_forbidden_scope):
            raise DecompositionNodeError(
                "candidate_allowed_scope intersects inherited_forbidden_scope"
            )
        _require_text_tuple(
            self.acceptance_checkpoint,
            "acceptance_checkpoint",
            MAX_ACCEPTANCE,
            allow_empty=True,
        )
        if self.complexity_estimate not in COMPLEXITY_ESTIMATES:
            raise DecompositionNodeError("complexity_estimate is unsupported")
        if not is_unknown(self.uncertainty):
            require_text(self.uncertainty, "uncertainty", MAX_UNCERTAINTY_BYTES)
        if type(self.requires_escalation) is not bool:
            raise DecompositionNodeError("requires_escalation must be bool")
        _require_text_tuple(
            self.escalation_reasons,
            "escalation_reasons",
            MAX_ACCEPTANCE,
            allow_empty=True,
        )
        if self.requires_escalation and not self.escalation_reasons:
            raise DecompositionNodeError(
                "requires_escalation needs escalation_reasons"
            )
        if not self.requires_escalation and self.escalation_reasons:
            raise DecompositionNodeError(
                "escalation_reasons require requires_escalation=True"
            )
        children = self.children
        if type(children) is not tuple or len(children) > MAX_CHILDREN:
            raise DecompositionNodeError("children is malformed")
        for child_id in children:
            require_id(child_id, "children")
        if children != tuple(sorted(set(children))):
            raise DecompositionNodeError("children is not canonical")
        if self.node_id in children:
            raise DecompositionNodeError("node cannot be its own child")
        require_no_authority(self)
        if self.execution_authorized is not False:
            raise DecompositionNodeError(
                "decomposition node cannot claim execution_authorized"
            )
        require_sha256(self.node_sha256, "node_sha256")
        if self.node_sha256 != sha256_hex(canonical_json(self._body())):
            raise DecompositionNodeError("node_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_NODE_BYTES:
            raise DecompositionNodeError("node exceeds byte bound")

    def _body(self):
        return {
            "acceptance_checkpoint": list(self.acceptance_checkpoint),
            "affected_components": list(self.affected_components),
            "candidate_allowed_scope": list(self.candidate_allowed_scope),
            "children": list(self.children),
            "complexity_estimate": self.complexity_estimate,
            "depends_on": list(self.depends_on),
            "escalation_reasons": list(self.escalation_reasons),
            "execution_authorized": False,
            "generator_version": self.generator_version,
            "github_authorized": False,
            "inherited_forbidden_scope": list(self.inherited_forbidden_scope),
            "level": self.level,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "objective": self.objective,
            "parent_id": self.parent_id,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "rationale": self.rationale,
            "requires_escalation": self.requires_escalation,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "title": self.title,
            "uncertainty": self.uncertainty,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["node_sha256"] = self.node_sha256
        return body


def create_decomposition_node(
    *,
    node_id,
    parent_id,
    level,
    node_type,
    title,
    objective,
    rationale,
    depends_on=(),
    affected_components=(),
    candidate_allowed_scope=(),
    inherited_forbidden_scope=(),
    acceptance_checkpoint=(),
    complexity_estimate="unknown",
    uncertainty=UNKNOWN,
    requires_escalation=False,
    escalation_reasons=(),
    children=(),
):
    """Seal one decomposition node. Never grants execution authority."""
    values = {
        "schema_version": NODE_SCHEMA_VERSION,
        "node_id": node_id,
        "parent_id": parent_id,
        "level": level,
        "node_type": node_type,
        "title": title,
        "objective": objective,
        "rationale": rationale,
        "depends_on": tuple(sorted(set(depends_on))),
        "affected_components": tuple(sorted(set(affected_components))),
        "candidate_allowed_scope": tuple(sorted(set(candidate_allowed_scope))),
        "inherited_forbidden_scope": tuple(
            sorted(set(inherited_forbidden_scope))
        ),
        "acceptance_checkpoint": tuple(acceptance_checkpoint),
        "complexity_estimate": complexity_estimate,
        "uncertainty": uncertainty,
        "requires_escalation": requires_escalation,
        "escalation_reasons": tuple(escalation_reasons),
        "children": tuple(sorted(set(children))),
        "generator_version": GENERATOR_VERSION,
        "execution_authorized": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(DecompositionNode)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return DecompositionNode(
        **values,
        node_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def decomposition_node_is_planning_only():
    """TRUST REVIEW helper: True -- node grants no execution authority."""
    return True
