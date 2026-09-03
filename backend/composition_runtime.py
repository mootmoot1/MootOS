"""Controlled V0.4D composition runtime over the existing Tool System."""

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field, replace

from backend.composition_feasibility import (
    STATUS_FEASIBLE,
    FeasibleCompositionPlan,
    bind_composition_feasibility,
)
from backend.composition_proposal import (
    TRANSFORM_EXACT_COPY,
    TRANSFORM_FIXED_TITLE,
    TRANSFORM_INTEGER_TO_TEXT,
    TRANSFORM_SELECT_PROJECT,
    LiteralBinding,
    ResultBinding,
)
from backend.tool_budget import (
    OUTCOME_ERROR,
    OUTCOME_PENDING_OPERATION,
    OUTCOME_SKIPPED,
    OUTCOME_SUCCESS,
    ToolCallBudget,
)
from backend.tool_executor import execute_tool
from backend.tool_operations import create_pending_operation
from backend.tool_registry import ToolRegistry
from backend.tool_types import (
    RISK_INTERNAL_WRITE,
    RISK_READ_ONLY,
    ToolExecutionContext,
)
from backend.tool_validation import validate_arguments


class CompositionRuntimeError(ValueError):
    """Raised when runtime inputs or result metadata are malformed."""


STATUS_APPROVAL_PENDING = "approval_pending"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"
STEP_SUCCEEDED = "succeeded"
STEP_PENDING = "pending"
STEP_BLOCKED = "blocked"
STEP_FAILED = "failed"
STEP_NOT_ATTEMPTED = "not_attempted"
MAX_TOOL_RESULT_BYTES = 256 * 1024
MAX_RUNTIME_SUMMARY_BYTES = 128 * 1024
MAX_SAFE_TEXT_BYTES = 500
_STEP_STATUSES = {
    STEP_SUCCEEDED,
    STEP_PENDING,
    STEP_BLOCKED,
    STEP_FAILED,
    STEP_NOT_ATTEMPTED,
}


def _digest(value):
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bounded_text(value, name, limit=MAX_SAFE_TEXT_BYTES):
    if not isinstance(value, str) or not value.strip():
        raise CompositionRuntimeError(f"{name} is not bounded text")
    text = value.strip()
    if len(text.encode("utf-8")) > limit:
        raise CompositionRuntimeError(f"{name} exceeds its byte limit")
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise CompositionRuntimeError(f"{name} contains controls")
    return text


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
    if type(value) is list:
        return "array"
    if type(value) is dict:
        return "object"
    return "unsupported"


def _extract(data, field_path):
    current = data
    for field_name in field_path:
        if not isinstance(current, dict) or field_name not in current:
            raise CompositionRuntimeError("declared result field is missing")
        current = current[field_name]
    return current


