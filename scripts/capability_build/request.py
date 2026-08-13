"""Pure build-request intake records for MootOS V0.4B Slice 2.

A request is bounded, normalized human intent only. It cannot create or
advance a workflow, create build artifacts, execute commands, access files
or networks, invoke Git or GitHub, register or install capabilities, or
exercise backend/runtime/deployment authority.
"""

import json
import unicodedata
from dataclasses import dataclass, field
from typing import Any


class RequestError(ValueError):
    """Raised when a request cannot be represented safely."""


SCHEMA_VERSION = 1
STATUS_DRAFT = "draft"
STATUS_READY_FOR_WORKFLOW = "ready_for_workflow"
STATUS_BLOCKED = "blocked"
REQUEST_STATUSES = (
    STATUS_DRAFT,
    STATUS_READY_FOR_WORKFLOW,
    STATUS_BLOCKED,
)

MAX_REQUEST_ID_BYTES = 128
MAX_CAPABILITY_NAME_BYTES = 200
MAX_USER_GOAL_BYTES = 2_000
MAX_BEHAVIOR_SUMMARY_BYTES = 4_000
MAX_LIST_ITEM_BYTES = 512
MAX_LIST_ITEMS = 8
MAX_REQUEST_SUMMARY_BYTES = 32 * 1024

_MISSING_REASON = {
    "request_id": "request_id is required.",
    "capability_name": "capability_name is required.",
    "user_goal": "user_goal is required.",
}

_UNSAFE_AUTHORITY_POLICIES = (
    (
        "Request asks for autonomous deployment authority.",
        (
            "autonomous deployment",
            "deploy autonomously",
            "automatically deploy",
            "unattended deployment",
            "deploy without human approval",
        ),
    ),
    (
        "Request asks for direct registry or runtime writes.",
        (
            "direct registry write",
            "direct registry runtime write",
            "write directly to registry",
            "modify runtime registry",
            "write runtime state",
            "direct runtime write",
        ),
    ),
    (
        "Request asks for self-installation authority.",
        (
            "self install",
            "self installation",
            "install itself",
            "automatically install capability",
        ),
    ),
    (
        "Request asks for arbitrary shell or root access.",
        (
            "arbitrary shell access",
            "arbitrary shell root access",
            "root access",
            "run as root",
            "sudo access",
        ),
    ),
    (
        "Request asks for secret exfiltration.",
        (
            "exfiltrate secrets",
            "secret exfiltration",
            "steal secrets",
            "expose secrets",
            "copy api keys",
        ),
    ),
    (
        "Request asks to bypass human approval.",
        (
            "bypass human approval",
            "skip human approval",
            "without human approval",
        ),
    ),
    (
        "Request asks for direct GitHub PR or merge automation.",
        (
            "automatically create pull request",
            "automatically merge",
            "direct github merge",
            "github merge without approval",
            "github pr automation",
        ),
    ),
)

_NEGATION_WORDS = frozenset(
    {"avoid", "forbid", "forbidden", "never", "no", "not"}
)


def _collapse_human_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFC", value)
    without_controls = "".join(
        " " if unicodedata.category(character) == "Cc" else character
        for character in normalized
    )
    return " ".join(without_controls.split())


def _secret_shape(value: str) -> bool:
    lowered = value.casefold()
    for prefix, required in (
        ("sk-", 16),
        ("ghp_", 20),
        ("gho_", 20),
        ("ghu_", 20),
        ("ghs_", 20),
        ("ghr_", 20),
        ("akia", 16),
    ):
        start = 0
        while True:
            index = lowered.find(prefix, start)
            if index < 0:
                break
            suffix = lowered[index + len(prefix):]
            count = 0
            for character in suffix:
                if not (character.isalnum() or character in "_-"):
                    break
                count += 1
            if count >= required:
                return True
            start = index + len(prefix)
    for marker in (
        "api key",
        "api_key",
        "access token",
        "access_token",
        "password",
        "secret key",
        "secret_key",
        "session secret",
        "session_secret",
    ):
        index = lowered.find(marker)
        if index < 0:
            continue
        tail = lowered[index + len(marker):].lstrip()
        if not tail or tail[0] not in "=:":
            continue
        candidate = tail[1:].lstrip()
        if candidate[:1] in ("'", '"'):
            candidate = candidate[1:]
        count = 0
        for character in candidate:
            if not (character.isalnum() or character in "_-/+"):
                break
            count += 1
        if count >= 16:
            return True
    return False


