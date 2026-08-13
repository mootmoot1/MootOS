"""Frozen write-scope model for V0.4A Slice 2.

This module is pure validation and decision logic. It does not inspect or
mutate the filesystem and has no runtime or registry authority.
"""

import fnmatch
from functools import lru_cache
import unicodedata
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional


class ScopeError(ValueError):
    """Raised when a frozen scope or candidate path is unsafe."""


DEFAULT_PROTECTED_FILES = (
    ".github/workflows/**",
    "backend/application.py",
    "backend/auth.py",
    "backend/main.py",
    "backend/tool_budget.py",
    "backend/tool_conversation.py",
    "backend/tool_executor.py",
    "backend/tool_operations.py",
    "backend/tool_registry.py",
    "backend/tool_routes.py",
    "backend/tool_types.py",
    "backend/tool_validation.py",
    "railway.toml",
    "scripts/gates/**",
)

DEFAULT_FORBIDDEN_PATHS = (
    ".env*",
    "**/*.pth",
    "**/__init__.py",
    "**/conftest.py",
    "**/sitecustomize.py",
    "**/usercustomize.py",
    "backend/migrations.py",
    "conftest.py",
    "data/**",
    "pyproject.toml",
    "pytest.ini",
    "requirements*.txt",
    "scripts/capability_build/**",
    "scripts/capability_pipeline/**",
    "setup.cfg",
    "setup.py",
    "sitecustomize.py",
    "tox.ini",
    "usercustomize.py",
)

_PATTERN_CHARACTERS = "*"
_UNSUPPORTED_PATTERN_CHARACTERS = "?[]"


def normalize_repo_path(value: Any, *, allow_pattern: bool = False) -> str:
    """Return one safe NFC, forward-slash repository-relative path."""
    if not isinstance(value, str) or not value.strip():
        raise ScopeError("A scope path must be a non-empty string")
    if "\x00" in value:
        raise ScopeError("A scope path cannot contain a NUL byte")

    normalized = unicodedata.normalize("NFC", value.strip().replace("\\", "/"))
    if normalized.startswith("/"):
        raise ScopeError(f"Absolute paths are forbidden: {value!r}")
    if len(normalized) >= 2 and normalized[1] == ":":
        raise ScopeError(f"Absolute paths are forbidden: {value!r}")

    raw_parts = normalized.split("/")
    if any(part == ".." for part in raw_parts):
        raise ScopeError(f"Parent traversal is forbidden: {value!r}")
    if any(part == "." for part in raw_parts):
        raise ScopeError(f"Dot path segments are forbidden: {value!r}")
    parts = [part for part in raw_parts if part]
    if not parts:
        raise ScopeError("A scope path must name a repository path")
    normalized = "/".join(parts)

    if any(ord(character) < 32 for character in normalized):
        raise ScopeError("A scope path cannot contain control characters")
    if any(
        character in normalized
        for character in _UNSUPPORTED_PATTERN_CHARACTERS
    ):
        raise ScopeError(
            "Only '*' and whole-segment '**' scope patterns are supported"
        )
    if not allow_pattern and any(
        character in normalized for character in _PATTERN_CHARACTERS
    ):
        raise ScopeError("A concrete path cannot contain a pattern")
    for part in parts:
        if "**" in part and part != "**":
            raise ScopeError("'**' must occupy a complete path segment")
    return normalized