def _validate_result(step, data):
    try:
        encoded = json.dumps(
            data, sort_keys=True, ensure_ascii=False, default=str
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CompositionRuntimeError(
            "tool result is not serializable"
        ) from error
    if len(encoded) > MAX_TOOL_RESULT_BYTES:
        raise CompositionRuntimeError("tool result exceeds its byte limit")
    for output in step.declared_outputs:
        value = _extract(data, output.field_path)
        if _json_type(value) != output.value_type:
            raise CompositionRuntimeError(
                "declared result field has the wrong type"
            )


def _normalized_project_name(value):
    return unicodedata.normalize("NFC", value).strip().casefold()


def _select_project(projects):
    if not isinstance(projects, list) or not projects:
        raise CompositionRuntimeError("project overview is empty or malformed")
    candidates = []
    for project in projects:
        if not isinstance(project, dict):
            raise CompositionRuntimeError(
                "project overview entry is malformed"
            )
        name = _bounded_text(project.get("name"), "project name", 100)
        open_tasks = project.get("open_tasks")
        if type(open_tasks) is not int or open_tasks < 0:
            raise CompositionRuntimeError(
                "project open-task count is malformed"
            )
        candidates.append((open_tasks, _normalized_project_name(name), name))
    greatest = max(item[0] for item in candidates)
    eligible = (item for item in candidates if item[0] == greatest)
    return min(eligible, key=lambda item: (item[1], item[2]))[2]


def _transform(binding, value, selected_project):
    if binding.transform == TRANSFORM_EXACT_COPY:
        return value
    if binding.transform == TRANSFORM_SELECT_PROJECT:
        return _select_project(value)
    if binding.transform == TRANSFORM_INTEGER_TO_TEXT:
        if type(value) is not int:
            raise CompositionRuntimeError(
                "integer transform source is invalid"
            )
        return str(value)
    if binding.transform == TRANSFORM_FIXED_TITLE:
        if type(value) is not int or value < 0 or selected_project is None:
            raise CompositionRuntimeError("title transform source is invalid")
        return _bounded_text(
            f"Follow up on {selected_project}: review {value} open tasks",
            "generated task title",
        )
    raise CompositionRuntimeError("unsupported runtime transform")


def _materialize_arguments(step, results, selected_project):
    arguments = {}
    for binding in step.bindings:
        if isinstance(binding, LiteralBinding):
            value = binding.value
        elif isinstance(binding, ResultBinding):
            source = results.get(binding.source_step_id)
            if source is None:
                raise CompositionRuntimeError(
                    "prerequisite result is unavailable"
                )
            value = _transform(
                binding,
                _extract(source, binding.field_path),
                selected_project,
            )
        else:
            raise CompositionRuntimeError("runtime binding is malformed")
        arguments[binding.argument_name] = value
    return arguments


def _call_signature(tool_name, arguments):
    return _digest({"arguments": arguments, "tool_name": tool_name})


def _plan_is_authoritative(plan):
    try:
        return replace(plan) == plan
    except (TypeError, ValueError):
        return False


def _registry_matches(plan, registry):
    try:
        rebound = bind_composition_feasibility(plan.proposal, registry)
    except (TypeError, ValueError):
        return False
    return rebound.status == STATUS_FEASIBLE and rebound == plan


@dataclass(frozen=True)
class CompositionStepRun:
    """Bounded audit metadata for one attempted or skipped mission step."""

    step_id: str
    tool_name: str
    tool_version: str
    status: str
    argument_sha256: str = ""
    request_signature: str = ""
    run_id: str = ""
    result_sha256: str = ""
    executor_performed: bool = False

    def __post_init__(self):
        if self.status not in _STEP_STATUSES:
            raise CompositionRuntimeError("invalid step status")
        for name in (
            "step_id",
            "tool_name",
            "tool_version",
        ):
            _bounded_text(getattr(self, name), name, 128)
        for name in (
            "argument_sha256",
            "request_signature",
            "result_sha256",
        ):
            value = getattr(self, name)
            if value and (
                len(value) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in value
                )
            ):
                raise CompositionRuntimeError(f"invalid {name}")
        if self.run_id:
            _bounded_text(self.run_id, "run_id", 128)
        if self.status == STEP_SUCCEEDED and not self.executor_performed:
            raise CompositionRuntimeError("successful step did not execute")
        if self.status in {
            STEP_PENDING, STEP_BLOCKED, STEP_NOT_ATTEMPTED
        } and self.executor_performed:
            raise CompositionRuntimeError("unexecuted step claims execution")

    def to_dict(self):
        return {
            "argument_sha256": self.argument_sha256,
            "executor_performed": self.executor_performed,
            "request_signature": self.request_signature,
            "result_sha256": self.result_sha256,
            "run_id": self.run_id,
            "status": self.status,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
        }