def _bounded_field(
    value: Any,
    field_name: str,
    maximum_bytes: int,
    *,
    required: bool = False,
) -> tuple:
    reasons = []
    if not isinstance(value, str):
        normalized = ""
        if value is not None:
            reasons.append(f"{field_name} must be text.")
    else:
        normalized = _collapse_human_text(value)
    if required and not normalized and not reasons:
        reasons.append(_MISSING_REASON[field_name])
    if len(normalized.encode("utf-8")) > maximum_bytes:
        reasons.append(f"{field_name} exceeds {maximum_bytes} bytes.")
        normalized = ""
    if normalized and _secret_shape(normalized):
        reasons.append(f"{field_name} contains secret-like material.")
        normalized = ""
    return normalized, tuple(reasons)


def _bounded_list(values: Any, field_name: str) -> tuple:
    reasons = []
    if values is None:
        return (), ()
    if isinstance(values, (str, bytes)):
        return (), (f"{field_name} must be a sequence of text entries.",)
    try:
        raw_items = tuple(values)
    except TypeError:
        return (), (f"{field_name} must be a sequence of text entries.",)

    normalized = []
    for index, raw_item in enumerate(raw_items):
        item, item_reasons = _bounded_field(
            raw_item,
            f"{field_name}[{index}]",
            MAX_LIST_ITEM_BYTES,
        )
        if not item and not item_reasons:
            item_reasons = (
                f"{field_name} contains a blank text entry.",
            )
        reasons.extend(item_reasons)
        if item:
            normalized.append(item)

    stable_by_identity = {}
    for item in normalized:
        identity = unicodedata.normalize("NFC", item).casefold()
        stable_by_identity.setdefault(identity, item)
    stable_items = tuple(
        sorted(
            stable_by_identity.values(),
            key=lambda item: (item.casefold(), item),
        )
    )
    if len(stable_items) > MAX_LIST_ITEMS:
        reasons.append(
            f"{field_name} exceeds {MAX_LIST_ITEMS} entries."
        )
        stable_items = stable_items[:MAX_LIST_ITEMS]
    return stable_items, tuple(reasons)


def _searchable(value: str) -> str:
    characters = (
        character if character.isalnum() else " "
        for character in value.casefold()
    )
    return " ".join("".join(characters).split())


def _requested_phrase(value: str, phrase: str) -> bool:
    text = _searchable(value)
    target = _searchable(phrase)
    start = 0
    while True:
        index = text.find(target, start)
        if index < 0:
            return False
        preceding = text[:index].split()[-3:]
        if not _NEGATION_WORDS.intersection(preceding):
            return True
        start = index + len(target)


def _unsafe_authority_reasons(values: tuple) -> tuple:
    reasons = []
    for reason, phrases in _UNSAFE_AUTHORITY_POLICIES:
        if any(
            _requested_phrase(value, phrase)
            for value in values
            for phrase in phrases
        ):
            reasons.append(reason)
    return tuple(reasons)


def _stable_reasons(values: tuple) -> tuple:
    return tuple(
        sorted(set(values), key=lambda value: (value.casefold(), value))
    )


