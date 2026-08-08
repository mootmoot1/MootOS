"""Deterministic natural-language commands for long-term memory writes."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MemorySaveCommand:
    """One explicit request to save content to long-term memory."""

    content: str


@dataclass(frozen=True)
class MemoryCorrectionCommand:
    """One explicit request to replace an existing long-term memory."""

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
    "remember this",
    "remember",
)

CORRECTION_SUFFIXES = (
    "remember that instead",
    "remember this instead",
    "save that instead",
    "save this instead",
    "remember it instead",
    "save it instead",
)

CORRECTION_LEAD_INS = (
    "actually",
    "correction",
)


def _strip_optional_please(message: str) -> str:
    text = message.strip()
    if text.casefold().startswith("please "):
        return text[7:].lstrip()
    return text


def _content_after_prefix(message: str, prefix: str) -> Optional[str]:
    candidate = message[: len(prefix)]
    if candidate.casefold() != prefix:
        return None

    if len(message) > len(prefix):
        boundary = message[len(prefix)]
        if not boundary.isspace() and boundary not in {":", ",", "-"}:
            return None

    content = message[len(prefix) :].lstrip(" \t\r\n:,-").strip()
    placeholder = content.casefold().strip(" \t\r\n?!.,:;-")
    if (
        not content
        or placeholder in {"this", "that"}
        or not any(character.isalnum() for character in content)
    ):
        return None
    return content


def _strip_correction_lead_in(content: str) -> str:
    text = content.strip()
    folded = text.casefold()
    for lead_in in CORRECTION_LEAD_INS:
        if not folded.startswith(lead_in):
            continue
        if len(text) == len(lead_in):
            return ""
        boundary = text[len(lead_in)]
        if boundary.isspace() or boundary in {":", ",", "-"}:
            return text[len(lead_in) :].lstrip(" \t\r\n:,-").strip()
    return text


def parse_memory_correction_command(message: str) -> Optional[MemoryCorrectionCommand]:
    """Parse explicit replace-the-old-memory requests without guessing intent."""
    text = _strip_optional_please(message).strip()
    text = text.rstrip(" \t\r\n?!.,:;-").strip()
    folded = text.casefold()

    for suffix in CORRECTION_SUFFIXES:
        if not folded.endswith(suffix):
            continue

        content = text[: -len(suffix)].rstrip(" \t\r\n?!.,:;-").strip()
        content = _strip_correction_lead_in(content)
        placeholder = content.casefold().strip(" \t\r\n?!.,:;-")
        if (
            not content
            or placeholder in {"this", "that", "it"}
            or not any(character.isalnum() for character in content)
        ):
            return None
        return MemoryCorrectionCommand(content=content)

    return None


def parse_memory_save_command(message: str) -> Optional[MemorySaveCommand]:
    """Parse clear persistent-memory writes, including explicit corrections."""
    correction = parse_memory_correction_command(message)
    if correction is not None:
        return MemorySaveCommand(content=correction.content)

    text = _strip_optional_please(message)
    for prefix in COMMAND_PREFIXES:
        content = _content_after_prefix(text, prefix)
        if content is not None:
            return MemorySaveCommand(content=content)
    return None
