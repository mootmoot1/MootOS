"""Tests for deterministic long-term-memory correction commands."""

from backend.memory_commands import (
    parse_memory_correction_command,
    parse_memory_save_command,
)


def test_correction_command_extracts_replacement_content():
    message = "Actually, my test phrase is blue turbo 92. Remember that instead."

    correction = parse_memory_correction_command(message)

    assert correction is not None
    assert correction.content == "my test phrase is blue turbo 92"


def test_correction_is_routed_through_persistent_memory_handling():
    message = "Actually, my favorite compressor is the 1176. Remember that instead."

    command = parse_memory_save_command(message)

    assert command is not None
    assert command.content == "my favorite compressor is the 1176"


def test_plain_correction_without_persistent_directive_is_not_intercepted():
    message = "Actually, my test phrase is blue turbo 92."

    assert parse_memory_correction_command(message) is None
    assert parse_memory_save_command(message) is None