@dataclass(frozen=True)
class CapabilityBuildRequest:
    """Immutable, bounded request data with derived readiness only."""

    request_id: Any
    capability_name: Any
    user_goal: Any
    requested_behavior_summary: Any = ""
    constraints: tuple = ()
    non_goals: tuple = ()
    risk_notes: tuple = ()
    requester_decision_required: bool = False
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    status: str = field(init=False)
    blocking_reasons: tuple = field(init=False)
    ready_to_start_workflow: bool = field(init=False)
    offline_only: bool = field(default=True, init=False)
    autonomous: bool = field(default=False, init=False)
    runtime_authority: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        request_id, request_id_reasons = _bounded_field(
            self.request_id,
            "request_id",
            MAX_REQUEST_ID_BYTES,
            required=True,
        )
        capability_name, capability_reasons = _bounded_field(
            self.capability_name,
            "capability_name",
            MAX_CAPABILITY_NAME_BYTES,
            required=True,
        )
        user_goal, goal_reasons = _bounded_field(
            self.user_goal,
            "user_goal",
            MAX_USER_GOAL_BYTES,
            required=True,
        )
        behavior, behavior_reasons = _bounded_field(
            self.requested_behavior_summary,
            "requested_behavior_summary",
            MAX_BEHAVIOR_SUMMARY_BYTES,
        )
        constraints, constraint_reasons = _bounded_list(
            self.constraints, "constraints"
        )
        non_goals, non_goal_reasons = _bounded_list(
            self.non_goals, "non_goals"
        )
        risk_notes, risk_reasons = _bounded_list(
            self.risk_notes, "risk_notes"
        )

        decision_required = self.requester_decision_required
        decision_reasons = ()
        if not isinstance(decision_required, bool):
            decision_required = True
            decision_reasons = (
                "requester_decision_required must be a boolean.",
            )

        intent_values = tuple(
            value
            for value in (
                capability_name,
                user_goal,
                behavior,
                *constraints,
                *non_goals,
                *risk_notes,
            )
            if value
        )
        unsafe_reasons = _unsafe_authority_reasons(intent_values)
        reasons = _stable_reasons(
            request_id_reasons
            + capability_reasons
            + goal_reasons
            + behavior_reasons
            + constraint_reasons
            + non_goal_reasons
            + risk_reasons
            + decision_reasons
            + unsafe_reasons
        )
        if reasons:
            status = STATUS_BLOCKED
        elif decision_required:
            status = STATUS_DRAFT
        else:
            status = STATUS_READY_FOR_WORKFLOW

        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "capability_name", capability_name)
        object.__setattr__(self, "user_goal", user_goal)
        object.__setattr__(self, "requested_behavior_summary", behavior)
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "non_goals", non_goals)
        object.__setattr__(self, "risk_notes", risk_notes)
        object.__setattr__(
            self, "requester_decision_required", decision_required
        )
        object.__setattr__(self, "blocking_reasons", reasons)
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "ready_to_start_workflow",
            status == STATUS_READY_FOR_WORKFLOW,
        )

        if len(self.summary().encode("utf-8")) > MAX_REQUEST_SUMMARY_BYTES:
            raise RequestError(
                "request summary exceeds "
                f"{MAX_REQUEST_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic normalized request data for human review."""
        return {
            "authority": {
                "autonomous": self.autonomous,
                "offline_only": self.offline_only,
                "runtime_authority": self.runtime_authority,
            },
            "blocking_reasons": list(self.blocking_reasons),
            "capability_name": self.capability_name,
            "constraints": list(self.constraints),
            "non_goals": list(self.non_goals),
            "ready_to_start_workflow": self.ready_to_start_workflow,
            "request_id": self.request_id,
            "requested_behavior_summary": (
                self.requested_behavior_summary
            ),
            "requester_decision_required": (
                self.requester_decision_required
            ),
            "risk_notes": list(self.risk_notes),
            "schema_version": self.schema_version,
            "status": self.status,
            "user_goal": self.user_goal,
        }

    def summary(self) -> str:
        """Return stable bounded JSON without operational or secret data."""
        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"
