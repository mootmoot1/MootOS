"""Regression tests for bounded model input and capability honesty."""

from copy import deepcopy

import pytest

from backend.capability_catalog import render_capability_manifest
from backend.model_input import (
    MEMORY_CONTEXT_FOOTER,
    MEMORY_CONTEXT_HEADER,
    MODEL_INPUT_TOTAL_CHARACTER_BUDGET,
    ModelInputBudgetError,
    prepare_model_input,
)
from backend.model_router import ModelProviderError, ModelResponse, ModelRouter


# The manifest is generated fresh from the live default registry on every
# call (backend/capability_catalog.py, ADR-029) -- these tests exercise
# that real, production default-registry output. Dynamic add/remove and
# hallucination-prevention behavior is covered against isolated test
# registries in tests/test_capability_catalog.py, not here.
CAPABILITY_MANIFEST = render_capability_manifest()


class CapturingProvider:
    """Provider double that records the bounded request."""

    name = "capture"
    model = "capture-model"

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []
        self.instructions = ""

    def ensure_ready(self) -> None:
        return None

    def generate(
        self,
        messages: list[dict[str, str]],
        instructions: str,
    ) -> ModelResponse:
        self.messages = deepcopy(messages)
        self.instructions = instructions
        return ModelResponse(
            text="captured",
            provider=self.name,
            model=self.model,
        )


def _message_cost(message: dict[str, str]) -> int:
    return len(message["role"]) + len(message["content"])


def _instructions_with_memories(*entries: str) -> str:
    return (
        "Base identity"
        + MEMORY_CONTEXT_HEADER
        + "\n".join(entries)
        + MEMORY_CONTEXT_FOOTER
    )


def test_capability_manifest_is_explicit_about_available_and_unavailable_actions():
    assert "Text chat using the configured model provider" in CAPABILITY_MANIFEST
    assert "Explicit long-term-memory saves" in CAPABILITY_MANIFEST
    assert "Live web search" in CAPABILITY_MANIFEST
    assert "Sending messages" in CAPABILITY_MANIFEST
    assert "Reservations, purchases" in CAPABILITY_MANIFEST
    assert "Email, calendar access" in CAPABILITY_MANIFEST
    assert "GitHub or other repository changes" in CAPABILITY_MANIFEST
    assert "Background work" in CAPABILITY_MANIFEST
    assert "Planning an action is not the same as having access" in CAPABILITY_MANIFEST
    assert "chat model does not directly click or invoke" in CAPABILITY_MANIFEST


def test_capability_manifest_names_exactly_the_registered_v03a_tools():
    """V0.3A: MootOS may truthfully claim only the tools actually
    registered, and the claim is generated from the live registry, not a
    hand-maintained list -- see tests/test_capability_catalog.py for the
    dynamic add/remove/hallucination-prevention proof of that."""
    # Read-only tools are named in sorted order by the generator; V0.3C
    # added self.architecture/self.state (and web.search when configured),
    # V0.3E added tasks.status_summary (proof #1) and projects.overview
    # (proof #2). This assertion is deliberately the exact generated
    # sequence: a tool silently added to or dropped from the registry
    # changes this string, which is the drift protection ADR-029 exists
    # for.
    assert (
        "memory.search, projects.list, projects.overview, self.architecture, "
        "self.state, tasks.list, and tasks.status_summary"
    ) in CAPABILITY_MANIFEST
    assert "run automatically and only read existing MootOS data" in CAPABILITY_MANIFEST
    assert "tasks.create is registered as a write-capable tool" in CAPABILITY_MANIFEST
    assert "You may not invent, assume, or ask MootOS to run any other tool name" in CAPABILITY_MANIFEST
    assert "Never claim a write action" in CAPABILITY_MANIFEST


