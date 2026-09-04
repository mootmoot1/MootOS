"""Strict canonical parser and digest binding for builder blueprints."""

import hashlib
import json
import re
from dataclasses import dataclass

from .blueprint import (
    MAX_SERIALIZED_BYTES,
    SCHEMA_VERSION,
    BlueprintError,
    BuildBudget,
    ContinuousBuilderBlueprint,
    RollbackContract,
    SliceBlueprint,
    SystemBlueprint,
)
from .text_safety import utf8_length


class BlueprintParseError(BlueprintError):
    """Raised when serialized blueprint input is not exactly supported."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROOT = {
    "blueprint_id", "blueprint_version", "goal", "schema_version", "slices",
    "source_commit", "systems",
}
_SYSTEM = {"description", "name", "system_id"}
_SLICE = {
    "acceptance_criteria", "allowed_paths", "authority_classes", "budget",
    "expected_risk", "forbidden_paths", "hard_dependencies",
    "human_checkpoints", "non_goals", "objective", "priority_class",
    "promotion_eligibility", "requested_capabilities", "required_gates",
    "required_tests", "rollback", "slice_id", "soft_dependencies",
    "system_id", "version",
}
_BUDGET = {
    "max_attempts", "max_fix_rounds", "max_minutes", "max_output_bytes",
}
_ROLLBACK = {"strategy", "verification"}


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BlueprintParseError(f"duplicate field: {key}")
        result[key] = value
    return result


def _exact(value, fields, name):
    if not isinstance(value, dict):
        raise BlueprintParseError(f"{name} must be an object")
    unknown = set(value) - fields
    missing = fields - set(value)
    if unknown:
        raise BlueprintParseError(
            f"{name} has unknown fields: {sorted(unknown)}"
        )
    if missing:
        raise BlueprintParseError(
            f"{name} is missing fields: {sorted(missing)}"
        )
    return value


@dataclass(frozen=True)
class ParsedBlueprint:
    blueprint: ContinuousBuilderBlueprint
    content_sha256: str
    canonical_json: str
    signer_authenticated: bool = False
    persisted: bool = False

    def __post_init__(self):
        expected = hashlib.sha256(self.blueprint.canonical_bytes()).hexdigest()
        if self.content_sha256 != expected:
            raise BlueprintParseError("content digest does not bind blueprint")
        if (
            self.canonical_json.encode("utf-8")
            != self.blueprint.canonical_bytes()
        ):
            raise BlueprintParseError("canonical JSON does not bind blueprint")
        if self.signer_authenticated or self.persisted:
            raise BlueprintParseError(
                "parser cannot claim authority or persistence"
            )

    def to_dict(self):
        return {
            "blueprint": self.blueprint.to_dict(),
            "canonical_json": self.canonical_json,
            "content_sha256": self.content_sha256,
            "persisted": False,
            "signer_authenticated": False,
        }


def parse_blueprint(payload, expected_digest=None):
    """Parse exact JSON and return its canonical immutable representation."""
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise BlueprintParseError(
                "blueprint must be valid UTF-8"
            ) from error
    if not isinstance(payload, str):
        raise BlueprintParseError("blueprint payload must be text or bytes")
    if utf8_length(payload) > MAX_SERIALIZED_BYTES:
        raise BlueprintParseError("blueprint payload exceeds byte bound")
    try:
        raw = json.loads(payload, object_pairs_hook=_object_pairs)
    except (json.JSONDecodeError, TypeError) as error:
        raise BlueprintParseError("blueprint is not valid JSON") from error
    raw = _exact(raw, _ROOT, "blueprint")
    if raw["schema_version"] != SCHEMA_VERSION:
        raise BlueprintParseError("unsupported schema version")
    if not isinstance(raw["systems"], list) or not isinstance(
        raw["slices"], list
    ):
        raise BlueprintParseError("systems and slices must be arrays")
    systems = tuple(SystemBlueprint(**_exact(item, _SYSTEM, "system"))
                    for item in raw["systems"])
    slices = []
    for item in raw["slices"]:
        item = dict(_exact(item, _SLICE, "slice"))
        item["budget"] = BuildBudget(
            **_exact(item["budget"], _BUDGET, "budget")
        )
        item["rollback"] = RollbackContract(
            **_exact(item["rollback"], _ROLLBACK, "rollback")
        )
        slices.append(SliceBlueprint(**item))
    blueprint = ContinuousBuilderBlueprint(
        schema_version=raw["schema_version"],
        blueprint_id=raw["blueprint_id"],
        blueprint_version=raw["blueprint_version"],
        source_commit=raw["source_commit"], goal=raw["goal"],
        systems=systems, slices=tuple(slices),
    )
    digest = hashlib.sha256(blueprint.canonical_bytes()).hexdigest()
    if expected_digest is not None:
        if not isinstance(expected_digest, str) or not _SHA256.fullmatch(
                expected_digest):
            raise BlueprintParseError("expected digest is malformed")
        if digest != expected_digest:
            raise BlueprintParseError("blueprint mutation detected")
    return ParsedBlueprint(
        blueprint=blueprint, content_sha256=digest,
        canonical_json=blueprint.canonical_bytes().decode("utf-8"),
    )
