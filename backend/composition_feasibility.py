"""Deterministic registry and policy binding for V0.4D Slice 3."""

import hashlib
import json
from dataclasses import dataclass, field, replace

from backend.composition_proposal import (
    RISK_INTERNAL_WRITE,
    RISK_READ_ONLY,
    TRANSFORM_EXACT_COPY,
    TRANSFORM_FIXED_TITLE,
    TRANSFORM_INTEGER_TO_TEXT,
    TRANSFORM_SELECT_PROJECT,
    CompositionMissionProposal,
    CompositionProposalError,
    LiteralBinding,
    ResultBinding,
)
from backend.tool_registry import ToolRegistry
from backend.tool_types import RISK_HIGH_RISK, ToolNotFoundError


class CompositionFeasibilityError(ValueError):
    """Raised when a feasibility result is malformed or forged."""


STATUS_FEASIBLE = "feasible"
STATUS_NOT_FEASIBLE = "not_feasible"
BASELINE_TOOL_ORDER = (
    "projects.overview",
    "tasks.status_summary",
    "tasks.list",
    "memory.search",
    "tasks.create",
)
MAX_BOUND_PLAN_SUMMARY_BYTES = 128 * 1024
_INVALID_PROPOSAL = "Composition proposal is not authoritative."


def _schema_digest(schema):
    canonical = json.dumps(
        schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BoundToolFact:
    """Immutable authority-relevant facts read from one registered tool."""

    name: str
    version: str
    risk: str
    input_schema_sha256: str
    capabilities: tuple
    dependencies: tuple

    def __post_init__(self):
        if not all(isinstance(value, str) and value for value in (
            self.name, self.version, self.risk, self.input_schema_sha256,
        )):
            raise CompositionFeasibilityError("invalid bound tool fact")
        if len(self.input_schema_sha256) != 64:
            raise CompositionFeasibilityError("invalid schema digest")
        capabilities = tuple(self.capabilities)
        dependencies = tuple(self.dependencies)
        if capabilities != tuple(sorted(set(capabilities))):
            raise CompositionFeasibilityError("capabilities are not canonical")
        if dependencies != tuple(sorted(set(dependencies))):
            raise CompositionFeasibilityError("dependencies are not canonical")
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "dependencies", dependencies)

    def to_dict(self):
        return {
            "capabilities": list(self.capabilities),
            "dependencies": list(self.dependencies),
            "input_schema_sha256": self.input_schema_sha256,
            "name": self.name,
            "risk": self.risk,
            "version": self.version,
        }


@dataclass(frozen=True)
class FeasibleCompositionStep:
    """One proposal step bound to exact immutable registry facts."""

    step_id: str
    tool: BoundToolFact
    prerequisite_step_ids: tuple
    bindings: tuple

    def __post_init__(self):
        prerequisites = tuple(self.prerequisite_step_ids)
        bindings = tuple(self.bindings)
        if any(
            not isinstance(item, (LiteralBinding, ResultBinding))
            for item in bindings
        ):
            raise CompositionFeasibilityError("invalid bound step bindings")
        object.__setattr__(self, "prerequisite_step_ids", prerequisites)
        object.__setattr__(self, "bindings", bindings)

    def to_dict(self):
        return {
            "bindings": [binding.to_dict() for binding in self.bindings],
            "prerequisite_step_ids": list(self.prerequisite_step_ids),
            "step_id": self.step_id,
            "tool": self.tool.to_dict(),
        }


def _proposal_authoritative(proposal):
    try:
        expected = replace(proposal)
    except (CompositionProposalError, TypeError, ValueError):
        return False
    return expected == proposal


def _tool_fact(definition):
    return BoundToolFact(
        name=definition.name,
        version=definition.version,
        risk=definition.risk,
        input_schema_sha256=_schema_digest(definition.input_schema),
        capabilities=tuple(sorted(set(definition.capabilities))),
        dependencies=tuple(sorted(set(definition.depends_on))),
    )


def _json_type(value):
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    if type(value) is str:
        return "string"
    return "unsupported"


def _compatible(source_type, destination_type):
    if source_type == destination_type:
        return True
    return source_type == "integer" and destination_type == "number"


