"""Pure execution-inert composition proposals for V0.4D Slice 2."""

import hashlib
import json
import re
from dataclasses import dataclass, field


class CompositionProposalError(ValueError):
    """Raised when proposed mission metadata is malformed or unsafe."""


MISSION_KIND_BASELINE = "v04d_current_tools_baseline"
RISK_READ_ONLY = "read_only"
RISK_INTERNAL_WRITE = "internal_write"
LITERAL_USER_GOAL = "user_goal"
LITERAL_APPROVED_CONTRACT = "approved_mission_contract"
TRANSFORM_EXACT_COPY = "exact_copy"
TRANSFORM_SELECT_PROJECT = "select_project_most_open_tasks"
TRANSFORM_INTEGER_TO_TEXT = "integer_to_bounded_text"
TRANSFORM_FIXED_TITLE = "fixed_follow_up_title"
ALLOWED_TRANSFORMS = (
    TRANSFORM_EXACT_COPY,
    TRANSFORM_SELECT_PROJECT,
    TRANSFORM_INTEGER_TO_TEXT,
    TRANSFORM_FIXED_TITLE,
)
VALUE_TYPES = ("array", "boolean", "integer", "number", "object", "string")
MAX_IDENTITY_BYTES = 128
MAX_GOAL_BYTES = 2000
MAX_LITERAL_BYTES = 2048
MAX_STEPS = 8
MAX_BINDINGS_PER_STEP = 16
MAX_OUTPUTS_PER_STEP = 16
MAX_PROPOSAL_SUMMARY_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]*$")
_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE = re.compile(
    r"(?i)(?:token|password|secret|api[_-]?key|authorization)\s*[:=]"
)


def _text(value, name, limit=MAX_IDENTITY_BYTES, pattern=_IDENTIFIER):
    if not isinstance(value, str) or not value.strip():
        raise CompositionProposalError(f"{name} must be nonblank text")
    value = value.strip()
    if len(value.encode("utf-8")) > limit:
        raise CompositionProposalError(f"{name} exceeds {limit} bytes")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise CompositionProposalError(f"{name} contains controls")
    if _SENSITIVE.search(value):
        raise CompositionProposalError(f"{name} contains secret-like text")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise CompositionProposalError(f"{name} is malformed")
    return value


def _field_path(value):
    if isinstance(value, (str, bytes)):
        raise CompositionProposalError("field_path must be a sequence")
    try:
        path = tuple(value)
    except TypeError as error:
        raise CompositionProposalError(
            "field_path must be a sequence"
        ) from error
    if not path or len(path) > 8:
        raise CompositionProposalError(
            "field_path must contain 1 to 8 fields"
        )
    if any(
        not isinstance(part, str) or not _FIELD.fullmatch(part)
        for part in path
    ):
        raise CompositionProposalError("field_path contains a malformed field")
    return path


def _literal(value):
    if value is not None and type(value) not in (bool, int, float, str):
        raise CompositionProposalError("literal value must be a JSON scalar")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_LITERAL_BYTES:
        raise CompositionProposalError("literal value exceeds bound")
    if isinstance(value, str):
        _text(value, "literal value", MAX_LITERAL_BYTES, pattern=None)
    return value


@dataclass(frozen=True)
class LiteralBinding:
    """One bounded literal argument with explicit inert provenance."""

    argument_name: str
    source: str
    value: object

    def __post_init__(self):
        object.__setattr__(
            self,
            "argument_name",
            _text(self.argument_name, "argument_name", pattern=_FIELD),
        )
        if self.source not in (LITERAL_USER_GOAL, LITERAL_APPROVED_CONTRACT):
            raise CompositionProposalError("unsupported literal source")
        object.__setattr__(self, "value", _literal(self.value))

    def to_dict(self):
        return {
            "argument_name": self.argument_name,
            "kind": "literal",
            "source": self.source,
            "value": self.value,
        }


