"""Immutable, bounded Continuous Builder blueprint domain models."""

import json
import re
from dataclasses import dataclass

from .paths import PathCanonicalizationError, canonicalize_repo_path


class BlueprintError(ValueError):
    """Raised when a blueprint value is malformed or unsafe."""


SCHEMA_VERSION = "1"
RISK_CLASSES = ("low", "medium", "high")
PRIORITY_CLASSES = ("critical", "high", "normal", "low")
PROMOTION_POLICIES = ("not_eligible", "human_review_only")
MAX_TEXT_BYTES = 2048
MAX_ITEMS = 64
MAX_SLICES = 128
MAX_SERIALIZED_BYTES = 256 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SECRET = re.compile(
    r"(?i)(?:password|secret|api[_-]?key|authorization|bearer)\s*[:=]"
)


def _text(value, name, limit=MAX_TEXT_BYTES, identifier=False):
    if not isinstance(value, str) or not value.strip():
        raise BlueprintError(f"{name} must be nonblank text")
    value = value.strip()
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise BlueprintError(
            f"{name} contains an unpaired UTF-16 surrogate"
        ) from error
    if encoded_length > limit:
        raise BlueprintError(f"{name} exceeds {limit} bytes")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise BlueprintError(f"{name} contains control characters")
    if _SECRET.search(value):
        raise BlueprintError(f"{name} contains secret-like text")
    if identifier and _IDENTIFIER.fullmatch(value) is None:
        raise BlueprintError(f"{name} is malformed")
    return value


def _texts(values, name, path=False):
    if not isinstance(values, (list, tuple)):
        raise BlueprintError(f"{name} must be a collection")
    values = tuple(values)
    if len(values) > MAX_ITEMS:
        raise BlueprintError(f"{name} exceeds item bound")
    normalized = tuple(_text(value, name) for value in values)
    if path:
        try:
            normalized = tuple(
                canonicalize_repo_path(value) for value in normalized
            )
        except PathCanonicalizationError as error:
            raise BlueprintError(f"{name} contains an unsafe path") from error
    if len(normalized) != len(set(normalized)):
        raise BlueprintError(f"{name} must be unique")
    return normalized


@dataclass(frozen=True)
class BuildBudget:
    max_attempts: int
    max_fix_rounds: int
    max_minutes: int
    max_output_bytes: int

    def __post_init__(self):
        bounds = ((self.max_attempts, 1, 10), (self.max_fix_rounds, 0, 2),
                  (self.max_minutes, 1, 1440),
                  (self.max_output_bytes, 1024, 10 * 1024 * 1024))
        if any(type(value) is not int or not low <= value <= high
               for value, low, high in bounds):
            raise BlueprintError("budget value is outside its bound")

    def to_dict(self):
        return {
            "max_attempts": self.max_attempts,
            "max_fix_rounds": self.max_fix_rounds,
            "max_minutes": self.max_minutes,
            "max_output_bytes": self.max_output_bytes,
        }


@dataclass(frozen=True)
class RollbackContract:
    strategy: str
    verification: tuple

    def __post_init__(self):
        object.__setattr__(self, "strategy", _text(self.strategy, "rollback"))
        object.__setattr__(
            self,
            "verification",
            _texts(self.verification, "rollback verification"),
        )
        if not self.verification:
            raise BlueprintError("rollback verification is required")

    def to_dict(self):
        return {
            "strategy": self.strategy,
            "verification": list(self.verification),
        }


@dataclass(frozen=True)
class SystemBlueprint:
    system_id: str
    name: str
    description: str

    def __post_init__(self):
        object.__setattr__(self, "system_id", _text(
            self.system_id, "system_id", 128, True
        ))
        object.__setattr__(self, "name", _text(self.name, "system name", 256))
        object.__setattr__(
            self, "description", _text(self.description, "system description")
        )

    def to_dict(self):
        return {"description": self.description, "name": self.name,
                "system_id": self.system_id}


