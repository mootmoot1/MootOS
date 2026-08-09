"""V0.3B — Structured Gap Reasoning for MootOS.

Turns a natural-language goal into a structured, auditable Gap Report by
strictly separating two stages (docs/CAPABILITY_ARCHITECTURE.md Sec6
V0.3B, ADR-030):

    goal (natural language)
      -> model interpretation                              [non-deterministic]
      -> structured proposed capability requirements
      -> deterministic resolution against the live V0.3A
         capability index (backend/capability_catalog.py)   [deterministic]
      -> GapReport

The model may only ever *propose* what a goal appears to need, in a small,
strictly validated JSON shape. It never decides whether a proposed
capability is actually installed -- that is resolved here, deterministically,
by looking the proposed capability id up in
``backend.capability_catalog.build_capability_index``. A capability the
model invents that the registry does not back always resolves to
"missing" (or, if the model itself flags it, "externally_blocked"). It can
never become "installed" by merely being proposed, and nothing in this
module executes a tool, registers a capability, or installs anything --
see ``backend/tool_executor.py`` for the only code path allowed to execute
a registered tool.

Out of scope for V0.3B (see docs/CAPABILITY_ARCHITECTURE.md Sec6): web
search, repository self-inspection, protected-core gates, capability
building, the local node, the Codex bridge, and workflow persistence. This
module produces a Gap Report and nothing more.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from backend.capability_catalog import build_capability_index
from backend.model_router import ModelProviderError, ModelResponse, ModelRouter
from backend.runs import (
    DATA_EXPOSURE_MODEL_PROVIDER,
    finish_model_run_failure,
    finish_model_run_success,
    start_model_run,
)
from backend.tool_registry import ToolRegistry, get_tool_registry


# --- Classification outcomes ------------------------------------------------

CLASSIFICATION_ALREADY_POSSIBLE = "already_possible"
CLASSIFICATION_COMPOSABLE = "composable"
CLASSIFICATION_CAPABILITY_GAP = "capability_gap"
CLASSIFICATION_EXTERNALLY_BLOCKED = "externally_blocked"
VALID_CLASSIFICATIONS = {
    CLASSIFICATION_ALREADY_POSSIBLE,
    CLASSIFICATION_COMPOSABLE,
    CLASSIFICATION_CAPABILITY_GAP,
    CLASSIFICATION_EXTERNALLY_BLOCKED,
}

# --- Limits / strict validation ---------------------------------------------

GOAL_MAX_CHARACTERS = 2000
MAX_REQUIREMENTS = 10
CAPABILITY_ID_MAX_CHARACTERS = 100
REASON_MAX_CHARACTERS = 300
_REQUIREMENT_ALLOWED_KEYS = {"capability", "reason", "externally_blocked"}
# Dotted, lowercase, letter-led segments -- matches every real capability id
# (tasks.manage, memory.recall, projects.view) and every plausible invented
# one (instagram.manage_messages, cloud.archive_dropbox) without accepting
# a full sentence or arbitrary text as a "capability".
_CAPABILITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class GapAnalysisError(RuntimeError):
    """Raised whenever a goal cannot be turned into a Gap Report: an empty/
    invalid goal, a model-provider failure, or model output that does not
    match the required strict JSON shape. Always a safe, generic message --
    never the raw model text. Callers must not construct or use a
    ``GapReport`` when this is raised; there is no partial/fallback report.
    """


@dataclass(frozen=True)
class RequirementResolution:
    """One proposed capability requirement, with model interpretation and
    deterministic verification kept as clearly separate fields.

    ``reason`` and ``externally_blocked`` are the model's interpretation --
    advisory, never authoritative. ``installed`` and ``tools`` are resolved
    deterministically from the live Tool Registry and can never be set by
    the model.
    """

    capability: str
    reason: str
    externally_blocked: bool
    installed: bool
    tools: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "reason": self.reason,
            "externally_blocked": self.externally_blocked,
            "installed": self.installed,
            "tools": list(self.tools),
        }


@dataclass(frozen=True)
class GapReport:
    """The complete, structured, auditable result of one gap analysis.

    Advisory only (ADR-030): nothing on this object can execute a tool,
    register a capability, or install anything. ``requirements`` is the
    model's interpretation (reason/externally_blocked) merged with
    deterministic verification (installed/tools) per item; every other
    field is computed here, deterministically, from ``requirements``.
    """

    goal: str
    requirements: tuple[RequirementResolution, ...]
    available_capabilities: tuple[str, ...]
    composable_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    externally_blocked_capabilities: tuple[str, ...]
    classification: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "requirements": [item.to_dict() for item in self.requirements],
            "available_capabilities": list(self.available_capabilities),
            "composable_capabilities": list(self.composable_capabilities),
            "missing_capabilities": list(self.missing_capabilities),
            "externally_blocked_capabilities": list(self.externally_blocked_capabilities),
            "classification": self.classification,
            "notes": self.notes,
        }


# --- Model-facing contract ---------------------------------------------------

_INSTRUCTIONS_TEMPLATE = """You are MootOS's capability-gap analysis assistant.