def _binding_output_type(binding, source_type):
    if isinstance(binding, LiteralBinding):
        return _json_type(binding.value)
    if binding.transform == TRANSFORM_EXACT_COPY:
        return source_type
    if binding.transform == TRANSFORM_SELECT_PROJECT:
        return "string" if source_type == "array" else None
    if binding.transform in (TRANSFORM_INTEGER_TO_TEXT, TRANSFORM_FIXED_TITLE):
        return "string" if source_type == "integer" else None
    return None


def _declared_type(steps_by_id, binding):
    source = steps_by_id.get(binding.source_step_id)
    if source is None:
        return None
    matches = (
        item.value_type
        for item in source.declared_outputs
        if item.field_path == binding.field_path
    )
    return next(matches, None)


def _step_reason(step, definition, proposal, registry):
    if definition.name != step.tool_name:
        return f"Step {step.step_id} tool identity is inconsistent."
    if definition.risk == RISK_HIGH_RISK:
        return f"Step {step.step_id} uses a high-risk tool."
    if definition.risk != step.expected_risk:
        return f"Step {step.step_id} risk does not match the proposal."
    if step.capability_id not in definition.capabilities:
        return f"Step {step.step_id} capability is not registered on its tool."
    for dependency in definition.depends_on:
        try:
            registry.get(dependency)
        except ToolNotFoundError:
            return f"Step {step.step_id} has an unresolved tool dependency."

    schema = definition.input_schema
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
    ):
        return f"Step {step.step_id} input schema is not closed."
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        return f"Step {step.step_id} input schema is malformed."
    bindings = {binding.argument_name: binding for binding in step.bindings}
    if (
        not set(required) <= set(bindings)
        or not set(bindings) <= set(properties)
    ):
        return (
            f"Step {step.step_id} argument bindings do not match its schema."
        )

    steps_by_id = {item.step_id: item for item in proposal.steps}
    for name, binding in bindings.items():
        destination_type = properties[name].get("type")
        source_type = None
        if isinstance(binding, ResultBinding):
            source_type = _declared_type(steps_by_id, binding)
            if source_type is None:
                return f"Step {step.step_id} result field is unavailable."
        output_type = _binding_output_type(binding, source_type)
        if (
            output_type is None
            or not _compatible(output_type, destination_type)
        ):
            return f"Step {step.step_id} binding is type-incompatible."
    if any(
        isinstance(binding, ResultBinding)
        and binding.argument_name in {
            "tool_name", "capability_id", "risk", "schema", "executor",
            "budget", "approval",
        }
        for binding in step.bindings
    ):
        return f"Step {step.step_id} derives authority from tool output."
    return None


def _resolve(proposal, registry):
    if not _proposal_authoritative(proposal):
        return (), (_INVALID_PROPOSAL,)
    if tuple(step.tool_name for step in proposal.steps) != BASELINE_TOOL_ORDER:
        return (), ("Mission steps do not match the ADR-040 baseline.",)
    if len(proposal.steps) > proposal.max_processed_requests:
        return (), ("Mission exceeds its processed-request budget.",)
    if proposal.steps[-1].expected_risk != RISK_INTERNAL_WRITE or any(
        step.expected_risk != RISK_READ_ONLY for step in proposal.steps[:-1]
    ):
        return (), ("Mission write ordering violates ADR-040.",)

    facts = []
    bound_steps = []
    for step in proposal.steps:
        try:
            definition = registry.get(step.tool_name)
        except ToolNotFoundError:
            return (), (f"Step {step.step_id} tool is not registered.",)
        reason = _step_reason(step, definition, proposal, registry)
        if reason is not None:
            return (), (reason,)
        fact = _tool_fact(definition)
        facts.append(fact)
        bound_steps.append(FeasibleCompositionStep(
            step_id=step.step_id,
            tool=fact,
            prerequisite_step_ids=step.prerequisite_step_ids,
            bindings=step.bindings,
        ))
    if len({fact.name for fact in facts}) != len(facts):
        return (), ("Mission violates identical-request policy.",)
    return tuple(bound_steps), ()


