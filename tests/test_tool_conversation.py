"""Tests for the bounded model <-> Tool System conversation loop."""

import pytest

from backend.db import DATABASE_PATH
from backend.memory import create_memory, init_db
from backend.model_router import ModelResponse
from backend.runs import RUN_TYPE_TOOL, list_runs
from backend.tasks import list_tasks
from backend.tool_conversation import run_tool_conversation
from backend.tool_operations import OPERATION_STATUS_PENDING, list_pending_operations
from backend.tool_registry import get_tool_registry
from backend.tool_types import ToolRequest


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


class _FakeState:
    def __init__(self, round_number: int) -> None:
        self.round_number = round_number


class _FakeTurn:
    def __init__(self, kind, text=None, tool_requests=None, state=None):
        self.kind = kind
        self.text = text
        self.tool_requests = tool_requests or []
        self.provider = "fake"
        self.model = "fake-model"
        self.state = state


class PlainFakeRouter:
    """Mirrors the existing plain-generate test doubles used elsewhere.

    Deliberately does not implement generate_with_tools/supports_tools, to
    prove the loop still falls back to plain generate() for routers that
    only implement the original interface.
    """

    def __init__(self, text="Plain answer"):
        self.text = text
        self.calls = 0

    def ensure_ready(self):
        return None

    def generate(self, messages, instructions):
        self.calls += 1
        return ModelResponse(text=self.text, provider="fake", model="fake-model")