Task: read the user's stated goal and propose which MootOS capabilities it
would require to fully accomplish, using short dotted capability-style
identifiers such as "tasks.manage" or "cloud.archive_dropbox".

Currently installed capabilities (for reference only -- you are proposing
what the goal needs, not verifying what exists; that is checked separately
and your claims about installation are never trusted):
{capability_reference}

Respond with ONLY one JSON object. No prose, no markdown, no code fences,
no explanation outside the JSON. Shape exactly:

{{"requirements": [{{"capability": "<dotted.id>", "reason": "<short text>", "externally_blocked": <true or false>}}]}}

Rules:
- "capability" must be a short, dotted, lowercase identifier (letters,
  digits, underscores, at least one dot) -- reuse one from the reference
  list above when it fits, or invent a plausible new one. Never a full
  sentence.
- "reason" is a short (one sentence) explanation of why the goal needs it.
- Set "externally_blocked" to true only when this specific requirement is
  not something MootOS could reasonably gain as a normal internal
  capability or connector -- for example, accessing another person's
  private account without their consent, guaranteeing a real-world
  outcome, or something no software capability could provide. Set it to
  false for anything that is either already installed or could plausibly
  be added as an internal tool or connector. A capability simply being
  missing today is not, by itself, "externally_blocked".
- Propose at most {max_requirements} requirements. If the goal needs
  nothing beyond ordinary conversation, respond with
  {{"requirements": []}}.
- Do not state or imply whether a capability is actually installed --
  only propose what the goal appears to need.
"""


def _build_instructions(registry: ToolRegistry) -> str:
    entries = build_capability_index(registry)
    reference = (
        "\n".join(f"- {entry['id']}: {entry['label']}" for entry in entries)
        if entries
        else "(none currently installed)"
    )
    return _INSTRUCTIONS_TEMPLATE.format(
        capability_reference=reference,
        max_requirements=MAX_REQUIREMENTS,
    )


def _propose(router: ModelRouter, goal: str, registry: ToolRegistry) -> ModelResponse:
    return router.generate_standalone(
        messages=[{"role": "user", "content": goal}],
        instructions=_build_instructions(registry),
    )


def _strip_code_fence(text: str) -> str:
    """Defensively remove a whole-response ```/```json fence.

    Only strips a fence that wraps the *entire* response -- leading prose
    before a fence is not extracted from; that response still fails JSON
    parsing and is rejected, matching this module's fail-closed contract
    for output that does not follow the "only JSON" instruction.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines:
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _validate_requirement_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict) or not set(item).issubset(_REQUIREMENT_ALLOWED_KEYS):
        raise GapAnalysisError("Model output did not match the required shape")

    capability = item.get("capability")
    if not isinstance(capability, str):
        raise GapAnalysisError("Model output did not match the required shape")
    capability = capability.strip().lower()
    if not capability or len(capability) > CAPABILITY_ID_MAX_CHARACTERS:
        raise GapAnalysisError("Model output did not match the required shape")
    if not _CAPABILITY_ID_PATTERN.match(capability):
        raise GapAnalysisError("Model output did not match the required shape")

    reason = item.get("reason", "") or ""
    if not isinstance(reason, str):
        raise GapAnalysisError("Model output did not match the required shape")
    reason = reason.strip()[:REASON_MAX_CHARACTERS]

    externally_blocked = item.get("externally_blocked", False)
    if externally_blocked is None:
        externally_blocked = False
    if not isinstance(externally_blocked, bool):
        raise GapAnalysisError("Model output did not match the required shape")

    return {"capability": capability, "reason": reason, "externally_blocked": externally_blocked}


def _parse_and_validate_proposal(text: str) -> list[dict[str, Any]]:
    """Parse and strictly validate the model's proposed-requirements JSON.

    Fails closed on any deviation from the exact required shape -- there is
    no lenient/partial acceptance. A well-formed proposal is either fully
    accepted or the whole analysis raises ``GapAnalysisError``.
    """
    candidate = _strip_code_fence(text)
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError) as error:
        raise GapAnalysisError("Model did not return valid JSON") from error

    if not isinstance(parsed, dict) or set(parsed) != {"requirements"}:
        raise GapAnalysisError("Model output did not match the required shape")

    requirements = parsed["requirements"]
    if not isinstance(requirements, list) or len(requirements) > MAX_REQUIREMENTS:
        raise GapAnalysisError("Model output did not match the required shape")

    return [_validate_requirement_item(item) for item in requirements]


# --- Deterministic resolution ------------------------------------------------


def resolve_requirements(
    proposed: Sequence[dict[str, Any]],
    registry: Optional[ToolRegistry] = None,
) -> tuple[RequirementResolution, ...]:
    """Deterministically resolve validated proposed requirements against the
    live V0.3A capability index. The model's ``capability`` string is only
    ever used as a lookup key here -- it is never written back into the
    registry or catalog, and an unmatched id simply resolves ``installed=
    False`` (see ``docs/CAPABILITY_ARCHITECTURE.md`` Sec2: the Tool
    Registry remains the only executable source of truth)."""
    active_registry = registry if registry is not None else get_tool_registry()
    capability_index = {entry["id"]: entry for entry in build_capability_index(active_registry)}

    resolved = []
    for item in proposed:
        capability_id = item["capability"]
        entry = capability_index.get(capability_id)
        resolved.append(
            RequirementResolution(
                capability=capability_id,
                reason=item.get("reason", ""),
                externally_blocked=bool(item.get("externally_blocked", False)),
                installed=entry is not None,
                tools=tuple(entry["tools"]) if entry is not None else (),
            )
        )
    return tuple(resolved)