@dataclass(frozen=True)
class ResultBinding:
    """One predeclared result-to-argument binding with a fixed transform."""

    argument_name: str
    source_step_id: str
    field_path: tuple
    transform: str = TRANSFORM_EXACT_COPY

    def __post_init__(self):
        object.__setattr__(
            self,
            "argument_name",
            _text(self.argument_name, "argument_name", pattern=_FIELD),
        )
        object.__setattr__(
            self,
            "source_step_id",
            _text(self.source_step_id, "source_step_id"),
        )
        object.__setattr__(self, "field_path", _field_path(self.field_path))
        if self.transform not in ALLOWED_TRANSFORMS:
            raise CompositionProposalError("unsupported result transform")

    def to_dict(self):
        return {
            "argument_name": self.argument_name,
            "field_path": list(self.field_path),
            "kind": "result",
            "source_step_id": self.source_step_id,
            "transform": self.transform,
        }


@dataclass(frozen=True)
class DeclaredOutput:
    """An inert claim about a bounded field a later step may reference."""

    field_path: tuple
    value_type: str

    def __post_init__(self):
        object.__setattr__(self, "field_path", _field_path(self.field_path))
        if self.value_type not in VALUE_TYPES:
            raise CompositionProposalError("unsupported declared output type")

    def to_dict(self):
        return {
            "field_path": list(self.field_path),
            "value_type": self.value_type,
        }


