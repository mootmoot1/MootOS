"""Deterministic provider-independent model-input budgeting for MootOS."""

import logging
from dataclasses import dataclass
from typing import Mapping, Sequence

from backend.conversation_guidance import build_conversation_instructions


LOGGER = logging.getLogger(__name__)

MODEL_INPUT_TOTAL_CHARACTER_BUDGET = 120_000
MODEL_INPUT_HISTORY_CHARACTER_BUDGET = 64_000
MODEL_INPUT_MEMORY_CHARACTER_BUDGET = 32_000

MEMORY_CONTEXT_HEADER = "\nRelevant long-term memory context:\n"
MEMORY_CONTEXT_FOOTER = (
    "\nUse this context only when it helps answer the current request."
)

CAPABILITY_MANIFEST = """Current MootOS capability manifest:
Available to this running application:
- Text chat using the configured model provider.
- Recent conversation history supplied as context for the current chat.
- Ranked active long-term memories supplied as context by MootOS.
- Explicit long-term-memory saves handled by MootOS storage for commands beginning with "remember" or "save this".
- User-facing memory review, correction, recoverable archive, and restore through the MootOS interface and API. The chat model does not directly click or invoke those controls.
- A small set of registered, controlled internal tools you may call directly during this conversation: projects.list, memory.search, and tasks.list run automatically and only read existing MootOS data. tasks.create is registered as a write-capable tool: calling it never creates the Task immediately, but calling it promptly when appropriate is correct and expected -- see "Calling a write-capable tool" below.
- Only the tools named above exist. You may not invent, assume, or ask MootOS to run any other tool name.

Not available to the chat model in this running version:
- Live web search, local-business lookup, or browsing.
- Email, calendar access, scheduling, reminders, or changing appointments.
- Sending messages, contacting people, or coordinating with friends.
- Reservations, purchases, payments, or ordering.
- GitHub or other repository changes, deployments, shell commands, or infrastructure operations.
- Any external tool or service not explicitly registered above.
- Background work that continues after the current response.
- A write-capable tool (such as tasks.create) actually running before Moot approves the exact frozen request in the interface.

Calling a write-capable tool (currently tasks.create):
- Calling tasks.create is how MootOS's own review step starts, not something you need to precede with your own chat confirmation. If Moot clearly asks you to create/add a Task and you already know the title, call the tasks.create tool right away in that same turn.
- Do not ask a separate question such as "should I create this task?" or "would you like me to add that?" before calling it -- that is not how MootOS's approval works, and it duplicates the real Approve/Reject control MootOS itself will show Moot next.
- Calling tasks.create does not mean the Task exists. MootOS freezes the exact call and shows Moot a real Approve/Reject control in the interface; the Task is created only if Moot approves it there.
- If information the Task genuinely needs is missing or ambiguous (most commonly, what the task actually is), ask only for that missing piece. Do not re-ask about a title, project, or due date Moot already gave you, and do not ask a blanket confirmation once you already have enough to call the tool.
- Only include a project or a due date if Moot explicitly stated one in this conversation. Never invent, assume, guess, or default a due date, and never invent a project Moot did not name. In particular, never invent a due_at value.
- If no due time was requested, omit due_at entirely from the call. Do not send "none", "null", "unknown", "N/A", an empty string, or any other placeholder in its place -- those are not valid substitutes for omitting the field and MootOS will reject them. When you do have a real due time, due_at must be an actual timezone-aware ISO 8601 datetime (for example "2026-08-10T15:00:00-04:00"), never a bare date, a time without a timezone, or free text.
- tasks.create only supports title, project, and due_at. It has no description, priority, tag, or other field -- never offer, mention, or ask about one.

Capability honesty rules:
- You may help plan, draft, explain, compare, or prepare steps for an outside action.
- Planning an action is not the same as having access to the relevant service.
- An application feature is not proof that the chat model directly invoked it.
- The existence of the Tool System is not proof that a specific tool exists; only the tools explicitly named above are registered.
- Never claim an unavailable action was started, completed, booked, sent, changed, checked, or verified.
- Never claim a write action (such as creating a Task through a tool) already happened before MootOS confirms it was approved and actually executed. Requesting a tool call is not the same as it running.
- Never imply access to private accounts, live systems, current web information, or external tools unless application code explicitly supplied that result.
- Only say long-term memory was saved when the explicit MootOS memory-write path confirmed it.
"""


class ModelInputBudgetError(RuntimeError):
    """Raised when fixed instructions plus the current request exceed the budget."""


@dataclass(frozen=True)
class ModelInputDiagnostics:
    """Privacy-safe counts describing one prepared provider request."""

    original_history_messages: int
    selected_history_messages: int
    dropped_history_messages: int
    original_memories: int
    selected_memories: int
    dropped_memories: int
    instruction_characters: int
    message_characters: int
    total_characters: int


@dataclass(frozen=True)
class PreparedModelInput:
    """Bounded provider request plus privacy-safe budgeting diagnostics."""

    messages: list[dict[str, str]]
    instructions: str
    diagnostics: ModelInputDiagnostics


def _normalize_message(message: Mapping[str, str]) -> dict[str, str]:
    return {
        "role": str(message.get("role") or ""),
        "content": str(message.get("content") or ""),
    }


def _message_character_count(message: Mapping[str, str]) -> int:
    return len(str(message.get("role") or "")) + len(
        str(message.get("content") or "")
    )


def _messages_character_count(messages: Sequence[Mapping[str, str]]) -> int:
    return sum(_message_character_count(message) for message in messages)