def _classify(resolutions: Sequence[RequirementResolution]) -> str:
    if any(resolution.externally_blocked for resolution in resolutions):
        return CLASSIFICATION_EXTERNALLY_BLOCKED
    if any(not resolution.installed for resolution in resolutions):
        return CLASSIFICATION_CAPABILITY_GAP
    if len({resolution.capability for resolution in resolutions}) >= 2:
        return CLASSIFICATION_COMPOSABLE
    return CLASSIFICATION_ALREADY_POSSIBLE


def _build_notes(
    classification: str,
    resolutions: Sequence[RequirementResolution],
    available: Sequence[str],
    missing: Sequence[str],
    blocked: Sequence[str],
) -> str:
    if classification == CLASSIFICATION_ALREADY_POSSIBLE:
        if not resolutions:
            return "No new capability is required for this goal."
        return f"Already installed: {', '.join(available)}."
    if classification == CLASSIFICATION_COMPOSABLE:
        return f"Achievable by combining currently installed capabilities: {', '.join(available)}."

    parts = []
    if classification == CLASSIFICATION_EXTERNALLY_BLOCKED:
        parts.append(f"Blocked: {', '.join(blocked)}.")
    if missing:
        parts.append(f"Missing: {', '.join(missing)}.")
    if available:
        parts.append(f"Already installed: {', '.join(available)}.")
    return " ".join(parts)


def _build_report(goal: str, resolutions: tuple[RequirementResolution, ...]) -> GapReport:
    available = tuple(
        sorted({r.capability for r in resolutions if r.installed and not r.externally_blocked})
    )
    missing = tuple(
        sorted({r.capability for r in resolutions if not r.installed and not r.externally_blocked})
    )
    blocked = tuple(sorted({r.capability for r in resolutions if r.externally_blocked}))
    classification = _classify(resolutions)
    composable = available if classification == CLASSIFICATION_COMPOSABLE else ()

    return GapReport(
        goal=goal,
        requirements=resolutions,
        available_capabilities=available,
        composable_capabilities=composable,
        missing_capabilities=missing,
        externally_blocked_capabilities=blocked,
        classification=classification,
        notes=_build_notes(classification, resolutions, available, missing, blocked),
    )


# --- Orchestration ------------------------------------------------------------


def _normalize_goal(goal: Any) -> str:
    if not isinstance(goal, str):
        raise GapAnalysisError("Goal must be text")
    normalized = goal.strip()
    if not normalized:
        raise GapAnalysisError("Goal must not be empty")
    return normalized[:GOAL_MAX_CHARACTERS]


def analyze_goal(
    goal: str,
    *,
    router: ModelRouter,
    registry: Optional[ToolRegistry] = None,
    conversation_id: Optional[str] = None,
) -> GapReport:
    """Analyze one natural-language goal into a structured, audited
    ``GapReport``. Reasoning only -- never executes a tool, never registers
    a capability, never installs anything.

    Always either returns a complete, internally consistent ``GapReport``
    or raises ``GapAnalysisError`` -- there is no partial/malformed report.
    Every call is audited as a ``RUN_TYPE_MODEL`` Run (existing Run/audit
    conventions, no schema change): the Run row records that an analysis
    was attempted and whether it succeeded, exactly like any other model
    Run. The existing ``runs`` table has no column capable of holding the
    goal text, the model's raw output, or the report body, so this can
    never store a prompt/response dump -- only identity/status/timing, per
    the existing Run schema.
    """
    active_registry = registry if registry is not None else get_tool_registry()
    run = start_model_run(
        conversation_id=conversation_id,
        provider=None,
        model=None,
        data_exposure=DATA_EXPOSURE_MODEL_PROVIDER,
    )

    try:
        normalized_goal = _normalize_goal(goal)
        response = _propose(router, normalized_goal, active_registry)
        proposed = _parse_and_validate_proposal(response.text)
    except GapAnalysisError as error:
        finish_model_run_failure(run["id"], error)
        raise
    except ModelProviderError as error:
        finish_model_run_failure(run["id"], error)
        raise GapAnalysisError("MootOS could not analyze this goal right now.") from error
    except Exception as error:  # deliberately broad: sanitized boundary
        finish_model_run_failure(run["id"], error)
        raise GapAnalysisError("MootOS could not analyze this goal.") from error

    resolutions = resolve_requirements(proposed, active_registry)
    report = _build_report(normalized_goal, resolutions)

    finish_model_run_success(
        run["id"],
        conversation_id=conversation_id,
        provider=response.provider,
        model=response.model,
    )
    return report
