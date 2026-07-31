"""Tests for deterministic natural-language memory command parsing."""

import pytest

from backend.memory_commands import parse_memory_save_command


def test_remember_command_extracts_content():
    command = parse_memory_save_command(
        "Remember that my favorite tea is jasmine."
    )

    assert command is not None
    assert command.content == "my favorite tea is jasmine."


def test_remember_this_command_extracts_content():
    command = parse_memory_save_command(
        "Remember this: My studio opens at noon."
    )

    assert command is not None
    assert command.content == "My studio opens at noon."


def test_save_this_command_extracts_content():
    command = parse_memory_save_command(
        "Please save this to memory: Studio sessions start at noon."
    )

    assert command is not None
    assert command.content == "Studio sessions start at noon."


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Remember: The door code changed.", "The door code changed."),
        ("REMEMBER THAT the meeting starts at three.", "the meeting starts at three."),
        ("Remember- the tires are at 34 PSI.", "the tires are at 34 PSI."),
        (
            "  Please save to long-term memory: Use plain explanations.  ",
            "Use plain explanations.",
        ),
        ("Save that to memory, Call the client Friday.", "Call the client Friday."),
    ],
)
def test_supported_prefix_and_boundary_variants(message, expected):
    command = parse_memory_save_command(message)

    assert command is not None
    assert command.content == expected


def test_question_is_not_treated_as_a_save_command():
    assert parse_memory_save_command("Do you remember that studio session?") is None


def test_incomplete_command_is_not_saved():
    assert parse_memory_save_command("Remember that") is None
    assert parse_memory_save_command("Remember that?") is None
    assert parse_memory_save_command("Save this") is None


@pytest.mark.parametrize(
    "message",
    [
        "Remember that!!",
        "Remember that ...",
        "Remember that ?",
        "Save this: ???",
        "Save to memory ---",
    ],
)
def test_punctuation_only_content_is_not_saved(message):
    assert parse_memory_save_command(message) is None


def test_similar_words_do_not_trigger_memory_storage():
    assert parse_memory_save_command("Remembered details are useful.") is None
    assert parse_memory_save_command("Save money for later.") is None