def _snapshot_digest(bound_steps):
    facts = sorted(
        (step.tool.to_dict() for step in bound_steps),
        key=lambda item: item["name"],
    )
    canonical = json.dumps(
        facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FeasibleCompositionPlan:
    """Immutable registry-bound plan with no execution capability."""

    proposal: CompositionMissionProposal
    status: str
    bound_steps: tuple
    registry_snapshot_sha256: str
    blocking_reasons: tuple
    registry_bound: bool = field(init=False)
    runtime_revalidation_required: bool = field(default=True, init=False)
    in_memory_budget_only: bool = field(default=True, init=False)
    cross_process_budget_continuity: bool = field(default=False, init=False)
    pending_write_counts_as_processed: bool = field(default=True, init=False)
    tool_requests_created: bool = field(default=False, init=False)
    execution_performed: bool = field(default=False, init=False)
    pending_operation_created: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self):
        if not isinstance(self.proposal, CompositionMissionProposal):
            raise CompositionFeasibilityError("invalid composition proposal")
        steps = tuple(self.bound_steps)
        reasons = tuple(self.blocking_reasons)
        feasible = not reasons
        expected_status = STATUS_FEASIBLE if feasible else STATUS_NOT_FEASIBLE
        expected_digest = _snapshot_digest(steps) if feasible else ""
        if self.status != expected_status:
            raise CompositionFeasibilityError("plan status is forged")
        if feasible and len(steps) != len(self.proposal.steps):
            raise CompositionFeasibilityError("bound plan is incomplete")
        if not feasible and steps:
            raise CompositionFeasibilityError(
                "failed plan contains bound steps"
            )
        if self.registry_snapshot_sha256 != expected_digest:
            raise CompositionFeasibilityError("registry snapshot is forged")
        for proposed, bound in zip(self.proposal.steps, steps):
            if (
                proposed.step_id != bound.step_id
                or proposed.tool_name != bound.tool.name
                or proposed.bindings != bound.bindings
                or proposed.prerequisite_step_ids
                != bound.prerequisite_step_ids
            ):
                raise CompositionFeasibilityError("bound step is forged")
        object.__setattr__(self, "bound_steps", steps)
        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "registry_bound", feasible)
        if len(self.summary().encode("utf-8")) > MAX_BOUND_PLAN_SUMMARY_BYTES:
            raise CompositionFeasibilityError("bound plan exceeds size limit")

    def to_dict(self):
        return {
            "authority": {
                "cross_process_budget_continuity": (
                    self.cross_process_budget_continuity
                ),
                "execution_performed": self.execution_performed,
                "in_memory_budget_only": self.in_memory_budget_only,
                "pending_operation_created": self.pending_operation_created,
                "pending_write_counts_as_processed": (
                    self.pending_write_counts_as_processed
                ),
                "runtime_authority": self.runtime_authority,
                "runtime_revalidation_required": (
                    self.runtime_revalidation_required
                ),
                "tool_requests_created": self.tool_requests_created,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "bound_steps": [step.to_dict() for step in self.bound_steps],
            "budget": {
                "max_consecutive_failures": (
                    self.proposal.max_consecutive_failures
                ),
                "max_identical_requests": self.proposal.max_identical_requests,
                "max_processed_requests": self.proposal.max_processed_requests,
            },
            "mission_id": self.proposal.mission_id,
            "registry_bound": self.registry_bound,
            "registry_snapshot_sha256": self.registry_snapshot_sha256,
            "status": self.status,
        }

    def summary(self):
        return json.dumps(
            self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False
        ) + "\n"


def bind_composition_feasibility(proposal, registry):
    """Bind an inert proposal to supplied registry facts without execution."""
    if not isinstance(proposal, CompositionMissionProposal):
        raise CompositionFeasibilityError("invalid composition proposal")
    if not isinstance(registry, ToolRegistry):
        raise CompositionFeasibilityError("registry must be a ToolRegistry")
    steps, reasons = _resolve(proposal, registry)
    return FeasibleCompositionPlan(
        proposal=proposal,
        status=STATUS_FEASIBLE if not reasons else STATUS_NOT_FEASIBLE,
        bound_steps=steps,
        registry_snapshot_sha256=(
            _snapshot_digest(steps) if not reasons else ""
        ),
        blocking_reasons=reasons,
    )
