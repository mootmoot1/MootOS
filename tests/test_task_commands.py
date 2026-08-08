"""Tests for deterministic create-task chat commands."""

import pytest

from backend.task_commands import parse_task_create_command


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Create a task to call Mike", "call Mike"),
        ("create task to finish the mix", "finish the mix"),
        ("Add a task: upload the reel", "upload the reel"),
        ("Add task: export stems", "export stems"),
        ("Please add task to check the car", "check the car"),
        ("Please create task: send invoice", "send invoice"),
    ],
)
def test_parse_explicit_task_create_commands(message, expected):
    command = parse_task_create_command(message)
    assert command is not None
    assert command.title == expected


@pytest.mark.parametrize(
    "message",
    [
        "I need to create a task system someday",
        "Can you help me create a task?",
        "Remind me to call Mike tomorrow",
        "What tasks do I have?",
        "create a task",
        "add task: ---",
        "Create a task system for tracking clients",
        "Create a task manager",
        "Create task list for the dashboard",
        "Add task list to the sidebar",
        "Add a task manager to MootOS",
        "Please create a task system for me",
    ],
)
def test_parser_leaves_ordinary_or_incomplete_chat_alone(message):
    assert parse_task_create_command(message) is None