class ScriptedToolRouter:
    """A router whose generate_with_tools/continue_tool_turn follow a script."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.plain_generate_calls = 0

    def ensure_ready(self):
        return None

    def supports_tools(self):
        return True

    def generate(self, messages, instructions):
        self.plain_generate_calls += 1
        return ModelResponse(text="should not be used", provider="fake", model="fake-model")

    def generate_with_tools(self, messages, instructions, tools):
        return self._next()

    def continue_tool_turn(self, state, tool_results, force_text=False, tools=None):
        if force_text:
            return self.script[-1] if isinstance(self.script[-1], _FakeTurn) else self._next()
        return self._next()

    def _next(self):
        turn = self.script[self.calls]
        self.calls += 1
        return turn


def test_falls_back_to_plain_generate_when_registry_empty(clean_db):
    from backend.tool_registry import ToolRegistry

    router = PlainFakeRouter("hello")
    outcome = run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "hi"}],
        instructions="x",
        registry=ToolRegistry(),
    )

    assert outcome.kind == "final"
    assert outcome.response.text == "hello"
    assert router.calls == 1


def test_an_explicitly_empty_registry_is_never_silently_replaced_by_the_default_one(clean_db):
    """V0.3A regression: an empty ``ToolRegistry()`` is falsy (``__len__`` ==
    0), so ``registry or get_tool_registry()`` previously substituted the
    real process-wide default registry for it -- an intentionally empty
    registry would silently gain the four real V0.2A tools. Fixed to
    ``registry if registry is not None else get_tool_registry()``.

    A router that *does* support tool calling isolates this: the only
    reason this call could still fall back to plain generate() is the
    registry genuinely being treated as empty, not the router lacking tool
    support (unlike the test above, which uses PlainFakeRouter for that
    other reason)."""
    from backend.tool_registry import ToolRegistry

    router = ScriptedToolRouter([_FakeTurn(kind="final", text="should not be reached")])

    outcome = run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "hi"}],
        instructions="x",
        registry=ToolRegistry(),
    )

    assert outcome.kind == "final"
    assert outcome.response.text == "should not be used"  # ScriptedToolRouter.generate()'s fixed text
    assert router.plain_generate_calls == 1
    assert router.calls == 0  # generate_with_tools() was never reached


def test_falls_back_to_plain_generate_when_router_lacks_tool_support(clean_db):
    router = PlainFakeRouter("hello")
    outcome = run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "hi"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    assert outcome.response.text == "hello"
    assert router.calls == 1


def test_plain_answer_with_no_tool_calls(clean_db):
    router = ScriptedToolRouter([_FakeTurn("final", text="No tools needed here.")])

    outcome = run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "hi"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    assert outcome.response.text == "No tools needed here."


def test_read_only_tool_chain_feeds_results_back_and_produces_final_text(clean_db):
    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                tool_requests=[ToolRequest(name="projects.list", arguments={}, call_id="c1")],
                state=_FakeState(1),
            ),
            _FakeTurn("final", text="You have several projects."),
        ]
    )

    outcome = run_tool_conversation(
        router=router,
        conversation_id="conversation-1",
        project=None,
        messages=[{"role": "user", "content": "What projects do I have?"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    assert outcome.response.text == "You have several projects."
    tool_runs = [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL]
    assert len(tool_runs) == 1
    assert tool_runs[0]["tool_name"] == "projects.list"
    assert tool_runs[0]["status"] == "succeeded"


def test_multi_read_tool_loop_is_bounded_within_budget(clean_db):
    create_memory(content="Studio note about mixing")
    turns = []
    for index in range(3):
        turns.append(
            _FakeTurn(
                "tool_calls",
                tool_requests=[ToolRequest(name="memory.search", arguments={"query": f"q{index}"}, call_id=f"c{index}")],
                state=_FakeState(index),
            )
        )
    turns.append(_FakeTurn("final", text="Summary of what I found."))
    router = ScriptedToolRouter(turns)

    outcome = run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "search a few times"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    assert outcome.response.text == "Summary of what I found."
    tool_runs = [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL]
    assert len(tool_runs) == 3


def test_write_tool_request_stops_the_loop_and_creates_pending_operation(clean_db):
    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                tool_requests=[
                    ToolRequest(name="tasks.create", arguments={"title": "Call Mike"}, call_id="c1")
                ],
                state=_FakeState(1),
            ),
        ]
    )

    outcome = run_tool_conversation(
        router=router,
        conversation_id="conversation-1",
        project=None,
        messages=[{"role": "user", "content": "make me a task"}],
        instructions="x",
    )

    assert outcome.kind == "approval_required"
    assert outcome.operation["tool_name"] == "tasks.create"
    assert outcome.operation["status"] == OPERATION_STATUS_PENDING
    assert outcome.operation["arguments"] == {"title": "Call Mike"}
    assert "approval" in outcome.assistant_text.lower()

    # No execution happened: no Task, no tool Run.
    assert list_tasks() == []
    assert [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL] == []
    assert len(list_pending_operations(conversation_id="conversation-1")) == 1


def test_write_tool_request_with_valid_due_at_reaches_approval_normalized_to_utc(clean_db):
    """Live-approval-testing regression: a valid, real due_at reaches
    approval, and the frozen operation stores the UTC-normalized form the
    existing Task system uses -- not the model's original offset string."""
    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                tool_requests=[
                    ToolRequest(
                        name="tasks.create",
                        arguments={"title": "Call Mike", "due_at": "2026-08-10T15:00:00-04:00"},
                        call_id="c1",
                    )
                ],
                state=_FakeState(1),
            ),
        ]
    )

    outcome = run_tool_conversation(
        router=router,
        conversation_id="conversation-1",
        project=None,
        messages=[{"role": "user", "content": "make me a task due Monday at 3pm eastern"}],
        instructions="x",
    )

    assert outcome.kind == "approval_required"
    assert outcome.operation["arguments"]["due_at"] == "2026-08-10T19:00:00+00:00"


