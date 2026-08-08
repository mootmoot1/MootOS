"""Deterministic natural-language commands for creating MootOS Tasks from chat."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TaskCreateCommand:
    """One explicit request to create a Task."""

    title: str


TASK_PREFIXES = (
    "create a task to",
    "create task to",
    "add a task to",
    "add task to",
    "create a task",
    "create task",
    "add a task",
    "add task",
)


def _strip_optional_please(message: str) -> str:
    text = message.strip()
    if text.casefold().startswith("please "):
        return text[7:].lstrip()
    return text


def _title_after_prefix(message: str, prefix: str) -> Optional[str]:
    candidate = message[: len(prefix)]
    if candidate.casefold() != prefix:
        return None

    if len(message) > len(prefix):
        boundary = message[len(prefix)]
        if not boundary.isspace() and boundary not in {":", ",", "-"}:
            return None

    title = message[len(prefix) :].lstrip(" \t\r\n:,-").strip()
    if not title or not any(character.isalnum() for character in title):
        return None
    return title


def parse_task_create_command(message: str) -> Optional[TaskCreateCommand]:
    """Parse only explicit create/add-task commands; ordinary chat is untouched."""
    text = _strip_optional_please(message)
    for prefix in TASK_PREFIXES:
        title = _title_after_prefix(text, prefix)
        if title is not None:
            return TaskCreateCommand(title=title)
    return None
