"""The capability specification artifact (V0.3E).

The smallest useful machine-readable, human-reviewable description of one
proposed capability -- deliberately a flat dataclass with explicit fields
and deterministic cross-field rules, not a DSL. Every field maps directly
to a question a human reviewer has to answer before implementation begins
(see ``docs/CAPABILITY_BUILD_PIPELINE.md``).

Validation happens in two places that both enforce the same rules, on
purpose:

1. ``CapabilitySpec.__post_init__`` -- so constructing the dataclass
   directly (bypassing ``spec_from_dict``) still cannot produce an
   invalid spec. This mirrors ``backend.tool_types.ToolDefinition``'s own
   pattern deliberately: validation must not be skippable by choosing a
   different entry point.
2. ``spec_from_dict`` -- additionally rejects any unknown top-level key
   (fail-closed, ``additionalProperties: False`` semantics, matching
   every JSON-Schema-shaped contract already used in this codebase) before
   handing the known fields to the dataclass.

This module intentionally reuses MootOS's real risk/data-exposure
constants (``backend.tool_types``, ``backend.runs``) rather than
re-declaring its own copies -- a spec's risk classification is checked
against the exact same taxonomy a real ``ToolDefinition`` uses, so the
two can never quietly drift apart.
"""

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from backend.runs import VALID_DATA_EXPOSURES
from backend.tool_types import RISK_READ_ONLY, VALID_RISK_LEVELS


class CapabilitySpecError(ValueError):
    """Raised whenever a capability specification is malformed, internally
    inconsistent, or missing a required field. Always fails closed --
    there is no partial/best-effort spec."""


_DOTTED_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def _require_nonempty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilitySpecError(f"{field!r} must be a non-empty string")
    return value


def _require_str_tuple(value: Any, field: str, *, allow_empty: bool) -> tuple:
    if not isinstance(value, (tuple, list)):
        raise CapabilitySpecError(f"{field!r} must be a list/tuple of strings")
    items = tuple(value)
    if not allow_empty and not items:
        raise CapabilitySpecError(f"{field!r} must contain at least one entry")
    if any(not isinstance(item, str) or not item.strip() for item in items):
        raise CapabilitySpecError(f"{field!r} entries must be non-empty strings")
    return items


def _require_dotted_id(value: Any, field: str) -> str:
    text = _require_nonempty_str(value, field)
    if not _DOTTED_ID_PATTERN.match(text):
        raise CapabilitySpecError(
            f"{field!r} must be a dotted lowercase identifier such as "
            f"'tasks.status_insight' (got {text!r})"
        )
    return text