def _identity(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _has_pattern(value: str) -> bool:
    return "*" in value


def _matches(rule: str, path: str, *, casefold: bool = False) -> bool:
    rule_parts = rule.split("/")
    path_parts = path.split("/")
    if casefold:
        rule_parts = [_identity(part) for part in rule_parts]
        path_parts = [_identity(part) for part in path_parts]

    def match_from(rule_index: int, path_index: int) -> bool:
        if rule_index == len(rule_parts):
            return path_index == len(path_parts)
        rule_part = rule_parts[rule_index]
        if rule_part == "**":
            return any(
                match_from(rule_index + 1, next_path_index)
                for next_path_index in range(path_index, len(path_parts) + 1)
            )
        if path_index == len(path_parts):
            return False
        if not fnmatch.fnmatchcase(path_parts[path_index], rule_part):
            return False
        return match_from(rule_index + 1, path_index + 1)

    return match_from(0, 0)


def _patterns_overlap(first: str, second: str) -> bool:
    if not _has_pattern(first) and not _has_pattern(second):
        return _identity(first) == _identity(second)
    if not _has_pattern(first):
        return _matches(second, first, casefold=True)
    if not _has_pattern(second):
        return _matches(first, second, casefold=True)

    first_parts = tuple(_identity(part) for part in first.split("/"))
    second_parts = tuple(_identity(part) for part in second.split("/"))

    def segment_overlap(first_part: str, second_part: str) -> bool:
        if "*" not in first_part:
            return fnmatch.fnmatchcase(first_part, second_part)
        if "*" not in second_part:
            return fnmatch.fnmatchcase(second_part, first_part)

        first_prefix, _, first_tail = first_part.partition("*")
        second_prefix, _, second_tail = second_part.partition("*")
        first_suffix = first_tail.rsplit("*", 1)[-1]
        second_suffix = second_tail.rsplit("*", 1)[-1]
        prefixes_overlap = (
            first_prefix.startswith(second_prefix)
            or second_prefix.startswith(first_prefix)
        )
        suffixes_overlap = (
            first_suffix.endswith(second_suffix)
            or second_suffix.endswith(first_suffix)
        )
        return prefixes_overlap and suffixes_overlap

    @lru_cache(maxsize=None)
    def paths_overlap(first_index: int, second_index: int) -> bool:
        if first_index == len(first_parts):
            return all(part == "**" for part in second_parts[second_index:])
        if second_index == len(second_parts):
            return all(part == "**" for part in first_parts[first_index:])

        first_part = first_parts[first_index]
        second_part = second_parts[second_index]
        if first_part == "**" and second_part == "**":
            return (
                paths_overlap(first_index + 1, second_index)
                or paths_overlap(first_index, second_index + 1)
            )
        if first_part == "**":
            return (
                paths_overlap(first_index + 1, second_index)
                or paths_overlap(first_index, second_index + 1)
            )
        if second_part == "**":
            return (
                paths_overlap(first_index, second_index + 1)
                or paths_overlap(first_index + 1, second_index)
            )
        return segment_overlap(first_part, second_part) and paths_overlap(
            first_index + 1, second_index + 1
        )

    return paths_overlap(0, 0)


def _allowed_denied_overlap(allowed: str, denied: str) -> bool:
    if _identity(allowed) == ".env.example" and _identity(denied) in (
        ".env*",
        ".env.*",
    ):
        return False
    return _patterns_overlap(allowed, denied)


def _normalize_rules(values: Iterable[Any], field_name: str) -> tuple:
    if isinstance(values, (str, bytes)):
        raise ScopeError(f"{field_name} must be a sequence of paths")
    normalized = []
    identities = set()
    try:
        for value in values:
            rule = normalize_repo_path(value, allow_pattern=True)
            identity = _identity(rule)
            if identity in identities:
                raise ScopeError(
                    f"Duplicate {field_name} entry: {rule!r}"
                )
            identities.add(identity)
            normalized.append(rule)
    except TypeError as error:
        raise ScopeError(
            f"{field_name} must be a sequence of paths"
        ) from error
    return tuple(sorted(normalized, key=lambda item: (_identity(item), item)))


def _with_defaults(defaults: tuple, supplied: tuple) -> tuple:
    by_identity = {_identity(item): item for item in defaults}
    for item in supplied:
        by_identity.setdefault(_identity(item), item)
    return tuple(
        sorted(by_identity.values(), key=lambda item: (_identity(item), item))
    )


def _normalize_justifications(
    values: Mapping[Any, Any], allowed: tuple
) -> Mapping[str, str]:
    if not isinstance(values, Mapping):
        raise ScopeError("justifications must be a mapping")
    normalized = {}
    identities = {}
    for raw_path, raw_note in values.items():
        path = normalize_repo_path(raw_path, allow_pattern=True)
        identity = _identity(path)
        if identity in identities:
            raise ScopeError(f"Duplicate justification path: {path!r}")
        if not isinstance(raw_note, str) or not raw_note.strip():
            raise ScopeError(
                f"A non-empty justification is required for {path!r}"
            )
        identities[identity] = path
        normalized[path] = raw_note.strip()

    allowed_identities = {_identity(path): path for path in allowed}
    missing = set(allowed_identities) - set(identities)
    extra = set(identities) - set(allowed_identities)
    if missing:
        names = ", ".join(sorted(allowed_identities[item] for item in missing))
        raise ScopeError(f"Missing justification(s) for: {names}")
    if extra:
        names = ", ".join(sorted(identities[item] for item in extra))
        raise ScopeError(f"Unexpected justification(s) for: {names}")

    ordered = {
        path: normalized[identities[_identity(path)]]
        for path in allowed
    }
    return MappingProxyType(ordered)


@dataclass(frozen=True)
class ScopeDecision:
    """One deterministic create/modify scope decision."""

    path: str
    operation: str
    allowed: bool
    category: str
    matched_rule: Optional[str]
    explanation: str


@dataclass(frozen=True)
class FrozenScope:
    """Human-approved, deterministic write scope for one BuildJob."""

    allowed_new_files: tuple = ()
    allowed_existing_files: tuple = ()
    protected_files: tuple = DEFAULT_PROTECTED_FILES
    forbidden_paths: tuple = DEFAULT_FORBIDDEN_PATHS
    justifications: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed_new = _normalize_rules(
            self.allowed_new_files, "allowed_new_files"
        )
        allowed_existing = _normalize_rules(
            self.allowed_existing_files, "allowed_existing_files"
        )
        protected = _with_defaults(
            DEFAULT_PROTECTED_FILES,
            _normalize_rules(self.protected_files, "protected_files"),
        )
        forbidden = _with_defaults(
            DEFAULT_FORBIDDEN_PATHS,
            _normalize_rules(self.forbidden_paths, "forbidden_paths"),
        )

        for new_rule in allowed_new:
            for existing_rule in allowed_existing:
                if _patterns_overlap(new_rule, existing_rule):
                    raise ScopeError(
                        "Create and modify scopes overlap: "
                        f"{new_rule!r} and {existing_rule!r}"
                    )
        for allowed_rule in allowed_new + allowed_existing:
            for denied_rule in protected + forbidden:
                if _allowed_denied_overlap(allowed_rule, denied_rule):
                    raise ScopeError(
                        f"Allowed scope {allowed_rule!r} overlaps denied "
                        f"scope {denied_rule!r}"
                    )

        justifications = _normalize_justifications(
            self.justifications, allowed_new + allowed_existing
        )
        object.__setattr__(self, "allowed_new_files", allowed_new)
        object.__setattr__(self, "allowed_existing_files", allowed_existing)
        object.__setattr__(self, "protected_files", protected)
        object.__setattr__(self, "forbidden_paths", forbidden)
        object.__setattr__(self, "justifications", justifications)

    def to_dict(self) -> dict:
        return {
            "allowed_new_files": list(self.allowed_new_files),
            "allowed_existing_files": list(self.allowed_existing_files),
            "protected_files": list(self.protected_files),
            "forbidden_paths": list(self.forbidden_paths),
            "justifications": dict(self.justifications),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FrozenScope":
        if not isinstance(data, Mapping):
            raise ScopeError("A frozen scope must be a JSON object")
        fields = {
            "allowed_new_files",
            "allowed_existing_files",
            "protected_files",
            "forbidden_paths",
            "justifications",
        }
        unknown = set(data) - fields
        missing = fields - set(data)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ScopeError(f"Unknown frozen-scope field(s): {names}")
        if missing:
            names = ", ".join(sorted(missing))
            raise ScopeError(f"Missing frozen-scope field(s): {names}")
        return cls(**{name: data[name] for name in fields})

    def decision_for_create(self, path: Any) -> ScopeDecision:
        return self._decision(path, "create")

    def decision_for_modify(self, path: Any) -> ScopeDecision:
        return self._decision(path, "modify")

    def can_create(self, path: Any) -> bool:
        return self.decision_for_create(path).allowed

    def can_modify(self, path: Any) -> bool:
        return self.decision_for_modify(path).allowed

    def is_protected(self, path: Any) -> bool:
        normalized = normalize_repo_path(path)
        return (
            self._matching_denied_rule(normalized, self.protected_files)
            is not None
        )

    def is_forbidden(self, path: Any) -> bool:
        normalized = normalize_repo_path(path)
        return (
            self._matching_denied_rule(normalized, self.forbidden_paths)
            is not None
        )

    def is_forbidden_or_protected(self, path: Any) -> bool:
        return self.is_protected(path) or self.is_forbidden(path)

    def explain_create(self, path: Any) -> str:
        return self.decision_for_create(path).explanation

    def explain_modify(self, path: Any) -> str:
        return self.decision_for_modify(path).explanation

    def _matching_denied_rule(self, path: str, rules: tuple) -> Optional[str]:
        for rule in rules:
            if path == ".env.example" and rule in (".env*", ".env.*"):
                continue
            if _matches(rule, path, casefold=True):
                return rule
        return None

    def _decision(self, path: Any, operation: str) -> ScopeDecision:
        normalized = normalize_repo_path(path)
        protected = self._matching_denied_rule(
            normalized, self.protected_files
        )
        if protected is not None:
            return ScopeDecision(
                normalized,
                operation,
                False,
                "protected",
                protected,
                "Denied: "
                f"{normalized!r} matches protected rule {protected!r}.",
            )
        forbidden = self._matching_denied_rule(
            normalized, self.forbidden_paths
        )
        if forbidden is not None:
            return ScopeDecision(
                normalized,
                operation,
                False,
                "forbidden",
                forbidden,
                "Denied: "
                f"{normalized!r} matches forbidden rule {forbidden!r}.",
            )

        rules = (
            self.allowed_new_files
            if operation == "create"
            else self.allowed_existing_files
        )
        other_rules = (
            self.allowed_existing_files
            if operation == "create"
            else self.allowed_new_files
        )
        for rule in rules:
            if _matches(rule, normalized):
                return ScopeDecision(
                    normalized,
                    operation,
                    True,
                    "allowed",
                    rule,
                    f"Allowed to {operation}: matched approved rule {rule!r}.",
                )
        for rule in other_rules:
            if _matches(rule, normalized):
                other_operation = (
                    "modify" if operation == "create" else "create"
                )
                return ScopeDecision(
                    normalized,
                    operation,
                    False,
                    "wrong_operation",
                    rule,
                    "Denied: approved only for "
                    f"{other_operation} under {rule!r}.",
                )
        return ScopeDecision(
            normalized,
            operation,
            False,
            "outside_scope",
            None,
            "Denied: path is outside the frozen approved scope.",
        )