@pytest.mark.parametrize("placeholder", ["none", "null", "unknown"])
def test_write_tool_request_with_placeholder_due_at_is_rejected_before_approval(clean_db, placeholder):
    """Live-approval-testing regression: due_at: "none" (or similar
    placeholders) must never reach a pending approval operation -- the
    model sees a normal failed tool result instead of an approval card for
    something that could never execute."""
    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                tool_requests=[
                    ToolRequest(
                        name="tasks.create",
                        arguments={"title": "Call Mike", "due_at": placeholder},
                        call_id="c1",
                    )
                ],
                state=_FakeState(1),
            ),
            _FakeTurn("final", text="I could not schedule that; let me know a real date."),
        ]
    )

    outcome = run_tool_conversation(
        router=router,
        conversation_id="conversation-1",
        project=None,
        messages=[{"role": "user", "content": "make me a task"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    assert list_tasks() == []
    assert list_pending_operations(conversation_id="conversation-1") == []
    # A normal failed tool Run was still recorded (early-rejection audit
    # trail), never a tool_operations row.
    tool_runs = [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL]
    assert len(tool_runs) == 1
    assert tool_runs[0]["status"] == "failed"
    assert tool_runs[0]["error_class"] == "ToolValidationError"


def test_write_tool_request_with_malformed_due_at_is_rejected_before_approval(clean_db):
    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                tool_requests=[
                    ToolRequest(
                        name="tasks.create",
                        arguments={"title": "Call Mike", "due_at": "not a real date"},
                        call_id="c1",
                    )
                ],
                state=_FakeState(1),
            ),
            _FakeTurn("final", text="I need a real date to schedule that."),
        ]
    )

    outcome = run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "make me a task"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    assert list_tasks() == []
    assert list_pending_operations() == []


def test_write_tool_request_with_timezone_naive_due_at_is_rejected_before_approval(clean_db):
    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                tool_requests=[
                    ToolRequest(
                        name="tasks.create",
                        arguments={"title": "Call Mike", "due_at": "2026-08-10T15:00:00"},
                        call_id="c1",
                    )
                ],
                state=_FakeState(1),
            ),
            _FakeTurn("final", text="I need a timezone to schedule that."),
        ]
    )

    outcome = run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "make me a task"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    assert list_tasks() == []
    assert list_pending_operations() == []


def test_unknown_tool_request_is_fed_back_as_a_failed_result_and_loop_continues(clean_db):
    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                tool_requests=[ToolRequest(name="does.not.exist", arguments={}, call_id="c1")],
                state=_FakeState(1),
            ),
            _FakeTurn("final", text="That tool does not exist."),
        ]
    )

    outcome = run_tool_conversation(
        router=router,
        conversation_id="conversation-unknown",
        project=None,
        messages=[{"role": "user", "content": "use a fake tool"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    assert outcome.response.text == "That tool does not exist."

    # Grok audit remediation: an unregistered-tool request must still leave
    # exactly one failed tool Run, not vanish silently.
    tool_runs = [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL]
    assert len(tool_runs) == 1
    assert tool_runs[0]["tool_name"] == "does.not.exist"
    assert tool_runs[0]["tool_version"] is None
    assert tool_runs[0]["status"] == "failed"
    assert tool_runs[0]["error_class"] == "ToolNotFoundError"
    assert tool_runs[0]["conversation_id"] == "conversation-unknown"


def test_schema_validation_failure_creates_exactly_one_failed_tool_run(clean_db):
    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                # memory.search requires a non-empty "query" -- omit it.
                tool_requests=[ToolRequest(name="memory.search", arguments={}, call_id="c1")],
                state=_FakeState(1),
            ),
            _FakeTurn("final", text="I need a search term."),
        ]
    )

    outcome = run_tool_conversation(
        router=router,
        conversation_id="conversation-invalid-args",
        project=None,
        messages=[{"role": "user", "content": "search"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    tool_runs = [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL]
    assert len(tool_runs) == 1
    assert tool_runs[0]["tool_name"] == "memory.search"
    assert tool_runs[0]["tool_version"] == "1"
    assert tool_runs[0]["status"] == "failed"
    assert tool_runs[0]["error_class"] == "ToolValidationError"
    assert tool_runs[0]["conversation_id"] == "conversation-invalid-args"


def test_high_risk_refusal_creates_exactly_one_failed_tool_run(clean_db):
    from backend.tool_registry import ToolRegistry
    from backend.tool_types import RISK_HIGH_RISK, ToolDefinition

    danger = ToolDefinition(
        name="danger.thing",
        version="7",
        description="A high-risk tool that must never execute.",
        input_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        risk=RISK_HIGH_RISK,
        data_exposure="tool_external",
        executor=lambda arguments, context: {"never": "runs"},
    )
    registry = ToolRegistry()
    registry.register(danger)

    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                tool_requests=[ToolRequest(name="danger.thing", arguments={}, call_id="c1")],
                state=_FakeState(1),
            ),
            _FakeTurn("final", text="I cannot do that."),
        ]
    )

    outcome = run_tool_conversation(
        router=router,
        conversation_id="conversation-high-risk",
        project=None,
        messages=[{"role": "user", "content": "do the dangerous thing"}],
        instructions="x",
        registry=registry,
    )

    assert outcome.kind == "final"
    tool_runs = [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL]
    assert len(tool_runs) == 1
    assert tool_runs[0]["tool_name"] == "danger.thing"
    assert tool_runs[0]["tool_version"] == "7"
    assert tool_runs[0]["status"] == "failed"
    assert tool_runs[0]["error_class"] == "ToolPermissionError"
    assert tool_runs[0]["data_exposure"] == "tool_external"