@dataclass(frozen=True)
class CompositionMissionRun:
    """Immutable result of one bounded runtime composition attempt."""

    plan: FeasibleCompositionPlan
    status: str
    step_runs: tuple
    processed_requests: int
    executed_requests: int
    request_signatures: tuple
    selected_project: str = ""
    open_task_count: int = -1
    listed_open_task_count: int = -1
    memory_match_count: int = -1
    pending_operation_id: str = ""
    pending_operation_status: str = ""
    pending_tool_name: str = ""
    pending_tool_version: str = ""
    pending_arguments_sha256: str = ""
    failure_class: str = ""
    write_executed: bool = field(default=False, init=False)
    approval_performed: bool = field(default=False, init=False)
    generalized_resume_supported: bool = field(default=False, init=False)

    def __post_init__(self):
        if not isinstance(self.plan, FeasibleCompositionPlan):
            raise CompositionRuntimeError("invalid bound plan")
        steps = tuple(self.step_runs)
        signatures = tuple(self.request_signatures)
        if len(steps) != len(self.plan.bound_steps):
            raise CompositionRuntimeError(
                "runtime step sequence is incomplete"
            )
        if any(not isinstance(item, CompositionStepRun) for item in steps):
            raise CompositionRuntimeError("runtime step metadata is malformed")
        for bound, actual in zip(self.plan.bound_steps, steps):
            if (
                bound.step_id != actual.step_id
                or bound.tool.name != actual.tool_name
                or bound.tool.version != actual.tool_version
            ):
                raise CompositionRuntimeError("runtime step binding is forged")
        pending = self.status == STATUS_APPROVAL_PENDING
        expected_status = (
            STATUS_FAILED
            if self.failure_class
            and any(item.status == STEP_FAILED for item in steps)
            else STATUS_BLOCKED
        )
        if pending:
            expected_status = STATUS_APPROVAL_PENDING
        if self.status != expected_status:
            raise CompositionRuntimeError("runtime status is inconsistent")
        if pending:
            if (
                any(item.status != STEP_SUCCEEDED for item in steps[:-1])
                or steps[-1].status != STEP_PENDING
                or not self.pending_operation_id
                or self.pending_operation_status != "pending"
                or self.pending_tool_name != "tasks.create"
                or not self.pending_arguments_sha256
            ):
                raise CompositionRuntimeError(
                    "pending operation binding is invalid"
                )
        elif any((self.pending_operation_id, self.pending_operation_status)):
            raise CompositionRuntimeError(
                "failed run claims a pending operation"
            )
        if self.processed_requests != len(signatures):
            raise CompositionRuntimeError("processed-request count is forged")
        recorded_signatures = tuple(
            item.request_signature for item in steps if item.request_signature
        )
        if signatures != recorded_signatures:
            raise CompositionRuntimeError("request signatures are forged")
        if self.executed_requests != sum(
            item.executor_performed for item in steps
        ):
            raise CompositionRuntimeError("executed-request count is forged")
        if self.executed_requests > 4 or self.processed_requests > 5:
            raise CompositionRuntimeError("runtime budget is exceeded")
        if pending and (
            self.processed_requests != 5 or self.executed_requests != 4
        ):
            raise CompositionRuntimeError("pending runtime is incomplete")
        if self.selected_project:
            _bounded_text(self.selected_project, "selected_project", 100)
        if self.failure_class:
            _bounded_text(self.failure_class, "failure_class", 200)
        object.__setattr__(self, "step_runs", steps)
        object.__setattr__(self, "request_signatures", signatures)
        if len(self.summary().encode("utf-8")) > MAX_RUNTIME_SUMMARY_BYTES:
            raise CompositionRuntimeError("runtime summary exceeds byte limit")

    def to_dict(self):
        return {
            "authority": {
                "approval_performed": self.approval_performed,
                "generalized_resume_supported": (
                    self.generalized_resume_supported
                ),
                "write_executed": self.write_executed,
            },
            "counts": {
                "executed_requests": self.executed_requests,
                "listed_open_tasks": self.listed_open_task_count,
                "memory_matches": self.memory_match_count,
                "open_tasks": self.open_task_count,
                "processed_requests": self.processed_requests,
            },
            "failure_class": self.failure_class,
            "mission_id": self.plan.proposal.mission_id,
            "pending_operation": {
                "arguments_sha256": self.pending_arguments_sha256,
                "id": self.pending_operation_id,
                "status": self.pending_operation_status,
                "tool_name": self.pending_tool_name,
                "tool_version": self.pending_tool_version,
            },
            "plan_registry_snapshot_sha256": (
                self.plan.registry_snapshot_sha256
            ),
            "request_signatures": list(self.request_signatures),
            "selected_project": self.selected_project,
            "status": self.status,
            "steps": [item.to_dict() for item in self.step_runs],
        }

    def summary(self):
        return json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False, indent=2
        ) + "\n"


def _not_attempted(bound_steps):
    return tuple(
        CompositionStepRun(
            step_id=step.step_id,
            tool_name=step.tool.name,
            tool_version=step.tool.version,
            status=STEP_NOT_ATTEMPTED,
        )
        for step in bound_steps
    )