@dataclass(frozen=True)
class CapabilitySpec:
    """One proposed capability, fully specified for human review.

    Every field here answers a question a reviewer needs answered before
    approving implementation to begin -- see
    ``docs/CAPABILITY_BUILD_PIPELINE.md`` Sec3 for the field-by-field
    reviewer checklist this schema exists to support.
    """

    capability_id: str
    human_readable_goal: str
    tool_names: tuple
    resource_or_connector: str
    input_contract: Mapping[str, Any]
    output_contract: Mapping[str, str]
    side_effects: str
    has_side_effects: bool
    idempotent: bool
    risk: str
    data_exposure: str
    limitations: str
    required_tests: tuple
    rollback_notes: str
    registration_requirement: str
    dependencies: tuple = ()
    protected_core_impact: tuple = ()
    requires_human_registration_review: bool = False

    def __post_init__(self) -> None:
        _require_dotted_id(self.capability_id, "capability_id")
        _require_nonempty_str(self.human_readable_goal, "human_readable_goal")
        tool_names = _require_str_tuple(self.tool_names, "tool_names", allow_empty=False)
        for name in tool_names:
            _require_dotted_id(name, "tool_names entry")
        object.__setattr__(self, "tool_names", tool_names)

        _require_nonempty_str(self.resource_or_connector, "resource_or_connector")

        if not isinstance(self.input_contract, Mapping):
            raise CapabilitySpecError("'input_contract' must be an object/mapping")
        if self.input_contract.get("type") != "object":
            raise CapabilitySpecError("'input_contract' must have type: 'object'")
        if "properties" not in self.input_contract or "required" not in self.input_contract:
            raise CapabilitySpecError(
                "'input_contract' must declare 'properties' and 'required', "
                "matching backend/tool_validation.py's supported subset"
            )

        if not isinstance(self.output_contract, Mapping) or not self.output_contract:
            raise CapabilitySpecError(
                "'output_contract' must be a non-empty mapping of field name -> description"
            )
        for key, description in self.output_contract.items():
            if not isinstance(key, str) or not key.strip():
                raise CapabilitySpecError("'output_contract' keys must be non-empty strings")
            if not isinstance(description, str) or not description.strip():
                raise CapabilitySpecError(
                    f"'output_contract' entry {key!r} must have a non-empty description"
                )

        _require_nonempty_str(self.side_effects, "side_effects")

        if not isinstance(self.has_side_effects, bool):
            raise CapabilitySpecError("'has_side_effects' must be a boolean")
        if not isinstance(self.idempotent, bool):
            raise CapabilitySpecError("'idempotent' must be a boolean")

        if self.risk not in VALID_RISK_LEVELS:
            raise CapabilitySpecError(
                f"'risk' must be one of {sorted(VALID_RISK_LEVELS)} (got {self.risk!r})"
            )
        if self.data_exposure not in VALID_DATA_EXPOSURES:
            raise CapabilitySpecError(
                f"'data_exposure' must be one of {sorted(VALID_DATA_EXPOSURES)} "
                f"(got {self.data_exposure!r})"
            )

        # Test requirement #5: a write-capable spec cannot be mislabeled
        # read-only. This is a deterministic cross-field rule, not text
        # sniffing over the free-text 'side_effects' description -- exactly
        # per this phase's "prefer explicit schema rules" instruction.
        if self.risk == RISK_READ_ONLY and self.has_side_effects:
            raise CapabilitySpecError(
                "A capability classified 'read_only' cannot declare "
                "has_side_effects=True -- this is either mis-scoped as "
                "read_only, or has_side_effects is wrong. Fix one or the "
                "other; a read_only risk classification must never be "
                "used to under-declare a real side effect."
            )

        _require_nonempty_str(self.limitations, "limitations")

        required_tests = _require_str_tuple(self.required_tests, "required_tests", allow_empty=False)
        object.__setattr__(self, "required_tests", required_tests)

        _require_nonempty_str(self.rollback_notes, "rollback_notes")
        _require_nonempty_str(self.registration_requirement, "registration_requirement")

        dependencies = _require_str_tuple(self.dependencies, "dependencies", allow_empty=True)
        object.__setattr__(self, "dependencies", dependencies)

        protected_core_impact = _require_str_tuple(
            self.protected_core_impact, "protected_core_impact", allow_empty=True
        )
        object.__setattr__(self, "protected_core_impact", protected_core_impact)

        if not isinstance(self.requires_human_registration_review, bool):
            raise CapabilitySpecError("'requires_human_registration_review' must be a boolean")

        # Test requirement #6: protected-core impact must be surfaced, not
        # silently declared away. If the spec names any protected path,
        # the human-review flag is mandatory -- fails closed on the
        # inverse (paths named, flag left False).
        if protected_core_impact and not self.requires_human_registration_review:
            raise CapabilitySpecError(
                "'protected_core_impact' names at least one path, so "
                "'requires_human_registration_review' must be True -- a "
                "protected-core touch can never be marked as not requiring "
                "elevated human review"
            )

    def to_dict(self) -> dict:
        return {
            "capability_id": self.capability_id,
            "human_readable_goal": self.human_readable_goal,
            "tool_names": list(self.tool_names),
            "resource_or_connector": self.resource_or_connector,
            "input_contract": dict(self.input_contract),
            "output_contract": dict(self.output_contract),
            "side_effects": self.side_effects,
            "has_side_effects": self.has_side_effects,
            "idempotent": self.idempotent,
            "risk": self.risk,
            "data_exposure": self.data_exposure,
            "limitations": self.limitations,
            "required_tests": list(self.required_tests),
            "rollback_notes": self.rollback_notes,
            "registration_requirement": self.registration_requirement,
            "dependencies": list(self.dependencies),
            "protected_core_impact": list(self.protected_core_impact),
            "requires_human_registration_review": self.requires_human_registration_review,
        }


# The exact set of keys spec_from_dict accepts -- anything else is
# rejected before it ever reaches the dataclass, so a typo'd or
# speculative field fails loudly instead of being silently ignored.
_ALLOWED_FIELDS = frozenset(CapabilitySpec.__dataclass_fields__.keys())


def spec_from_dict(data: Mapping[str, Any]) -> CapabilitySpec:
    """Build and validate a ``CapabilitySpec`` from a plain dict (as
    loaded from a JSON/YAML capability-spec file). Fails closed on any
    key not in the schema -- a malformed or speculative field is a hard
    error, never a silently-ignored extra."""
    if not isinstance(data, Mapping):
        raise CapabilitySpecError("A capability spec must be a JSON/YAML object")

    unknown = set(data.keys()) - _ALLOWED_FIELDS
    if unknown:
        raise CapabilitySpecError(
            f"Unknown capability-spec field(s): {', '.join(sorted(unknown))}"
        )

    try:
        return CapabilitySpec(**data)
    except TypeError as error:
        # A required field is missing entirely (dataclass construction
        # itself fails) -- normalize to the same error type everything
        # else in this module raises, with the real reason preserved.
        raise CapabilitySpecError(f"Malformed capability spec: {error}") from error


def load_spec_file(path) -> CapabilitySpec:
    """Load and validate a capability spec from a JSON file on disk."""
    import json
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise CapabilitySpecError(f"{path}: not valid JSON: {error}") from error
    return spec_from_dict(data)


def main(argv: Optional[list] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate a V0.3E capability specification JSON file."
    )
    parser.add_argument("path", help="Path to a capability spec JSON file")
    args = parser.parse_args(argv)

    try:
        spec = load_spec_file(args.path)
    except CapabilitySpecError as error:
        print(f"INVALID: {error}")
        return 1

    print(f"VALID: {spec.capability_id} ({', '.join(spec.tool_names)})")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
