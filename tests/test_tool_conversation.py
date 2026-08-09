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
        conversation_id=None,
        project=None,
        messages=[{"role": "user", "content": "use a fake tool"}],
        instructions="x",
    )

    assert outcome.kind == "final"
    assert outcome.response.text == "That tool does not exist."


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