def _failed_run(
    plan,
    step_runs,
    budget,
    signatures,
    failure_class,
    *,
    selected_project="",
    open_task_count=-1,
    listed_open_task_count=-1,
    memory_match_count=-1,
    failed=False,
):
    completed = list(step_runs)
    remaining = plan.bound_steps[len(completed):]
    completed.extend(_not_attempted(remaining))
    return CompositionMissionRun(
        plan=plan,
        status=STATUS_FAILED if failed else STATUS_BLOCKED,
        step_runs=tuple(completed),
        processed_requests=budget.total_calls,
        executed_requests=budget.executions,
        request_signatures=tuple(signatures),
        selected_project=selected_project,
        open_task_count=open_task_count,
        listed_open_task_count=listed_open_task_count,
        memory_match_count=memory_match_count,
        failure_class=failure_class,
    )


def run_composition_mission(plan, registry, *, conversation_id=None):
    """Run four exact reads and freeze one exact write; never approve it."""
    if (
        not isinstance(plan, FeasibleCompositionPlan)
        or not _plan_is_authoritative(plan)
    ):
        raise CompositionRuntimeError("plan must be authoritative")
    if plan.status != STATUS_FEASIBLE:
        raise CompositionRuntimeError("plan must be feasible")
    if not isinstance(registry, ToolRegistry):
        raise CompositionRuntimeError("registry must be a ToolRegistry")

    budget = ToolCallBudget(
        max_calls=plan.proposal.max_processed_requests,
        max_identical_calls=plan.proposal.max_identical_requests,
        max_consecutive_failures=plan.proposal.max_consecutive_failures,
    )
    results = {}
    step_runs = []
    signatures = []
    selected_project = ""
    open_count = -1
    listed_count = -1
    memory_count = -1

    for index, (proposed, bound) in enumerate(
        zip(plan.proposal.steps, plan.bound_steps)
    ):
        if not _registry_matches(plan, registry):
            return _failed_run(
                plan,
                step_runs,
                budget,
                signatures,
                "RegistryMismatch",
                selected_project=selected_project,
                open_task_count=open_count,
                listed_open_task_count=listed_count,
                memory_match_count=memory_count,
            )
        try:
            definition = registry.get(bound.tool.name)
            arguments = _materialize_arguments(
                proposed, results, selected_project or None
            )
            arguments = validate_arguments(
                definition.input_schema, arguments
            )
        except Exception as error:
            return _failed_run(
                plan,
                step_runs,
                budget,
                signatures,
                type(error).__name__,
                selected_project=selected_project,
                open_task_count=open_count,
                listed_open_task_count=listed_count,
                memory_match_count=memory_count,
            )
        signature = _call_signature(definition.name, arguments)
        if not budget.allow_call(definition.name, arguments):
            budget.record(definition.name, arguments, OUTCOME_SKIPPED)
            signatures.append(signature)
            step_runs.append(
                CompositionStepRun(
                    bound.step_id,
                    bound.tool.name,
                    bound.tool.version,
                    STEP_BLOCKED,
                    _digest(arguments),
                    signature,
                )
            )
            return _failed_run(
                plan,
                step_runs,
                budget,
                signatures,
                "ToolBudgetExceededError",
                selected_project=selected_project,
                open_task_count=open_count,
                listed_open_task_count=listed_count,
                memory_match_count=memory_count,
            )

        if index == len(plan.bound_steps) - 1:
            if definition.risk != RISK_INTERNAL_WRITE:
                return _failed_run(
                    plan, step_runs, budget, signatures, "WriteRiskMismatch"
                )
            try:
                operation = create_pending_operation(
                    tool_name=definition.name,
                    tool_version=definition.version,
                    arguments=arguments,
                    conversation_id=conversation_id,
                    project=arguments.get("project"),
                )
            except Exception as error:
                budget.record(definition.name, arguments, OUTCOME_ERROR)
                signatures.append(signature)
                step_runs.append(
                    CompositionStepRun(
                        bound.step_id,
                        bound.tool.name,
                        bound.tool.version,
                        STEP_FAILED,
                        _digest(arguments),
                        signature,
                    )
                )
                return _failed_run(
                    plan,
                    step_runs,
                    budget,
                    signatures,
                    type(error).__name__,
                    selected_project=selected_project,
                    open_task_count=open_count,
                    listed_open_task_count=listed_count,
                    memory_match_count=memory_count,
                    failed=True,
                )
            budget.record(
                definition.name, arguments, OUTCOME_PENDING_OPERATION
            )
            signatures.append(signature)
            step_runs.append(
                CompositionStepRun(
                    bound.step_id,
                    bound.tool.name,
                    bound.tool.version,
                    STEP_PENDING,
                    _digest(arguments),
                    signature,
                )
            )
            return CompositionMissionRun(
                plan=plan,
                status=STATUS_APPROVAL_PENDING,
                step_runs=tuple(step_runs),
                processed_requests=budget.total_calls,
                executed_requests=budget.executions,
                request_signatures=tuple(signatures),
                selected_project=selected_project,
                open_task_count=open_count,
                listed_open_task_count=listed_count,
                memory_match_count=memory_count,
                pending_operation_id=operation["id"],
                pending_operation_status=operation["status"],
                pending_tool_name=operation["tool_name"],
                pending_tool_version=operation["tool_version"],
                pending_arguments_sha256=_digest(operation["arguments"]),
            )

        if definition.risk != RISK_READ_ONLY:
            return _failed_run(
                plan, step_runs, budget, signatures, "ReadRiskMismatch"
            )
        try:
            result = execute_tool(
                tool_name=definition.name,
                arguments=arguments,
                context=ToolExecutionContext(
                    conversation_id=conversation_id,
                    project=selected_project or None,
                    approved=False,
                ),
                registry=registry,
            )
        except Exception as error:
            budget.record(definition.name, arguments, OUTCOME_ERROR)
            signatures.append(signature)
            step_runs.append(
                CompositionStepRun(
                    bound.step_id,
                    bound.tool.name,
                    bound.tool.version,
                    STEP_FAILED,
                    _digest(arguments),
                    signature,
                )
            )
            return _failed_run(
                plan,
                step_runs,
                budget,
                signatures,
                type(error).__name__,
                selected_project=selected_project,
                open_task_count=open_count,
                listed_open_task_count=listed_count,
                memory_match_count=memory_count,
                failed=True,
            )

        budget.record(definition.name, arguments, OUTCOME_SUCCESS)
        signatures.append(signature)
        try:
            _validate_result(proposed, result.data)
            if bound.tool.name == "projects.overview":
                if result.data.get("truncated") is not False:
                    raise CompositionRuntimeError(
                        "project overview is incomplete"
                    )
                selected_project = _select_project(result.data["projects"])
            elif bound.tool.name == "tasks.status_summary":
                if result.data.get("project") != selected_project:
                    raise CompositionRuntimeError(
                        "task summary project binding differs"
                    )
                open_count = result.data["counts"]["open"]
                if type(open_count) is not int or open_count < 0:
                    raise CompositionRuntimeError(
                        "task summary open count is malformed"
                    )
            elif bound.tool.name == "tasks.list":
                tasks = result.data["tasks"]
                listed_count = result.data["count"]
                if (
                    type(listed_count) is not int
                    or listed_count != len(tasks)
                    or listed_count != open_count
                    or any(
                        not isinstance(task, dict)
                        or task.get("status") != "open"
                        or task.get("project") != selected_project
                        for task in tasks
                    )
                ):
                    raise CompositionRuntimeError(
                        "task summary and list materially disagree"
                    )
            elif bound.tool.name == "memory.search":
                memories = result.data["memories"]
                memory_count = result.data["count"]
                if (
                    type(memory_count) is not int
                    or memory_count != len(memories)
                    or result.data.get("query") != selected_project
                ):
                    raise CompositionRuntimeError(
                        "memory result binding is malformed"
                    )
        except Exception as error:
            step_runs.append(
                CompositionStepRun(
                    bound.step_id,
                    bound.tool.name,
                    bound.tool.version,
                    STEP_FAILED,
                    _digest(arguments),
                    signature,
                    result.run_id or "",
                    _digest(result.data),
                    executor_performed=True,
                )
            )
            return _failed_run(
                plan,
                step_runs,
                budget,
                signatures,
                type(error).__name__,
                selected_project=selected_project,
                open_task_count=open_count,
                listed_open_task_count=listed_count,
                memory_match_count=memory_count,
                failed=True,
            )
        results[proposed.step_id] = result.data
        step_runs.append(
            CompositionStepRun(
                bound.step_id,
                bound.tool.name,
                bound.tool.version,
                STEP_SUCCEEDED,
                _digest(arguments),
                signature,
                result.run_id or "",
                _digest(result.data),
                executor_performed=True,
            )
        )

    raise CompositionRuntimeError("mission ended without a terminal write")