@dataclass(frozen=True)
class CompositionStepProposal:
    """One descriptive proposed step; it carries no executable request."""

    step_id: str
    capability_id: str
    tool_name: str
    expected_risk: str
    bindings: tuple = ()
    prerequisite_step_ids: tuple = ()
    declared_outputs: tuple = ()

    def __post_init__(self):
        for name in ("step_id", "capability_id", "tool_name"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.expected_risk not in (RISK_READ_ONLY, RISK_INTERNAL_WRITE):
            raise CompositionProposalError("unsupported expected risk")
        bindings = tuple(self.bindings)
        if len(bindings) > MAX_BINDINGS_PER_STEP or any(
            not isinstance(item, (LiteralBinding, ResultBinding))
            for item in bindings
        ):
            raise CompositionProposalError(
                "invalid or excessive step bindings"
            )
        arguments = tuple(item.argument_name for item in bindings)
        if len(arguments) != len(set(arguments)):
            raise CompositionProposalError("argument bindings must be unique")
        prerequisites = tuple(self.prerequisite_step_ids)
        if any(
            not isinstance(item, str) or not _IDENTIFIER.fullmatch(item)
            for item in prerequisites
        ):
            raise CompositionProposalError("invalid prerequisite step id")
        if len(prerequisites) != len(set(prerequisites)):
            raise CompositionProposalError("prerequisites must be unique")
        outputs = tuple(self.declared_outputs)
        if len(outputs) > MAX_OUTPUTS_PER_STEP or any(
            not isinstance(item, DeclaredOutput) for item in outputs
        ):
            raise CompositionProposalError(
                "invalid or excessive declared outputs"
            )
        paths = tuple(item.field_path for item in outputs)
        if len(paths) != len(set(paths)):
            raise CompositionProposalError(
                "declared output paths must be unique"
            )
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(self, "prerequisite_step_ids", prerequisites)
        object.__setattr__(self, "declared_outputs", outputs)

    def to_dict(self):
        return {
            "bindings": [item.to_dict() for item in self.bindings],
            "capability_id": self.capability_id,
            "declared_outputs": [
                item.to_dict() for item in self.declared_outputs
            ],
            "expected_risk": self.expected_risk,
            "prerequisite_step_ids": list(self.prerequisite_step_ids),
            "step_id": self.step_id,
            "tool_name": self.tool_name,
        }


def _validate_graph(steps):
    identifiers = {step.step_id for step in steps}
    for step in steps:
        references = set(step.prerequisite_step_ids)
        references.update(
            binding.source_step_id
            for binding in step.bindings
            if isinstance(binding, ResultBinding)
        )
        if step.step_id in references or not references <= identifiers:
            raise CompositionProposalError("step contains invalid references")
    visiting = set()
    visited = set()
    edges = {step.step_id: set(step.prerequisite_step_ids) for step in steps}

    def visit(step_id):
        if step_id in visiting:
            raise CompositionProposalError("step graph contains a cycle")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in edges[step_id]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for identifier in identifiers:
        visit(identifier)


@dataclass(frozen=True)
class CompositionMissionProposal:
    """Immutable bounded mission proposal with no resolution or authority."""

    mission_id: str
    goal_summary: str
    goal_sha256: str
    steps: tuple
    max_processed_requests: int = 5
    max_identical_requests: int = 2
    max_consecutive_failures: int = 2
    mission_kind: str = field(default=MISSION_KIND_BASELINE, init=False)
    persisted: bool = field(default=False, init=False)
    tools_resolved: bool = field(default=False, init=False)
    execution_performed: bool = field(default=False, init=False)
    pending_operation_created: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self):
        object.__setattr__(
            self, "mission_id", _text(self.mission_id, "mission_id")
        )
        goal = _text(
            self.goal_summary,
            "goal_summary",
            MAX_GOAL_BYTES,
            pattern=None,
        )
        object.__setattr__(self, "goal_summary", goal)
        if (
            not isinstance(self.goal_sha256, str)
            or not _SHA256.fullmatch(self.goal_sha256)
        ):
            raise CompositionProposalError("goal_sha256 is malformed")
        digest = hashlib.sha256(goal.encode("utf-8")).hexdigest()
        if digest != self.goal_sha256:
            raise CompositionProposalError(
                "goal digest does not match summary"
            )
        steps = tuple(self.steps)
        if not 1 <= len(steps) <= MAX_STEPS or any(
            not isinstance(step, CompositionStepProposal) for step in steps
        ):
            raise CompositionProposalError(
                "mission has invalid step count or type"
            )
        identifiers = tuple(step.step_id for step in steps)
        if len(identifiers) != len(set(identifiers)):
            raise CompositionProposalError("step IDs must be unique")
        _validate_graph(steps)
        for step in steps:
            for binding in step.bindings:
                if (
                    isinstance(binding, ResultBinding)
                    and binding.source_step_id
                    not in step.prerequisite_step_ids
                ):
                    raise CompositionProposalError(
                        "result source must be an explicit prerequisite"
                    )
        if (
            self.max_processed_requests != 5
            or self.max_identical_requests != 2
            or self.max_consecutive_failures != 2
        ):
            raise CompositionProposalError(
                "mission budget differs from ADR-040"
            )
        object.__setattr__(self, "steps", steps)
        if len(self.summary().encode("utf-8")) > MAX_PROPOSAL_SUMMARY_BYTES:
            raise CompositionProposalError("proposal summary exceeds bound")

    def to_dict(self):
        return {
            "authority": {
                "execution_performed": self.execution_performed,
                "pending_operation_created": self.pending_operation_created,
                "persisted": self.persisted,
                "runtime_authority": self.runtime_authority,
                "tools_resolved": self.tools_resolved,
            },
            "budget": {
                "max_consecutive_failures": self.max_consecutive_failures,
                "max_identical_requests": self.max_identical_requests,
                "max_processed_requests": self.max_processed_requests,
            },
            "goal_sha256": self.goal_sha256,
            "goal_summary": self.goal_summary,
            "mission_id": self.mission_id,
            "mission_kind": self.mission_kind,
            "steps": [step.to_dict() for step in self.steps],
        }

    def summary(self):
        return json.dumps(
            self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False
        ) + "\n"


def propose_composition_mission(mission_id, goal_summary, steps):
    """Create one inert proposal; no registry lookup or execution occurs."""
    normalized_goal = _text(
        goal_summary, "goal_summary", MAX_GOAL_BYTES, pattern=None
    )
    return CompositionMissionProposal(
        mission_id=mission_id,
        goal_summary=normalized_goal,
        goal_sha256=hashlib.sha256(
            normalized_goal.encode("utf-8")
        ).hexdigest(),
        steps=tuple(steps),
    )
