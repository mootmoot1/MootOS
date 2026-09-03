"""Tests for centralized tool-call budget / loop protection."""

from backend.tool_budget import (
    MAX_CONSECUTIVE_FAILURES,
    MAX_IDENTICAL_CALLS_PER_TURN,
    MAX_TOOL_CALLS_PER_TURN,
    OUTCOME_ERROR,
    OUTCOME_PENDING_OPERATION,
    OUTCOME_SUCCESS,
    OUTCOME_UNKNOWN_TOOL,
    ToolCallBudget,
)


def test_max_five_calls_per_turn_by_default():
    assert MAX_TOOL_CALLS_PER_TURN == 5
    budget = ToolCallBudget()
    for index in range(5):
        assert budget.allow_call("tool", {"n": index}) is True
        budget.record("tool", {"n": index}, OUTCOME_SUCCESS)

    assert budget.allow_next() is False
    assert budget.allow_call("tool", {"n": "sixth"}) is False


def test_budget_limit_is_centralized_and_configurable():
    budget = ToolCallBudget(max_calls=2)
    budget.record("tool", {"a": 1}, OUTCOME_SUCCESS)
    budget.record("tool", {"a": 2}, OUTCOME_SUCCESS)

    assert budget.allow_next() is False


def test_repeated_identical_calls_are_capped():
    budget = ToolCallBudget()
    same_args = {"query": "car"}

    assert budget.allow_call("memory.search", same_args) is True
    budget.record("memory.search", same_args, OUTCOME_SUCCESS)
    assert budget.allow_call("memory.search", same_args) is True
    budget.record("memory.search", same_args, OUTCOME_SUCCESS)

    # A third identical call is blocked with room under the total-call cap.
    assert MAX_IDENTICAL_CALLS_PER_TURN == 2
    assert budget.allow_call("memory.search", same_args) is False
    assert budget.remaining() == MAX_TOOL_CALLS_PER_TURN - 2


def test_argument_order_does_not_evade_the_duplicate_cap():
    budget = ToolCallBudget()
    budget.record("tool", {"a": 1, "b": 2}, OUTCOME_SUCCESS)
    budget.record("tool", {"b": 2, "a": 1}, OUTCOME_SUCCESS)

    assert budget.allow_call("tool", {"a": 1, "b": 2}) is False


def test_repeated_nonexistent_tool_requests_stop_the_loop_early():
    """Each distinct nonexistent-tool attempt is still a failure outcome.

    Consecutive-failure protection stops the loop well before the 5-call
    hard cap, even though every attempt names a different tool name (so
    the duplicate-call cap alone would not have caught it).
    """
    budget = ToolCallBudget()
    allowed = 0
    for index in range(5):
        if not budget.allow_call(f"does.not.exist.{index}", {}):
            break
        budget.record(f"does.not.exist.{index}", {}, OUTCOME_UNKNOWN_TOOL)
        allowed += 1

    assert allowed == MAX_CONSECUTIVE_FAILURES
    assert budget.allow_next() is False
    assert budget.total_calls < MAX_TOOL_CALLS_PER_TURN


def test_consecutive_failures_stop_the_loop_before_the_hard_cap():
    assert MAX_CONSECUTIVE_FAILURES == 2
    budget = ToolCallBudget()
    budget.record("tool", {"n": 1}, OUTCOME_ERROR)
    assert budget.allow_next() is True
    budget.record("tool", {"n": 2}, OUTCOME_ERROR)

    assert budget.allow_next() is False
    assert budget.total_calls < budget.max_calls


def test_a_success_resets_the_consecutive_failure_streak():
    budget = ToolCallBudget()
    budget.record("tool", {"n": 1}, OUTCOME_ERROR)
    budget.record("tool", {"n": 2}, OUTCOME_SUCCESS)
    budget.record("tool", {"n": 3}, OUTCOME_ERROR)

    assert budget.allow_next() is True


def test_pending_operation_consumes_request_without_claiming_execution():
    budget = ToolCallBudget()
    arguments = {"title": "Review project", "project": "MootOS"}

    assert budget.allow_call("tasks.create", arguments) is True
    budget.record(
        "tasks.create", arguments, OUTCOME_PENDING_OPERATION
    )

    assert budget.total_calls == 1
    assert budget.executions == 0
    assert budget.consecutive_failures == 0
    assert budget.remaining() == MAX_TOOL_CALLS_PER_TURN - 1
