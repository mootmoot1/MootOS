"""End-to-end HTTP tests for the model-driven Tool System through /chat.

These exercise the real conversation loop (backend/tool_conversation.py)
against a fake provider that implements the tool-calling capability, wired
in exactly the way backend.main._chat expects: monkeypatching
backend.main.get_model_router, the same seam every other chat integration
test in this repository already uses.
"""

import pytest
from fastapi.testclient import TestClient

from backend.application import app
from backend.memory import DATABASE_PATH, init_db
from backend.tool_types import ToolRequest


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


class ScriptedToolRouter:
    """Mirrors backend.model_router.ModelRouter's tool-calling surface."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.provider_name = "fake"
        self.providers = {"fake": type("Provider", (), {"model": "fake-model"})()}

    def ensure_ready(self):
        return None

    def supports_tools(self):
        return True

    def generate(self, messages, instructions):
        raise AssertionError("plain generate should not run when tools are offered")

    def generate_with_tools(self, messages, instructions, tools):
        return self._next()

    def continue_tool_turn(self, state, tool_results, force_text=False, tools=None):
        return self._next()

    def _next(self):
        turn = self.script[self.calls]
        self.calls += 1
        return turn


@pytest.fixture
def clean_db():
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    init_db()
    yield
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()


@pytest.fixture
def client():
    return TestClient(app)


def test_plain_chat_without_tool_calls_still_works(clean_db, client, monkeypatch):
    router = ScriptedToolRouter([_FakeTurn("final", text="Hello there.")])
    monkeypatch.setattr("backend.main.get_model_router", lambda: router)

    response = client.post("/chat", json={"message": "Hi"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["assistant_message"]["content"] == "Hello there."
    assert "approval_required" not in data


def test_deterministic_memory_command_still_bypasses_the_model(clean_db, client, monkeypatch):
    router = ScriptedToolRouter([_FakeTurn("final", text="should not run")])
    monkeypatch.setattr("backend.main.get_model_router", lambda: router)

    response = client.post("/chat", json={"message": "Remember that the sky is blue"})

    assert response.status_code == 200
    assert router.calls == 0
    data = response.json()["data"]
    assert data["provider"] == "mootos"
    assert data["model"] == "memory-command-v1"


def test_deterministic_task_command_still_bypasses_the_model(clean_db, client, monkeypatch):
    router = ScriptedToolRouter([_FakeTurn("final", text="should not run")])
    monkeypatch.setattr("backend.main.get_model_router", lambda: router)

    response = client.post("/chat", json={"message": "Create a task to call Mike"})

    assert response.status_code == 200
    assert router.calls == 0
    data = response.json()["data"]
    assert data["task"]["title"] == "call Mike"


def test_read_only_tool_call_feeds_result_back_and_persists_conversation(clean_db, client, monkeypatch):
    router = ScriptedToolRouter(
        [
            _FakeTurn(
                "tool_calls",
                tool_requests=[ToolRequest(name="projects.list", arguments={}, call_id="c1")],
                state=_FakeState(1),
            ),
            _FakeTurn("final", text="You have several projects available."),
        ]
    )
    monkeypatch.setattr("backend.main.get_model_router", lambda: router)

    response = client.post("/chat", json={"message": "What projects do I have?"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["assistant_message"]["content"] == "You have several projects available."

    conversation = client.get(f"/conversations/{data['conversation_id']}").json()["data"]
    assert [message["role"] for message in conversation["messages"]] == ["user", "assistant"]

    activity = client.get("/activity/runs").json()["data"]
    tool_runs = [run for run in activity if run["run_type"] == "tool"]
    assert len(tool_runs) == 1
    assert tool_runs[0]["tool_name"] == "projects.list"


def test_write_tool_request_returns_approval_payload_instead_of_executing(clean_db, client, monkeypatch):
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
    monkeypatch.setattr("backend.main.get_model_router", lambda: router)

    response = client.post("/chat", json={"message": "Make me a task to call Mike"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["approval_required"] is True
    assert data["operation"]["tool_name"] == "tasks.create"
    assert data["operation"]["status"] == "pending"
    assert data["operation"]["arguments"] == {"title": "Call Mike"}

    assert client.get("/tasks").json()["data"] == []


def test_approving_the_pending_operation_creates_exactly_one_task(clean_db, client, monkeypatch):
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
    monkeypatch.setattr("backend.main.get_model_router", lambda: router)

    chat_response = client.post("/chat", json={"message": "Make me a task to call Mike"})
    operation_id = chat_response.json()["data"]["operation"]["id"]

    approve_response = client.post(f"/tool-operations/{operation_id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["data"]["status"] == "succeeded"

    tasks = client.get("/tasks").json()["data"]
    assert [task["title"] for task in tasks] == ["Call Mike"]

    duplicate = client.post(f"/tool-operations/{operation_id}/approve")
    assert duplicate.status_code == 409
    assert client.get("/tasks").json()["data"] == tasks


def test_rejecting_the_pending_operation_creates_no_task(clean_db, client, monkeypatch):
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
    monkeypatch.setattr("backend.main.get_model_router", lambda: router)

    chat_response = client.post("/chat", json={"message": "Make me a task to call Mike"})
    operation_id = chat_response.json()["data"]["operation"]["id"]

    reject_response = client.post(f"/tool-operations/{operation_id}/reject")
    assert reject_response.status_code == 200
    assert reject_response.json()["data"]["status"] == "rejected"
    assert client.get("/tasks").json()["data"] == []


def test_multi_read_tool_loop_stays_bounded_over_http(clean_db, client, monkeypatch):
    turns = []
    for index in range(3):
        turns.append(
            _FakeTurn(
                "tool_calls",
                tool_requests=[
                    ToolRequest(name="memory.search", arguments={"query": f"topic-{index}"}, call_id=f"c{index}")
                ],
                state=_FakeState(index),
            )
        )
    turns.append(_FakeTurn("final", text="Here is what I found."))
    router = ScriptedToolRouter(turns)
    monkeypatch.setattr("backend.main.get_model_router", lambda: router)

    response = client.post("/chat", json={"message": "search for a few things"})

    assert response.status_code == 200
    assert response.json()["data"]["assistant_message"]["content"] == "Here is what I found."
    tool_runs = [run for run in client.get("/activity/runs").json()["data"] if run["run_type"] == "tool"]
    assert len(tool_runs) == 3