def test_early_rejection_runs_never_store_arguments_or_content(clean_db):
    """Privacy: the Run row for an early rejection carries no arguments,
    memory content, prompt text, or model output -- only sanitized identity
    and outcome metadata."""
    from backend.db import database_connection

    secret_query = "super secret project codename Phoenix" + ("x" * 480)
    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                # Too long for memory.search's maxLength -- a validation
                # failure whose rejected argument must not reach the Run row.
                tool_requests=[ToolRequest(name="memory.search", arguments={"query": secret_query}, call_id="c1")],
                state=_FakeState(1),
            ),
            _FakeTurn("final", text="ok"),
        ]
    )

    run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "search"}],
        instructions="x",
    )

    with database_connection() as connection:
        row = connection.execute("SELECT * FROM runs WHERE run_type = 'tool'").fetchone()
    assert row is not None
    serialized = str(dict(row))
    assert "codename Phoenix" not in serialized
    assert secret_query not in serialized


def test_budget_exceeded_stops_safely_with_honest_final_response(clean_db):
    # Distinct arguments each round so the 5-call hard cap is what stops the
    # loop, not the separate identical-call duplicate cap.
    turns = []
    for index in range(6):
        turns.append(
            _FakeTurn(
                "tool_calls",
                tool_requests=[
                    ToolRequest(name="memory.search", arguments={"query": f"topic-{index}"}, call_id=f"c{index}")
                ],
                state=_FakeState(index),
            )
        )
    turns.append(_FakeTurn("final", text="Wrapped up after the limit."))
    router = ScriptedToolRouter(turns)

    outcome = run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "loop forever"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    tool_runs = [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL]
    assert len(tool_runs) == 5


class DuplicateRequestRouter:
    """Always returns the exact same duplicate tool request, forever.

    Used to prove the budget forces termination instead of looping forever:
    before the Grok remediation, a request denied by the identical-call cap
    was never recorded against the budget, so the post-batch
    ``budget.allow_next()`` check never tripped and the loop could bounce
    through an unbounded number of rounds. ``MAX_SAFETY_CALLS`` is a
    generous ceiling far above what correct code should ever reach; if the
    loop is actually unbounded, this test fails loudly instead of hanging.
    """

    MAX_SAFETY_CALLS = 50

    def __init__(self):
        self.calls = 0

    def ensure_ready(self):
        return None

    def supports_tools(self):
        return True

    def generate(self, messages, instructions):
        raise AssertionError("plain generate should not run when tools are offered")

    def generate_with_tools(self, messages, instructions, tools):
        return self._turn()

    def continue_tool_turn(self, state, tool_results, force_text=False, tools=None):
        if force_text:
            return _FakeTurn("final", text="Wrapping up.")
        return self._turn()

    def _turn(self):
        self.calls += 1
        if self.calls > self.MAX_SAFETY_CALLS:
            raise AssertionError(
                "tool conversation loop did not terminate (possible infinite loop)"
            )
        return _FakeTurn(
            "tool_calls",
            tool_requests=[
                ToolRequest(name="memory.search", arguments={"query": "same"}, call_id=f"c{self.calls}")
            ],
            state=_FakeState(self.calls),
        )


