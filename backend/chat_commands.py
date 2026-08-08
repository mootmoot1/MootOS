"""Ordered deterministic command parsing for the MootOS chat endpoint."""

from dataclasses import dataclass
from typing import Any, Optional

from backend.memory_commands import parse_memory_save_command
from backend.task_commands import parse_task_create_command


COMMAND_MEMORY = "memory"
COMMAND_TASK = "task"


@dataclass(frozen=True)
class ParsedChatCommand:
    """One deterministic chat command selected before model-backed conversation."""

    kind: str
    command: Any


def parse_deterministic_chat_command(message: str) -> Optional[ParsedChatCommand]:
    """Return the first supported deterministic command in explicit priority order."""
    memory_command = parse_memory_save_command(message)
    if memory_command is not None:
        return ParsedChatCommand(kind=COMMAND_MEMORY, command=memory_command)

    task_command = parse_task_create_command(message)
    if task_command is not None:
        return ParsedChatCommand(kind=COMMAND_TASK, command=task_command)

    return None
