"""The single centralized executor for the MootOS Tool System.

Every actual tool execution -- whether an auto-executed read tool or an
approved write tool -- goes through ``execute_tool``. Individual tools never
start their own Run, check their own permissions, or format their own
errors; this is the one place that does it, so those rules can't drift
between tools.

Risk enforcement here is a deliberate second layer, not the only one. The
tool conversation loop (backend/tool_conversation.py) is expected to route
INTERNAL_WRITE tool requests to the approval flow *before* ever calling this
function for an unapproved request. This function enforces the same rule
again so that any other caller -- present or future -- cannot bypass it by
skipping the conversation loop.
"""

from typing import Any, Optional

from backend.runs import (
    DATA_EXPOSURE_LOCAL,
    finish_tool_run_failure,
    finish_tool_run_success,
    start_tool_run,
)
from backend.tool_registry import ToolRegistry, get_tool_registry
from backend.tool_types import (
    RISK_HIGH_RISK,
    RISK_INTERNAL_WRITE,
    ToolExecutionContext,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolResult,
    ToolValidationError,
)
from backend.tool_validation import validate_arguments


GENERIC_EXECUTION_ERROR = "MootOS could not complete this action."
HIGH_RISK_BLOCKED_MESSAGE = (
    "High-risk tools cannot execute automatically or by approval in this version"
)
APPROVAL_REQUIRED_MESSAGE = "This tool requires explicit approval before it can run"


def execute_tool(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    context: ToolExecutionContext,
    registry: Optional[ToolRegistry] = None,
) -> ToolResult:
    """Resolve, validate, authorize, Run-log, and run exactly one tool.

    Raises ``ToolNotFoundError``, ``ToolValidationError``,
    ``ToolPermissionError``, or ``ToolExecutionError`` on failure -- all
    three carry only safe, sanitized messages; the underlying exception's
    class name (never its text) is the only thing persisted to the Run.
    """
    active_registry = registry or get_tool_registry()

    try:
        definition = active_registry.get(tool_name)
    except ToolNotFoundError as error:
        # A genuinely unregistered name still gets an audit trail entry --
        # this is what lets a repeatedly-nonexistent-tool request show up in
        # Activity instead of vanishing silently.
        run = start_tool_run(
            conversation_id=context.conversation_id,
            tool_name=tool_name or "unknown",
            tool_version=None,
            data_exposure=DATA_EXPOSURE_LOCAL,
        )
        finish_tool_run_failure(run["id"], error)
        raise

    run = start_tool_run(
        conversation_id=context.conversation_id,
        tool_name=definition.name,
        tool_version=definition.version,
        data_exposure=definition.data_exposure,
    )

    try:
        validated_arguments = validate_arguments(definition.input_schema, arguments)

        if definition.risk == RISK_HIGH_RISK:
            raise ToolPermissionError(HIGH_RISK_BLOCKED_MESSAGE)
        if definition.risk == RISK_INTERNAL_WRITE and not context.approved:
            raise ToolPermissionError(APPROVAL_REQUIRED_MESSAGE)

        raw_result = definition.executor(validated_arguments, context)
    except (ToolValidationError, ToolPermissionError, ToolExecutionError) as error:
        finish_tool_run_failure(run["id"], error)
        raise
    except Exception as error:  # Deliberately broad: sanitized at this boundary.
        finish_tool_run_failure(run["id"], error)
        raise ToolExecutionError(GENERIC_EXECUTION_ERROR) from error

    finish_tool_run_success(run["id"])
    data = raw_result if isinstance(raw_result, dict) else {"result": raw_result}
    return ToolResult(
        success=True,
        tool_name=definition.name,
        data=data,
        summary=f"{definition.name} completed successfully.",
        run_id=run["id"],
    )