def test_capability_manifest_generic_write_tool_guidance_is_present():
    """Live-testing regression, generalized to any internal_write tool: the
    model must call a write-capable tool as soon as the request is clear,
    not ask its own chat confirmation question first -- the Tool System's
    own approval UI is what reviews the request."""
    assert (
        "Calling a write-capable tool is how MootOS's own review step starts"
        in CAPABILITY_MANIFEST
    )
    assert 'Do not ask your own confirmation question (such as "should I do this?"' in CAPABILITY_MANIFEST
    assert "ask only for that missing piece" in CAPABILITY_MANIFEST
    assert "do not ask a blanket confirmation once enough information is already available" in CAPABILITY_MANIFEST


def test_capability_manifest_embeds_each_write_tools_own_description_verbatim():
    """The manifest never re-authors a write tool's argument-level rules --
    it quotes the tool's own registered ``description`` (the same text
    already sent to the provider as the function-tool schema), so there is
    exactly one place that text is written, not two independently
    maintained copies."""
    from backend.tool_registry import get_tool_registry

    description = get_tool_registry().get("tasks.create").description
    assert description in CAPABILITY_MANIFEST
    # Spot-check a few of the argument-specific rules live inside that
    # embedded description, not as a second, separately authored copy:
    assert "never invent, guess, or default a due date" in description
    assert "omit due_at entirely from the call" in description
    assert '"none", "null", "unknown", "N/A"' in description
    assert "No other fields exist (no description, priority, or tags)" in description


def test_conversation_guidance_does_not_conflict_with_immediate_tool_calling():
    """The general "ask before an outside action" rule must not read as
    telling the model to ask a confirmation question before calling a
    registered tool -- that conflict was the root cause of the live bug."""
    from backend.conversation_guidance import CONVERSATION_RULES

    assert "Calling a registered internal tool is not an unreviewed outside action" in CONVERSATION_RULES


def test_history_budget_drops_oldest_and_preserves_current_message_fully():
    oldest = {"role": "user", "content": "oldest-" + ("a" * 40)}
    middle = {"role": "assistant", "content": "middle-" + ("b" * 40)}
    newest = {"role": "user", "content": "newest-" + ("c" * 40)}
    current = {"role": "user", "content": "current-" + ("d" * 200)}
    history_budget = _message_cost(middle) + _message_cost(newest)

    prepared = prepare_model_input(
        base_instructions="Base identity",
        messages=[oldest, middle, newest, current],
        history_character_budget=history_budget,
    )

    assert prepared.messages == [middle, newest, current]
    assert prepared.messages[-1]["content"] == current["content"]
    assert prepared.diagnostics.dropped_history_messages == 1
    assert prepared.diagnostics.selected_history_messages == 2


def test_memory_budget_keeps_highest_ranked_prefix_and_drops_lowest_ranked():
    first = "- [MootOS / decision] highest-ranked-" + ("a" * 40)
    second = "- [Global / preference] second-ranked-" + ("b" * 40)
    third = "- [Cars / detail] lowest-ranked-" + ("c" * 40)
    budget = len(first) + 1 + len(second)

    prepared = prepare_model_input(
        base_instructions=_instructions_with_memories(first, second, third),
        messages=[{"role": "user", "content": "What matters?"}],
        memory_character_budget=budget,
    )

    assert first in prepared.instructions
    assert second in prepared.instructions
    assert third not in prepared.instructions
    assert prepared.diagnostics.selected_memories == 2
    assert prepared.diagnostics.dropped_memories == 1


def test_multiline_memory_continuation_stays_with_its_ranked_entry():
    first = (
        "- [MootOS / note] first line"
        "\ncontinuation line"
        "\nthird line"
    )
    second = "- [Global / note] lower-ranked entry"

    prepared = prepare_model_input(
        base_instructions=_instructions_with_memories(first, second),
        messages=[{"role": "user", "content": "Use the best memory."}],
        memory_character_budget=len(first),
    )

    assert first in prepared.instructions
    assert second not in prepared.instructions
    assert prepared.diagnostics.selected_memories == 1
    assert prepared.diagnostics.dropped_memories == 1


