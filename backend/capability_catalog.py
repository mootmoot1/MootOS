"""Generated capability catalog and model-facing manifest (V0.3A).

Everything in this module is a **read-only, derived view** over the live
Tool Registry (``backend/tool_registry.py``). Nothing here stores, executes,
authorizes, or approves anything -- it only ever reads already-registered
``ToolDefinition`` objects and reshapes them for description purposes. See
``docs/CAPABILITY_ARCHITECTURE.md`` and ADR-028/ADR-029.

Two non-negotiable rules this module exists to enforce, in code:

1. **A capability is never a second executable registry.** ``build_capability_
   index`` groups tool *names* by their declared ``capabilities`` reference;
   it never stores an executor, and a capability id can never be passed to
   ``backend.tool_executor.execute_tool`` -- only a real, registered tool
   name can (``ToolRegistry.get`` fails closed on anything else, capability
   ids included).

2. **The model-facing capability manifest is generated, not hand-maintained.**
   ``render_capability_manifest`` replaces the previously hand-authored
   ``CAPABILITY_MANIFEST`` prose constant (ADR-022) with text built entirely
   from ``registry.list_definitions()`` at call time. A tool that is not
   registered cannot be named as available here, and a tool that *is*
   registered cannot be silently missing -- there is no second, independent
   list that could drift from the registry (ADR-029).

This module knows nothing about self-inspection (source paths, version/
commit, docs) or gap reasoning (goals, missing capabilities) -- both are
explicitly out of scope for V0.3A; see ``docs/CAPABILITY_ARCHITECTURE.md``
Sec6 (V0.3B, V0.3C).
"""

from typing import Any, Optional, Sequence

from backend.tool_registry import ToolRegistry, get_tool_registry
from backend.tool_types import RISK_INTERNAL_WRITE, RISK_READ_ONLY


# Cosmetic phrasing only -- never an authority on whether a capability
# "exists". A capability id that no registered tool references never
# appears in build_capability_index's output regardless of whether it has
# an entry here, and a capability id with no label below still appears
# (under an auto-generated label) if a registered tool does reference it.
CAPABILITY_LABELS: dict[str, str] = {
    "projects.view": "View MootOS projects",
    "memory.recall": "Search saved long-term memory",
    "tasks.manage": "View and create MootOS Tasks",
    "self.inspect": "Inspect MootOS's own architecture and current capability state",
    "web.current_information": "Search the public web for current information",
}


def _default_label(capability_id: str) -> str:
    """Fallback cosmetic label for a capability id with no entry above."""
    words = capability_id.replace(".", " ").replace("_", " ").split()
    return " ".join(words).capitalize() if words else capability_id


def _join_names(names: Sequence[str]) -> str:
    """Oxford-comma-joined names: "a", "a and b", or "a, b, and c"."""
    ordered = list(names)
    if not ordered:
        return ""
    if len(ordered) == 1:
        return ordered[0]
    if len(ordered) == 2:
        return f"{ordered[0]} and {ordered[1]}"
    return ", ".join(ordered[:-1]) + f", and {ordered[-1]}"


def build_tool_catalog(registry: Optional[ToolRegistry] = None) -> list[dict[str, Any]]:
    """Return the full, safe, JSON-serializable tool catalog.

    Identical to ``registry.catalog()`` -- kept as a stable, documented
    capability-layer entry point so callers describing installed abilities
    never need to import ``ToolRegistry`` directly.
    """
    active_registry = registry if registry is not None else get_tool_registry()
    return active_registry.catalog()


def build_capability_index(registry: Optional[ToolRegistry] = None) -> list[dict[str, Any]]:
    """Group registered tools by their declared capability references.

    Returns one entry per capability id that at least one registered tool
    actually declares, sorted by id, each shaped as::

        {"id": "tasks.manage", "label": "View and create MootOS Tasks",
         "tools": ["tasks.create", "tasks.list"]}

    A capability with zero backing tools simply does not appear -- this
    function never invents an entry for a capability id that isn't actually
    referenced by a registered ``ToolDefinition``. Entries contain no
    executor and cannot be used to execute anything (see module docstring).
    """
    active_registry = registry if registry is not None else get_tool_registry()
    grouped: dict[str, list[str]] = {}
    for definition in active_registry.list_definitions():
        for capability_id in definition.capabilities:
            grouped.setdefault(capability_id, []).append(definition.name)

    return [
        {
            "id": capability_id,
            "label": CAPABILITY_LABELS.get(capability_id, _default_label(capability_id)),
            "tools": sorted(tool_names),
        }
        for capability_id, tool_names in sorted(grouped.items())
    ]


def describe_installed_abilities(registry: Optional[ToolRegistry] = None) -> dict[str, Any]:
    """The full, structured, read-only answer to "what can you currently do?"

    Entirely derived from the live Tool Registry. Contains only tool/
    capability metadata (name, version, risk, description, side effects,
    idempotency, limitations, dependencies, capability grouping) -- never
    tool arguments, prompt/response content, secrets, or private user data.
    """
    active_registry = registry if registry is not None else get_tool_registry()
    return {
        "tools": build_tool_catalog(active_registry),
        "capabilities": build_capability_index(active_registry),
    }


