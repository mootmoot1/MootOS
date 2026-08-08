"""Unit tests for ordered deterministic chat-command dispatch."""

from backend.chat_commands import (
    COMMAND_MEMORY,
    COMMAND_TASK,
    parse_deterministic_chat_command,
)


def test_memory_command_is_selected_by_unified_dispatch():
    parsed = parse_deterministic_chat_command("Remember that the interface is black")

    assert parsed is not None
    assert parsed.kind == COMMAND_MEMORY
    assert parsed.command.content == "the interface is black"


def test_task_command_is_selected_by_unified_dispatch():
    parsed = parse_deterministic_chat_command("Create a task to call Mike")

    assert parsed is not None
    assert parsed.kind == COMMAND_TASK
    assert parsed.command.title == "call Mike"


def test_reminder_language_is_not_intercepted_yet():
    assert (
        parse_deterministic_chat_command("Remind me to call Mike tomorrow at 3")
        is None
    )


def test_ordinary_taskish_chat_is_not_intercepted():
    assert parse_deterministic_chat_command("Create a task manager") is None
