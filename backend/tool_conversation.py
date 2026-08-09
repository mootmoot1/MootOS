"""The bounded model <-> Tool System conversation loop for normal MootOS chat.

This is the orchestration described in the V0.2A specification:

    user request -> model reasoning -> tool selection -> registry
    validation -> permission check -> execution or approval request ->
    tool result -> model response -> execution receipt

Deterministic chat commands (explicit memory/Task writes) are handled
entirely before this module is ever reached -- see ``backend/main.py``. This
module only runs for ordinary provider-backed chat, and only engages tools
at all when the registry has something to offer and the configured provider
implements tool calling; otherwise it is a thin, zero-overhead pass-through
to ``ModelRouter.generate`` so existing plain-text behavior is unchanged.

Tool results returned to the model are always sent back through the
provider's own tool-result channel (see ``backend/model_router.py``), never
encoded as a fabricated user message -- the model sees them labeled as tool
output, not as something the user said.
"""

from dataclasses import dataclass
from typing import Any, Optional

from backend.model_router import ModelProviderError, ModelResponse, ModelRouter
from backend.tool_budget import (
    OUTCOME_ERROR,
    OUTCOME_SKIPPED,
    OUTCOME_SUCCESS,
    OUTCOME_UNKNOWN_TOOL,
    ToolCallBudget,
)
from backend.tool_executor import execute_tool, record_rejected_tool_attempt
from backend.tool_operations import create_pending_operation
from backend.tool_registry import ToolRegistry, get_tool_registry
from backend.tool_types import (
    RISK_HIGH_RISK,
    RISK_INTERNAL_WRITE,
    ToolExecutionContext,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolRequest,
    ToolResult,
    ToolValidationError,
)
from backend.tool_validation import validate_arguments


SKIPPED_BY_BUDGET_SUMMARY = (
    "MootOS did not run this tool call: the per-turn tool-call limit was reached."
)
HIGH_RISK_SUMMARY = "This tool is not available for automatic or approved execution in this version."
FALLBACK_BUDGET_TEXT = (
    "MootOS stopped after reaching the maximum number of actions allowed for one "
    "turn. Ask again if you would like MootOS to continue."
)
FALLBACK_BUDGET_PROVIDER = "mootos"
FALLBACK_BUDGET_MODEL = "tool-budget-v1"


@dataclass(frozen=True)
class ToolConversationOutcome:
    """The result of one bounded tool-calling chat turn.

    ``kind == "final"``: ``response`` is a normal, ready-to-commit
    ``ModelResponse`` (possibly reached only after 0+ tool rounds).

    ``kind == "approval_required"``: nothing wrote anything. ``operation``
    is the frozen pending approval (safe to show a client), and
    ``assistant_text`` is a deterministic summary suitable for the normal
    assistant chat message.
    """

    kind: str
    response: Optional[ModelResponse] = None
    operation: Optional[dict[str, Any]] = None
    assistant_text: Optional[str] = None


def _format_operation_summary(tool_name: str, arguments: dict[str, Any]) -> str:
    if not arguments:
        return f'MootOS prepared "{tool_name}" and needs your approval before it runs.'
    details = ", ".join(
        f"{key}: {value}" for key, value in arguments.items() if value not in (None, "")
    )
    return (
        f'MootOS prepared "{tool_name}" and needs your approval before it runs '
        f"({details}). Approve or reject it to continue."
    )


def _skipped_result(request: ToolRequest) -> ToolResult:
    return ToolResult(
        success=False,
        tool_name=request.name,
        data=None,
        summary=SKIPPED_BY_BUDGET_SUMMARY,
        call_id=request.call_id,
    )


def _finalize_after_budget(
    router: ModelRouter,
    state: Any,
    tool_results: list[ToolResult],
) -> ModelResponse:
    """Ask the provider for one honest closing answer with tools disabled."""
    try:
        final_turn = router.continue_tool_turn(state, tool_results, force_text=True)
    except ModelProviderError:
        final_turn = None

    if final_turn is not None and final_turn.kind == "final" and final_turn.text:
        return ModelResponse(
            text=final_turn.text,
            provider=final_turn.provider,
            model=final_turn.model,
        )
    return ModelResponse(
        text=FALLBACK_BUDGET_TEXT,
        provider=FALLBACK_BUDGET_PROVIDER,
        model=FALLBACK_BUDGET_MODEL,
    )


def _router_supports_tools(router: ModelRouter) -> bool:
    """Duck-typed capability probe.

    Prefers the router's own ``supports_tools()`` when it defines one (the
    real ``ModelRouter`` always does). Falls back to checking for
    ``generate_with_tools`` directly so a minimal test double or a future
    router-like object that only implements plain ``generate`` is routed to
    the existing plain-text path instead of raising ``AttributeError``.
    """
    probe = getattr(router, "supports_tools", None)
    if callable(probe):
        try:
            return bool(probe())
        except Exception:
            return False
    return hasattr(router, "generate_with_tools") and hasattr(router, "continue_tool_turn")


