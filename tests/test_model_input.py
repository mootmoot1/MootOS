"""Regression tests for bounded model input and capability honesty."""

from copy import deepcopy

import pytest

from backend.model_input import (
    CAPABILITY_MANIFEST,
    MEMORY_CONTEXT_FOOTER,
    MEMORY_CONTEXT_HEADER,
    ModelInputBudgetError,
    prepare_model_input,
)
from backend.model_router import ModelResponse, ModelRouter


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
    assert "Calendar access" in CAPABILITY_MANIFEST
    assert "Deployments, repository changes" in CAPABILITY_MANIFEST
    assert "Background work" in CAPABILITY_MANIFEST
    assert "Planning an action is not the same as having access" in CAPABILITY_MANIFEST


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
    assert prepared.diagnostics.total_characters <= 120_000


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