def _split_memory_context(instructions: str) -> tuple[str, list[str]]:
    """Separate the ranked memory block from fixed instructions.

    Memory entries are emitted in rank order by ``backend.main``. Continuation
    lines remain attached to the preceding entry so multiline memory content is
    budgeted as one ranked unit.
    """
    if MEMORY_CONTEXT_HEADER not in instructions:
        return instructions.rstrip(), []

    fixed_prefix, remainder = instructions.split(MEMORY_CONTEXT_HEADER, 1)
    if MEMORY_CONTEXT_FOOTER not in remainder:
        return instructions.rstrip(), []

    memory_text, trailing = remainder.rsplit(MEMORY_CONTEXT_FOOTER, 1)
    entries: list[str] = []
    current: list[str] = []

    for line in memory_text.splitlines():
        if line.startswith("- [") and current:
            entries.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current and any(part.strip() for part in current):
        entries.append("\n".join(current))

    fixed = fixed_prefix.rstrip()
    if trailing.strip():
        fixed += "\n" + trailing.strip()
    return fixed, entries


def _select_recent_history(
    history: Sequence[Mapping[str, str]],
    character_budget: int,
) -> list[dict[str, str]]:
    """Keep the newest contiguous history and restore chronological order."""
    selected_reversed: list[dict[str, str]] = []
    used = 0

    for message in reversed(history):
        normalized = _normalize_message(message)
        cost = _message_character_count(normalized)
        if used + cost > character_budget:
            break
        selected_reversed.append(normalized)
        used += cost

    selected_reversed.reverse()
    return selected_reversed


def _select_ranked_memories(
    entries: Sequence[str],
    character_budget: int,
) -> list[str]:
    """Keep the highest-ranked contiguous memory prefix."""
    selected: list[str] = []
    used = 0

    for entry in entries:
        cost = len(entry)
        if selected:
            cost += 1
        if used + cost > character_budget:
            break
        selected.append(entry)
        used += cost

    return selected


def _build_instructions(
    fixed_instructions: str,
    memory_entries: Sequence[str],
    messages: Sequence[Mapping[str, str]],
) -> str:
    instructions = (
        fixed_instructions.rstrip()
        + "\n\n"
        + CAPABILITY_MANIFEST.rstrip()
    )
    if memory_entries:
        instructions += (
            MEMORY_CONTEXT_HEADER
            + "\n".join(memory_entries)
            + MEMORY_CONTEXT_FOOTER
        )

    return build_conversation_instructions(
        base_instructions=instructions,
        messages=messages,
    )


def prepare_model_input(
    *,
    base_instructions: str,
    messages: Sequence[Mapping[str, str]],
    total_character_budget: int = MODEL_INPUT_TOTAL_CHARACTER_BUDGET,
    history_character_budget: int = MODEL_INPUT_HISTORY_CHARACTER_BUDGET,
    memory_character_budget: int = MODEL_INPUT_MEMORY_CHARACTER_BUDGET,
) -> PreparedModelInput:
    """Apply deterministic budgets without truncating the current request.

    ``messages`` is expected to end with the current user message. Earlier
    messages are treated as history. The current message and all fixed
    instructions remain intact. Oldest history is removed first, and ranked
    memories are removed from the lowest-ranked end.
    """
    normalized_messages = [_normalize_message(message) for message in messages]
    if normalized_messages:
        history = normalized_messages[:-1]
        current = [normalized_messages[-1]]
    else:
        history = []
        current = []

    fixed_instructions, ranked_memories = _split_memory_context(base_instructions)
    selected_history = _select_recent_history(
        history,
        max(history_character_budget, 0),
    )
    selected_memories = _select_ranked_memories(
        ranked_memories,
        max(memory_character_budget, 0),
    )

    def build() -> tuple[list[dict[str, str]], str, int, int, int]:
        prepared_messages = selected_history + current
        prepared_instructions = _build_instructions(
            fixed_instructions,
            selected_memories,
            prepared_messages,
        )
        instruction_characters = len(prepared_instructions)
        message_characters = _messages_character_count(prepared_messages)
        return (
            prepared_messages,
            prepared_instructions,
            instruction_characters,
            message_characters,
            instruction_characters + message_characters,
        )

    (
        prepared_messages,
        prepared_instructions,
        instruction_characters,
        message_characters,
        total_characters,
    ) = build()

    while total_characters > total_character_budget and selected_history:
        selected_history.pop(0)
        (
            prepared_messages,
            prepared_instructions,
            instruction_characters,
            message_characters,
            total_characters,
        ) = build()

    while total_characters > total_character_budget and selected_memories:
        selected_memories.pop()
        (
            prepared_messages,
            prepared_instructions,
            instruction_characters,
            message_characters,
            total_characters,
        ) = build()

    if total_characters > total_character_budget:
        raise ModelInputBudgetError(
            "Fixed model instructions and the current message exceed the "
            "configured character budget"
        )

    diagnostics = ModelInputDiagnostics(
        original_history_messages=len(history),
        selected_history_messages=len(selected_history),
        dropped_history_messages=len(history) - len(selected_history),
        original_memories=len(ranked_memories),
        selected_memories=len(selected_memories),
        dropped_memories=len(ranked_memories) - len(selected_memories),
        instruction_characters=instruction_characters,
        message_characters=message_characters,
        total_characters=total_characters,
    )

    if diagnostics.dropped_history_messages or diagnostics.dropped_memories:
        LOGGER.info(
            "Model input budget applied: history_kept=%d history_dropped=%d "
            "memories_kept=%d memories_dropped=%d total_characters=%d",
            diagnostics.selected_history_messages,
            diagnostics.dropped_history_messages,
            diagnostics.selected_memories,
            diagnostics.dropped_memories,
            diagnostics.total_characters,
        )

    return PreparedModelInput(
        messages=prepared_messages,
        instructions=prepared_instructions,
        diagnostics=diagnostics,
    )