def run_tool_conversation(
    *,
    router: ModelRouter,
    conversation_id: Optional[str],
    project: Optional[str],
    messages: list[dict[str, str]],
    instructions: str,
    registry: Optional[ToolRegistry] = None,
) -> ToolConversationOutcome:
    """Run one bounded, provider-backed chat turn with Tool System support.

    Falls back to plain ``router.generate`` (unchanged behavior) whenever
    there is nothing to gain from tool calling: an empty registry, or a
    provider that does not implement it.
    """
    active_registry = registry if registry is not None else get_tool_registry()
    catalog = active_registry.catalog()

    if not catalog or not _router_supports_tools(router):
        response = router.generate(messages=messages, instructions=instructions)
        return ToolConversationOutcome(kind="final", response=response)

    context = ToolExecutionContext(conversation_id=conversation_id, project=project, approved=False)
    budget = ToolCallBudget()

    turn = router.generate_with_tools(messages=messages, instructions=instructions, tools=catalog)

    while True:
        if turn.kind != "tool_calls":
            return ToolConversationOutcome(
                kind="final",
                response=ModelResponse(text=turn.text, provider=turn.provider, model=turn.model),
            )

        tool_results: list[ToolResult] = []

        for request in turn.tool_requests:
            if not budget.allow_call(request.name, request.arguments):
                # Recording the skip (not just appending a result) is what
                # guarantees the loop terminates: without it, a request that
                # keeps getting denied by the identical-call cap would never
                # advance ``total_calls``, and the post-batch budget check
                # below would never trip -- the loop would keep asking the
                # model for another round indefinitely. Every processed
                # request, skipped or not, now counts toward the same 5-call
                # ceiling, so it is also always a hard bound on how many
                # rounds this loop can run.
                budget.record(request.name, request.arguments, OUTCOME_SKIPPED)
                tool_results.append(_skipped_result(request))
                continue

            try:
                definition = active_registry.get(request.name)
            except ToolNotFoundError as error:
                record_rejected_tool_attempt(
                    tool_name=request.name,
                    conversation_id=conversation_id,
                    error=error,
                    registry=active_registry,
                )
                budget.record(request.name, request.arguments, OUTCOME_UNKNOWN_TOOL)
                tool_results.append(
                    ToolResult(
                        success=False,
                        tool_name=request.name,
                        data=None,
                        summary="Unknown tool.",
                        call_id=request.call_id,
                    )
                )
                continue

            try:
                validated_arguments = validate_arguments(definition.input_schema, request.arguments)
            except ToolValidationError as error:
                record_rejected_tool_attempt(
                    tool_name=definition.name,
                    conversation_id=conversation_id,
                    error=error,
                    registry=active_registry,
                )
                budget.record(definition.name, request.arguments, OUTCOME_ERROR)
                tool_results.append(
                    ToolResult(
                        success=False,
                        tool_name=definition.name,
                        data=None,
                        summary=str(error),
                        call_id=request.call_id,
                    )
                )
                continue

            if definition.risk == RISK_HIGH_RISK:
                high_risk_error = ToolPermissionError(HIGH_RISK_SUMMARY)
                record_rejected_tool_attempt(
                    tool_name=definition.name,
                    conversation_id=conversation_id,
                    error=high_risk_error,
                    registry=active_registry,
                )
                budget.record(definition.name, validated_arguments, OUTCOME_ERROR)
                tool_results.append(
                    ToolResult(
                        success=False,
                        tool_name=definition.name,
                        data=None,
                        summary=HIGH_RISK_SUMMARY,
                        call_id=request.call_id,
                    )
                )
                continue

            if definition.risk == RISK_INTERNAL_WRITE:
                operation = create_pending_operation(
                    tool_name=definition.name,
                    tool_version=definition.version,
                    arguments=validated_arguments,
                    conversation_id=conversation_id,
                    project=project,
                )
                return ToolConversationOutcome(
                    kind="approval_required",
                    operation=operation,
                    assistant_text=_format_operation_summary(definition.name, validated_arguments),
                )

            # RISK_READ_ONLY: the only risk level left, may auto-execute.
            try:
                result = execute_tool(
                    tool_name=definition.name,
                    arguments=validated_arguments,
                    context=context,
                    registry=active_registry,
                )
            except (ToolValidationError, ToolPermissionError, ToolExecutionError) as error:
                budget.record(definition.name, validated_arguments, OUTCOME_ERROR)
                tool_results.append(
                    ToolResult(
                        success=False,
                        tool_name=definition.name,
                        data=None,
                        summary=str(error),
                        call_id=request.call_id,
                    )
                )
                continue

            budget.record(definition.name, validated_arguments, OUTCOME_SUCCESS)
            tool_results.append(
                ToolResult(
                    success=True,
                    tool_name=result.tool_name,
                    data=result.data,
                    summary=result.summary,
                    run_id=result.run_id,
                    call_id=request.call_id,
                )
            )

        if not budget.allow_next():
            response = _finalize_after_budget(router, turn.state, tool_results)
            return ToolConversationOutcome(kind="final", response=response)

        turn = router.continue_tool_turn(turn.state, tool_results, tools=catalog)
