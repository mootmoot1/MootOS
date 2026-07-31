"""Deterministic natural-language commands for long-term memory writes."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MemorySaveCommand:
    """One explicit request to save content to long-term memory."""

    content: str


COMMAND_PREFIXES = (
    "save this to long-term memory",
    "save that to long-term memory",
    "save this to long term memory",
    "save that to long term memory",
    "save this to memory",
    "save that to memory",
    "save to long-term memory",
    "save to long term memory",
    "save to memory",
    "save this",
    "save that",
    "remember that",
    "remember",
)


def _strip_optional_please(message: str) -> str:
    text = message.strip()
    if text.casefold().startswith("please "):
        return text[7:].lstrip()
    return text


def _content_after_prefix(message: str, prefix: str) -> Optional[str]:
    lowered = message.casefold()
    if not lowered.startswith(prefix):
        return None

    if len(message) > len(prefix):
        boundary = message[len(prefix)]
        if not boundary.isspace() and boundary not in {":", ",", "-"}:
            return None

    content = message[len(prefix) :].lstrip(" \t\r\n:,-")
    if not content or content.casefold() in {"this", "that"}:
        return None
    return content.strip()


def parse_memory_save_command(message: str) -> Optional[MemorySaveCommand]:
    """Parse only clear imperative save commands, never ordinary questions."""
    text = _strip_optional_please(message)
    for prefix in COMMAND_PREFIXES:
        content = _content_after_prefix(text, prefix)
        if content is not None:
            return MemorySaveCommand(content=content)
    return None