def test_total_budget_removes_old_history_before_ranked_memory():
    current = {"role": "user", "content": "current request"}
    memory = "- [Global / preference] preserve this ranked memory"
    memory_only = prepare_model_input(
        base_instructions=_instructions_with_memories(memory),
        messages=[current],
    )
    history = [
        {"role": "user", "content": "old history " + ("x" * 300)},
        {"role": "assistant", "content": "newer history " + ("y" * 300)},
    ]

    prepared = prepare_model_input(
        base_instructions=_instructions_with_memories(memory),
        messages=history + [current],
        total_character_budget=memory_only.diagnostics.total_characters,
        history_character_budget=10_000,
        memory_character_budget=10_000,
    )

    assert prepared.messages == [current]
    assert memory in prepared.instructions
    assert prepared.diagnostics.dropped_history_messages == 2
    assert prepared.diagnostics.dropped_memories == 0


def test_fixed_identity_capabilities_and_conversation_rules_are_never_truncated():
    current = {"role": "user", "content": "z" * 20_000}
    prepared = prepare_model_input(
        base_instructions="Fixed identity marker",
        messages=[current],
    )

    assert prepared.messages[-1]["content"] == current["content"]
    assert "Fixed identity marker" in prepared.instructions
    assert "Current MootOS capability manifest" in prepared.instructions
    assert "Conversation handling rules" in prepared.instructions
    assert (
        prepared.diagnostics.total_characters
        <= MODEL_INPUT_TOTAL_CHARACTER_BUDGET
    )


def test_privacy_safe_budget_log_contains_counts_not_message_or_memory_content(
    caplog,
):
    history_secret = "PRIVATE-HISTORY-SECRET"
    memory_secret = "PRIVATE-MEMORY-SECRET"
    current = {"role": "user", "content": "current"}

    with caplog.at_level("INFO", logger="backend.model_input"):
        prepare_model_input(
            base_instructions=_instructions_with_memories(
                "- [Global / test] " + memory_secret
            ),
            messages=[
                {"role": "user", "content": history_secret},
                current,
            ],
            history_character_budget=0,
            memory_character_budget=0,
        )

    assert "history_dropped=1" in caplog.text
    assert "memories_dropped=1" in caplog.text
    assert history_secret not in caplog.text
    assert memory_secret not in caplog.text


def test_router_sends_bounded_messages_and_fixed_manifest_to_provider():
    provider = CapturingProvider()
    router = ModelRouter()
    router.provider_name = provider.name
    router.providers = {provider.name: provider}
    messages = [
        {"role": "user", "content": "Give me two options."},
        {"role": "assistant", "content": "One and two."},
        {"role": "user", "content": "Do the second one."},
    ]

    response = router.generate(messages=messages, instructions="Base identity")

    assert response.text == "captured"
    assert provider.messages == messages
    assert "Current MootOS capability manifest" in provider.instructions
    assert "earlier messages are supplied" in provider.instructions
    assert router.last_input_diagnostics is not None
    assert router.last_input_diagnostics.dropped_history_messages == 0


def test_budget_error_does_not_truncate_fixed_core_or_current_request():
    with pytest.raises(ModelInputBudgetError):
        prepare_model_input(
            base_instructions="Fixed identity",
            messages=[{"role": "user", "content": "current request"}],
            total_character_budget=10,
        )


def test_router_sanitizes_fail_closed_budget_errors(monkeypatch):
    provider = CapturingProvider()
    router = ModelRouter()
    router.provider_name = provider.name
    router.providers = {provider.name: provider}

    def fail_budget(**kwargs):
        raise ModelInputBudgetError("PRIVATE-INPUT-CONTENT")

    monkeypatch.setattr("backend.model_router.prepare_model_input", fail_budget)

    with pytest.raises(ModelProviderError) as captured:
        router.generate(
            messages=[{"role": "user", "content": "private request"}],
            instructions="Base identity",
        )

    assert str(captured.value) == "Model input preparation failed"
    assert "PRIVATE-INPUT-CONTENT" not in str(captured.value)
    assert provider.messages == []
