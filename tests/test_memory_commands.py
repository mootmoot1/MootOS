"""Tests for deterministic natural-language memory command parsing."""

from backend.memory_commands import parse_memory_save_command


def test_remember_command_extracts_content():
    command = parse_memory_save_command(
        "Remember that my favorite tea is jasmine."
    )

    assert command is not None
    assert command.content == "my favorite tea is jasmine."


def test_save_this_command_extracts_content():
    command = parse_memory_save_command(
        "Please save this to memory: Studio sessions start at noon."
    )

    assert command is not None
    assert command.content == "Studio sessions start at noon."


def test_question_is_not_treated_as_a_save_command():
    assert parse_memory_save_command("Do you remember that studio session?") is None


def test_incomplete_command_is_not_saved():
    assert parse_memory_save_command("Remember that") is None
    assert parse_memory_save_command("Save this") is None


def test_similar_words_do_not_trigger_memory_storage():
    assert parse_memory_save_command("Remembered details are useful.") is None
    assert parse_memory_save_command("Save money for later.") is None