def test_repeated_duplicate_calls_terminate_instead_of_looping_forever(clean_db):
    """Grok audit remediation: a request denied by the duplicate-call cap
    must still consume budget, or the loop never terminates."""
    router = DuplicateRequestRouter()

    outcome = run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "search repeatedly"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    # Bounded well under the safety ceiling: the identical-call cap (2 real
    # executions) plus the 5-call total budget must stop this in a handful
    # of rounds, never anywhere near 50.
    assert router.calls <= 6

    tool_runs = [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL]
    # Only the two calls that got past the duplicate cap actually executed.
    assert len(tool_runs) == 2


def test_single_turn_with_more_tool_calls_than_remaining_budget(clean_db):
    """A model response containing more tool calls than remain in the
    turn's budget must only execute up to the remaining budget -- the rest
    are denied, not queued for a future turn."""
    requests = [
        ToolRequest(name="memory.search", arguments={"query": f"topic-{index}"}, call_id=f"c{index}")
        for index in range(7)
    ]
    router = ScriptedToolRouter(
        [
            _FakeTurn("tool_calls", tool_requests=requests, state=_FakeState(1)),
            _FakeTurn("final", text="Handled the first few."),
        ]
    )

    outcome = run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "search for seven different things at once"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    assert outcome.response.text == "Handled the first few."
    tool_runs = [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL]
    # Exactly the 5-call budget, not all 7 requested.
    assert len(tool_runs) == 5
    # Only the initial generate_with_tools() call was needed to receive the
    # whole batch of 7 requests -- processing the excess ones as denied
    # (rather than queuing them for another round) means the forced-text
    # finalize is reached without any extra tool-calling round trip.
    assert router.calls == 1


def test_combined_memory_search_then_task_create_requires_approval(clean_db):
    create_memory(content="Need to renew the studio insurance policy")

    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                tool_requests=[
                    ToolRequest(name="memory.search", arguments={"query": "insurance"}, call_id="c1")
                ],
                state=_FakeState(1),
            ),
            _FakeTurn(
                "tool_calls",
                tool_requests=[
                    ToolRequest(
                        name="tasks.create",
                        arguments={"title": "Renew studio insurance"},
                        call_id="c2",
                    )
                ],
                state=_FakeState(2),
            ),
        ]
    )

    outcome = run_tool_conversation(
        router=router,
        conversation_id="conversation-9",
        project=None,
        messages=[{"role": "user", "content": "find something I still need to do and make a task"}],
        instructions="x",
    )

    assert outcome.kind == "approval_required"
    assert outcome.operation["arguments"]["title"] == "Renew studio insurance"
    # The read-only memory.search call before the write request really ran.
    tool_runs = [run for run in list_runs() if run["run_type"] == RUN_TYPE_TOOL]
    assert [run["tool_name"] for run in tool_runs] == ["memory.search"]
    assert list_tasks() == []


def test_uses_the_real_default_registry_when_none_is_supplied(clean_db):
    router = ScriptedToolRouter([_FakeTurn("final", text="ok")])

    run_tool_conversation(
        router=router,
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "hi"}],
        instructions="x",
    )

    # Sanity: the default registry is the same one the rest of the app uses.
    assert {d.name for d in get_tool_registry().list_definitions()} >= {
        "projects.list",
        "memory.search",
        "tasks.list",
        "tasks.create",
    }