def render_capability_manifest(registry: Optional[ToolRegistry] = None) -> str:
    """Build the model-facing capability manifest text from the live registry.

    Replaces the previously hand-maintained ``CAPABILITY_MANIFEST`` prose
    constant (ADR-022). A tool can only be named as "available" here if it
    is actually registered; nothing here can claim a tool exists that the
    registry does not have. High-risk tools (``RISK_HIGH_RISK``) are never
    described as available or callable, matching
    ``backend.tool_executor``'s unconditional block on that risk tier --
    none exist in V0.2A/V0.3A, but this holds if one is ever registered.
    """
    active_registry = registry if registry is not None else get_tool_registry()
    definitions = active_registry.list_definitions()

    read_only_names = sorted(d.name for d in definitions if d.risk == RISK_READ_ONLY)
    write_definitions = sorted(
        (d for d in definitions if d.risk == RISK_INTERNAL_WRITE),
        key=lambda d: d.name,
    )

    lines: list[str] = [
        "Current MootOS capability manifest:",
        "Available to this running application:",
        "- Text chat using the configured model provider.",
        "- Recent conversation history supplied as context for the current chat.",
        "- Ranked active long-term memories supplied as context by MootOS.",
        (
            "- Explicit long-term-memory saves handled by MootOS storage for "
            'commands beginning with "remember" or "save this".'
        ),
        (
            "- User-facing memory review, correction, recoverable archive, and "
            "restore through the MootOS interface and API. The chat model does "
            "not directly click or invoke those controls."
        ),
    ]

    if read_only_names:
        lines.append(
            "- A small set of registered, controlled internal tools you may "
            f"call directly during this conversation: {_join_names(read_only_names)} "
            "run automatically and only read existing MootOS data."
        )
    for definition in write_definitions:
        lines.append(
            f"- {definition.name} is registered as a write-capable tool: calling "
            "it never performs the write immediately, but calling it promptly "
            'when appropriate is correct and expected -- see "Calling a '
            'write-capable tool" below.'
        )
    if not read_only_names and not write_definitions:
        lines.append("- No internal tools are currently registered.")

    lines.append(
        "- Only the tools named above exist. You may not invent, assume, or "
        "ask MootOS to run any other tool name."
    )

    lines.extend(
        [
            "",
            "Not available to the chat model in this running version:",
            "- Live web search, local-business lookup, or browsing.",
            "- Email, calendar access, scheduling, reminders, or changing appointments.",
            "- Sending messages, contacting people, or coordinating with friends.",
            "- Reservations, purchases, payments, or ordering.",
            (
                "- GitHub or other repository changes, deployments, shell "
                "commands, or infrastructure operations."
            ),
            "- Any external tool or service not explicitly registered above.",
            "- Background work that continues after the current response.",
            (
                "- A write-capable tool actually running before Moot approves "
                "the exact frozen request in the interface."
            ),
        ]
    )

    if write_definitions:
        lines.extend(
            [
                "",
                "Calling a write-capable tool:",
                (
                    "- Calling a write-capable tool is how MootOS's own review "
                    "step starts, not something you need to precede with your "
                    "own chat confirmation."
                ),
                (
                    '- Do not ask your own confirmation question (such as "should '
                    'I do this?" or "would you like me to?") before calling it -- '
                    "MootOS's own Approve/Reject control is the review step, and "
                    "a separate confirmation question duplicates it instead of "
                    "helping."
                ),
                (
                    "- If information a write-capable tool genuinely needs is "
                    "missing or ambiguous, ask only for that missing piece -- do "
                    "not re-ask for something already given, and do not ask a "
                    "blanket confirmation once enough information is already "
                    "available to call the tool."
                ),
                (
                    "- Each write-capable tool's own description below is the "
                    "single, authoritative source for its exact argument rules; "
                    "MootOS does not maintain a second, separate copy of that "
                    "guidance."
                ),
            ]
        )
        for definition in write_definitions:
            lines.append(f"  - {definition.name}: {definition.description}")

    lines.extend(
        [
            "",
            "Capability honesty rules:",
            "- You may help plan, draft, explain, compare, or prepare steps for an outside action.",
            "- Planning an action is not the same as having access to the relevant service.",
            "- An application feature is not proof that the chat model directly invoked it.",
            (
                "- The existence of the Tool System is not proof that a specific "
                "tool exists; only the tools explicitly named above are registered."
            ),
            (
                "- Never claim an unavailable action was started, completed, "
                "booked, sent, changed, checked, or verified."
            ),
            (
                "- Never claim a write action already happened before MootOS "
                "confirms it was approved and actually executed. Requesting a "
                "tool call is not the same as it running."
            ),
            (
                "- Never imply access to private accounts, live systems, current "
                "web information, or external tools unless application code "
                "explicitly supplied that result."
            ),
            (
                "- Only say long-term memory was saved when the explicit MootOS "
                "memory-write path confirmed it."
            ),
        ]
    )

    return "\n".join(lines) + "\n"