@dataclass(frozen=True)
class SliceBlueprint:
    slice_id: str
    version: str
    system_id: str
    objective: str
    acceptance_criteria: tuple
    hard_dependencies: tuple
    soft_dependencies: tuple
    requested_capabilities: tuple
    expected_risk: str
    allowed_paths: tuple
    forbidden_paths: tuple
    required_tests: tuple
    required_gates: tuple
    budget: BuildBudget
    rollback: RollbackContract
    human_checkpoints: tuple
    non_goals: tuple
    promotion_eligibility: str = "not_eligible"
    priority_class: str = "normal"
    authority_classes: tuple = ()

    def __post_init__(self):
        for name in ("slice_id", "version", "system_id"):
            object.__setattr__(self, name, _text(
                getattr(self, name), name, 128, True
            ))
        object.__setattr__(
            self, "objective", _text(self.objective, "objective")
        )
        for name in ("acceptance_criteria", "hard_dependencies",
                     "soft_dependencies", "requested_capabilities",
                     "required_tests", "required_gates", "human_checkpoints",
                     "non_goals", "authority_classes"):
            object.__setattr__(self, name, _texts(getattr(self, name), name))
        for name in ("allowed_paths", "forbidden_paths"):
            object.__setattr__(
                self, name, _texts(getattr(self, name), name, path=True)
            )
        if not self.acceptance_criteria or not self.allowed_paths:
            raise BlueprintError(
                "acceptance criteria and allowed paths are required"
            )
        if set(self.hard_dependencies) & set(self.soft_dependencies):
            raise BlueprintError("hard and soft dependencies must be disjoint")
        if self.expected_risk not in RISK_CLASSES:
            raise BlueprintError("unsupported expected risk")
        if self.priority_class not in PRIORITY_CLASSES:
            raise BlueprintError("unsupported priority class")
        if self.promotion_eligibility not in PROMOTION_POLICIES:
            raise BlueprintError("unsupported promotion eligibility")
        if not isinstance(self.budget, BuildBudget):
            raise BlueprintError("budget must be BuildBudget")
        if not isinstance(self.rollback, RollbackContract):
            raise BlueprintError("rollback must be RollbackContract")

    def to_dict(self):
        return {
            "acceptance_criteria": list(self.acceptance_criteria),
            "allowed_paths": list(self.allowed_paths),
            "authority_classes": list(self.authority_classes),
            "budget": self.budget.to_dict(),
            "expected_risk": self.expected_risk,
            "forbidden_paths": list(self.forbidden_paths),
            "hard_dependencies": list(self.hard_dependencies),
            "human_checkpoints": list(self.human_checkpoints),
            "non_goals": list(self.non_goals),
            "objective": self.objective,
            "priority_class": self.priority_class,
            "promotion_eligibility": self.promotion_eligibility,
            "requested_capabilities": list(self.requested_capabilities),
            "required_gates": list(self.required_gates),
            "required_tests": list(self.required_tests),
            "rollback": self.rollback.to_dict(),
            "slice_id": self.slice_id,
            "soft_dependencies": list(self.soft_dependencies),
            "system_id": self.system_id,
            "version": self.version,
        }


@dataclass(frozen=True)
class ContinuousBuilderBlueprint:
    schema_version: str
    blueprint_id: str
    blueprint_version: str
    source_commit: str
    goal: str
    systems: tuple
    slices: tuple

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION:
            raise BlueprintError("unsupported schema version")
        for name in ("blueprint_id", "blueprint_version"):
            object.__setattr__(self, name, _text(
                getattr(self, name), name, 128, True
            ))
        commit = _text(self.source_commit, "source_commit", 64)
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise BlueprintError("source_commit must be a full SHA-1")
        object.__setattr__(self, "source_commit", commit)
        object.__setattr__(self, "goal", _text(self.goal, "goal"))
        systems = tuple(self.systems)
        slices = tuple(self.slices)
        if not systems or len(systems) > MAX_ITEMS or any(
                not isinstance(item, SystemBlueprint) for item in systems):
            raise BlueprintError("invalid systems")
        if not slices or len(slices) > MAX_SLICES or any(
                not isinstance(item, SliceBlueprint) for item in slices):
            raise BlueprintError("invalid slices")
        system_ids = tuple(item.system_id for item in systems)
        slice_ids = tuple(item.slice_id for item in slices)
        if len(system_ids) != len(set(system_ids)):
            raise BlueprintError("system IDs must be unique")
        if len(slice_ids) != len(set(slice_ids)):
            raise BlueprintError("slice IDs must be unique")
        if any(item.system_id not in system_ids for item in slices):
            raise BlueprintError("slice references an unknown system")
        object.__setattr__(self, "systems", systems)
        object.__setattr__(self, "slices", slices)
        if len(self.canonical_bytes()) > MAX_SERIALIZED_BYTES:
            raise BlueprintError("blueprint exceeds serialized byte bound")

    def to_dict(self):
        return {
            "blueprint_id": self.blueprint_id,
            "blueprint_version": self.blueprint_version,
            "goal": self.goal,
            "schema_version": self.schema_version,
            "slices": [item.to_dict() for item in self.slices],
            "source_commit": self.source_commit,
            "systems": [item.to_dict() for item in self.systems],
        }

    def canonical_bytes(self):
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
