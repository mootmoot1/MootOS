"""Continuous Builder System Model v1 (CB-028A–E).

THE SYSTEM OWNS TRUTH. THE WORKER ONLY PROPOSES CHANGES.

This module builds a descriptive, evidence-only model of a trusted repository
tree.  It does not authorize queue transitions, publication, GitHub, merge,
Main advancement, or worker-output trust.  Evidence is not authorization.

TRUST REVIEW (CB-028D): System Model is descriptive evidence and read-only
query surface.  It has no enforcement power over admission, queue, or
publication.  Therefore it stays OUTSIDE the TCB registry.  If a future
change grants it referee/enforcement authority, HOLD and expand TCB via
``create_mootos_tcb_registry_v1()`` only — never by duplicating protected
path lists here.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .paths import PathCanonicalizationError, canonicalize_repo_path
from .trusted_policy import (
    AUTHORITY_FLAGS as TCB_AUTHORITY_FLAGS,
    create_mootos_tcb_registry_v1,
)


class SystemModelError(ValueError):
    """Raised when System Model evidence cannot be produced safely."""


MODEL_VERSION = "cb-system-model-v1"
MAX_FILES = 4096
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_COMPONENTS = 512
MAX_EDGES = 8192
MAX_OWNERSHIP = 8192
MAX_UNCERTAINTIES = 512
MAX_MODEL_BYTES = 8 * 1024 * 1024
MAX_PATH_BYTES = 4096
MAX_COMPONENT_ID_BYTES = 128
MAX_QUERY_PATHS = 256

FILE_CATEGORIES = frozenset({
    "python_module",
    "python_package_init",
    "test",
    "script",
    "documentation",
    "config",
    "data",
    "frontend",
    "other",
    "excluded",
})

COMPONENT_KINDS = frozenset({
    "python_package",
    "continuous_builder_module",
    "scripts",
    "tests",
    "docs",
    "frontend",
    "config",
    "root",
    "other",
    "unknown",
})

OWNERSHIP_STATES = frozenset({
    "owned",
    "ambiguous",
    "unowned",
    "excluded",
    "unknown",
})

DEPENDENCY_KINDS = frozenset({
    "internal_import",
    "external_import",
    "unresolved_import",
    "ambiguous_import",
})

UNCERTAINTY_KINDS = frozenset({
    "ambiguous_ownership",
    "unresolved_import",
    "ambiguous_import",
    "missing_protected_path",
    "tcb_registry_mismatch",
    "skipped_non_regular",
    "bounded_truncation",
    "parse_failure",
    "possible_impact",
    "unknown",
})

IMPACT_STATES = frozenset({
    "impacted",
    "possible_impact",
    "not_impacted",
    "unknown",
})

AUTHORITY_FLAGS = TCB_AUTHORITY_FLAGS

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMPONENT_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_EXCLUDE_DIR_NAMES = frozenset({
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "node_modules",
    ".eggs",
    "dist",
    "build",
    ".coverage",
    "htmlcov",
    ".idea",
    ".vscode",
    ".cursor",
})
_EXCLUDE_FILE_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".egg-info",
)
_EXCLUDE_FILE_NAMES = frozenset({
    ".DS_Store",
    "Thumbs.db",
    "mootos.db-wal",
    "mootos.db-shm",
    "mootos.db-journal",
})
_EXCLUDE_NAME_MARKERS = (
    " 2.",
    " 2 ",
)
_MODEL_TOKEN = object()
_COMPONENT_TOKEN = object()
_FILE_TOKEN = object()
_EDGE_TOKEN = object()
_OWNERSHIP_TOKEN = object()
_UNCERTAINTY_TOKEN = object()
_SNAPSHOT_TOKEN = object()
_INVENTORY_TOKEN = object()
_QUERY_TOKEN = object()


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value, label):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SystemModelError(f"{label} is malformed")


def _require_no_authority(obj):
    for name in AUTHORITY_FLAGS:
        if getattr(obj, name, False) is not False:
            raise SystemModelError("system model cannot claim authority")


def _canonical_repo_path(value, label="path"):
    if not isinstance(value, str) or not value:
        raise SystemModelError(f"{label} is malformed")
    if len(value.encode("utf-8")) > MAX_PATH_BYTES:
        raise SystemModelError(f"{label} exceeds bound")
    try:
        canonical = canonicalize_repo_path(value)
    except PathCanonicalizationError as error:
        raise SystemModelError(f"{label} is unsafe") from error
    if canonical != value:
        raise SystemModelError(f"{label} is not canonical")
    return canonical


def _is_excluded_path(rel_path):
    segments = rel_path.split("/")
    if any(segment in _EXCLUDE_DIR_NAMES for segment in segments[:-1]):
        return True
    name = segments[-1]
    if name in _EXCLUDE_FILE_NAMES:
        return True
    if name.endswith(_EXCLUDE_FILE_SUFFIXES):
        return True
    if name.endswith("-wal") or name.endswith("-shm") or name.endswith("-journal"):
        if "mootos.db" in name or name.startswith("mootos.db"):
            return True
    lower = name.lower()
    if "job_created" in lower or "scope_frozen" in lower:
        return True
    for marker in _EXCLUDE_NAME_MARKERS:
        if marker in name:
            return True
    if name.endswith(" 2") or re.search(r" 2\.[^.]+$", name):
        return True
    return False


def _file_category(rel_path):
    if _is_excluded_path(rel_path):
        return "excluded"
    name = rel_path.split("/")[-1]
    if rel_path.startswith("tests/") or name.startswith("test_") or (
        name.endswith("_test.py")
    ):
        return "test"
    if rel_path.startswith("scripts/"):
        return "script"
    if rel_path.startswith("docs/") or name.endswith(".md"):
        return "documentation"
    if rel_path.startswith("frontend/"):
        return "frontend"
    if rel_path.startswith("config/") or name in (
        "requirements.txt",
        "requirements-dev.txt",
        "railway.toml",
        ".gitignore",
        ".env.example",
    ):
        return "config"
    if name.endswith(".py"):
        if name == "__init__.py":
            return "python_package_init"
        return "python_module"
    if name.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".cfg")):
        return "config"
    if name.endswith((".db", ".sqlite", ".csv", ".bin")):
        return "data"
    return "other"


def _python_package_hint(rel_path):
    if not rel_path.endswith(".py"):
        return None
    parts = rel_path.split("/")
    if parts[0] not in ("backend", "scripts", "tests"):
        # Still allow nested packages under backend
        pass
    if parts[-1] == "__init__.py":
        pkg = ".".join(parts[:-1])
        return pkg or None
    if len(parts) >= 2:
        # module inside a package directory
        return ".".join(parts[:-1])
    return None


def _component_id_for_path(rel_path):
    parts = rel_path.split("/")
    if parts[0] == "backend" and len(parts) >= 2:
        if parts[1] == "continuous_builder" and len(parts) >= 3:
            return "backend.continuous_builder"
        return f"backend.{parts[1]}" if parts[1].endswith(".py") is False else "backend"
    if parts[0] == "tests":
        return "tests"
    if parts[0] == "scripts":
        return "scripts"
    if parts[0] == "docs":
        return "docs"
    if parts[0] == "frontend":
        return "frontend"
    if parts[0] == "config":
        return "config"
    if parts[0] == "database":
        return "database"
    if parts[0] == "capability_specs":
        return "capability_specs"
    if len(parts) == 1:
        return "root"
    return f"other.{parts[0]}"


def _component_kind(component_id):
    if component_id == "backend.continuous_builder":
        return "continuous_builder_module"
    if component_id.startswith("backend."):
        return "python_package"
    if component_id == "tests":
        return "tests"
    if component_id == "scripts":
        return "scripts"
    if component_id == "docs":
        return "docs"
    if component_id == "frontend":
        return "frontend"
    if component_id == "config":
        return "config"
    if component_id == "root":
        return "root"
    if component_id.startswith("other."):
        return "other"
    return "unknown"


# ---------------------------------------------------------------------------
# CB-028A contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepositoryFileRecord:
    """One immutable inventory record for a regular repository file."""

    path: str
    content_sha256: str
    size_bytes: int
    category: str
    python_package_hint: str | None
    is_tcb: bool
    excluded: bool
    record_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _FILE_TOKEN:
            raise SystemModelError(
                "file record requires trusted system construction"
            )
        path = _canonical_repo_path(self.path, "file path")
        object.__setattr__(self, "path", path)
        _require_sha256(self.content_sha256, "content digest")
        _require_sha256(self.record_sha256, "record digest")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise SystemModelError("size_bytes is malformed")
        if self.size_bytes > MAX_FILE_BYTES and not self.excluded:
            raise SystemModelError("file exceeds bound")
        if self.category not in FILE_CATEGORIES:
            raise SystemModelError("file category is unsupported")
        if self.python_package_hint is not None:
            if (
                not isinstance(self.python_package_hint, str)
                or not self.python_package_hint
                or len(self.python_package_hint.encode("utf-8"))
                > MAX_COMPONENT_ID_BYTES
            ):
                raise SystemModelError("python package hint is malformed")
        if type(self.is_tcb) is not bool or type(self.excluded) is not bool:
            raise SystemModelError("file flags must be boolean")
        if self.record_sha256 != _digest(self._payload()):
            raise SystemModelError("file record digest mismatch")

    def _body(self):
        return {
            "category": self.category,
            "content_sha256": self.content_sha256,
            "excluded": self.excluded,
            "is_tcb": self.is_tcb,
            "path": self.path,
            "python_package_hint": self.python_package_hint,
            "size_bytes": self.size_bytes,
        }

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["record_sha256"] = self.record_sha256
        return body


def _seal_file_record(
    *,
    path,
    content_sha256,
    size_bytes,
    category,
    python_package_hint,
    is_tcb,
    excluded,
):
    values = {
        "path": path,
        "content_sha256": content_sha256,
        "size_bytes": size_bytes,
        "category": category,
        "python_package_hint": python_package_hint,
        "is_tcb": is_tcb,
        "excluded": excluded,
    }
    provisional = object.__new__(RepositoryFileRecord)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return RepositoryFileRecord(
        **values,
        record_sha256=_digest(provisional._payload()),
        _token=_FILE_TOKEN,
    )


@dataclass(frozen=True)
class SystemComponent:
    """One immutable system component derived from trusted tree evidence."""

    component_id: str
    kind: str
    root_path: str
    file_paths: tuple
    ownership_state: str
    component_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _COMPONENT_TOKEN:
            raise SystemModelError(
                "system component requires trusted system construction"
            )
        if (
            not isinstance(self.component_id, str)
            or _COMPONENT_ID.fullmatch(self.component_id) is None
            or len(self.component_id.encode("utf-8")) > MAX_COMPONENT_ID_BYTES
        ):
            raise SystemModelError("component ID is malformed")
        if self.kind not in COMPONENT_KINDS:
            raise SystemModelError("component kind is unsupported")
        if self.ownership_state not in OWNERSHIP_STATES:
            raise SystemModelError("ownership state is unsupported")
        root = _canonical_repo_path(self.root_path, "component root")
        object.__setattr__(self, "root_path", root)
        if type(self.file_paths) is not tuple:
            raise SystemModelError("component file_paths malformed")
        if len(self.file_paths) > MAX_FILES:
            raise SystemModelError("component exceeds file bound")
        normalized = tuple(
            _canonical_repo_path(path, "component file")
            for path in self.file_paths
        )
        if normalized != tuple(sorted(set(normalized))):
            raise SystemModelError("component files are not canonical")
        if len({path.casefold() for path in normalized}) != len(normalized):
            raise SystemModelError("component files collide by case")
        object.__setattr__(self, "file_paths", normalized)
        _require_sha256(self.component_sha256, "component digest")
        if self.component_sha256 != _digest(self._payload()):
            raise SystemModelError("component digest mismatch")

    def _body(self):
        return {
            "component_id": self.component_id,
            "file_paths": list(self.file_paths),
            "kind": self.kind,
            "ownership_state": self.ownership_state,
            "root_path": self.root_path,
        }

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["component_sha256"] = self.component_sha256
        return body


def _seal_component(
    *,
    component_id,
    kind,
    root_path,
    file_paths,
    ownership_state,
):
    ordered = tuple(sorted(set(file_paths)))
    values = {
        "component_id": component_id,
        "kind": kind,
        "root_path": root_path,
        "file_paths": ordered,
        "ownership_state": ownership_state,
    }
    provisional = object.__new__(SystemComponent)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return SystemComponent(
        **values,
        component_sha256=_digest(provisional._payload()),
        _token=_COMPONENT_TOKEN,
    )


@dataclass(frozen=True)
class DependencyEdge:
    """One immutable static dependency edge."""

    source_component_id: str
    target_component_id: str | None
    source_path: str
    imported_name: str
    kind: str
    edge_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _EDGE_TOKEN:
            raise SystemModelError(
                "dependency edge requires trusted system construction"
            )
        if (
            not isinstance(self.source_component_id, str)
            or _COMPONENT_ID.fullmatch(self.source_component_id) is None
        ):
            raise SystemModelError("source component ID is malformed")
        if self.target_component_id is not None:
            if (
                not isinstance(self.target_component_id, str)
                or _COMPONENT_ID.fullmatch(self.target_component_id) is None
            ):
                raise SystemModelError("target component ID is malformed")
        _canonical_repo_path(self.source_path, "edge source path")
        if (
            not isinstance(self.imported_name, str)
            or not self.imported_name
            or len(self.imported_name.encode("utf-8")) > MAX_COMPONENT_ID_BYTES
        ):
            raise SystemModelError("imported name is malformed")
        if self.kind not in DEPENDENCY_KINDS:
            raise SystemModelError("dependency kind is unsupported")
        if self.kind == "internal_import" and self.target_component_id is None:
            raise SystemModelError("internal import requires target")
        if self.kind in ("external_import", "unresolved_import") and (
            self.target_component_id is not None
        ):
            raise SystemModelError("external/unresolved must not bind target")
        _require_sha256(self.edge_sha256, "edge digest")
        if self.edge_sha256 != _digest(self._payload()):
            raise SystemModelError("edge digest mismatch")

    def _body(self):
        return {
            "imported_name": self.imported_name,
            "kind": self.kind,
            "source_component_id": self.source_component_id,
            "source_path": self.source_path,
            "target_component_id": self.target_component_id,
        }

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["edge_sha256"] = self.edge_sha256
        return body


def _seal_edge(
    *,
    source_component_id,
    target_component_id,
    source_path,
    imported_name,
    kind,
):
    values = {
        "source_component_id": source_component_id,
        "target_component_id": target_component_id,
        "source_path": source_path,
        "imported_name": imported_name,
        "kind": kind,
    }
    provisional = object.__new__(DependencyEdge)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return DependencyEdge(
        **values,
        edge_sha256=_digest(provisional._payload()),
        _token=_EDGE_TOKEN,
    )


@dataclass(frozen=True)
class OwnershipRecord:
    """Path ownership evidence — never invents certainty."""

    path: str
    component_id: str | None
    state: str
    ownership_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _OWNERSHIP_TOKEN:
            raise SystemModelError(
                "ownership record requires trusted system construction"
            )
        _canonical_repo_path(self.path, "ownership path")
        if self.state not in OWNERSHIP_STATES:
            raise SystemModelError("ownership state is unsupported")
        if self.state == "owned":
            if (
                not isinstance(self.component_id, str)
                or _COMPONENT_ID.fullmatch(self.component_id) is None
            ):
                raise SystemModelError("owned path requires component")
        if self.state in ("unowned", "excluded", "unknown"):
            if self.component_id is not None:
                raise SystemModelError(
                    f"{self.state} ownership must not bind component"
                )
        if self.state == "ambiguous" and self.component_id is not None:
            # Ambiguous may optionally name a contested primary; keep None.
            raise SystemModelError(
                "ambiguous ownership must not claim sole component"
            )
        _require_sha256(self.ownership_sha256, "ownership digest")
        if self.ownership_sha256 != _digest(self._payload()):
            raise SystemModelError("ownership digest mismatch")

    def _body(self):
        return {
            "component_id": self.component_id,
            "path": self.path,
            "state": self.state,
        }

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["ownership_sha256"] = self.ownership_sha256
        return body


def _seal_ownership(*, path, component_id, state):
    values = {
        "path": path,
        "component_id": component_id,
        "state": state,
    }
    provisional = object.__new__(OwnershipRecord)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return OwnershipRecord(
        **values,
        ownership_sha256=_digest(provisional._payload()),
        _token=_OWNERSHIP_TOKEN,
    )


@dataclass(frozen=True)
class UncertaintyRecord:
    """Explicit uncertainty — never silently upgraded to certainty."""

    kind: str
    subject: str
    detail_code: str
    uncertainty_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _UNCERTAINTY_TOKEN:
            raise SystemModelError(
                "uncertainty record requires trusted system construction"
            )
        if self.kind not in UNCERTAINTY_KINDS:
            raise SystemModelError("uncertainty kind is unsupported")
        if (
            not isinstance(self.subject, str)
            or not self.subject
            or len(self.subject.encode("utf-8")) > MAX_PATH_BYTES
        ):
            raise SystemModelError("uncertainty subject is malformed")
        if (
            not isinstance(self.detail_code, str)
            or not self.detail_code
            or len(self.detail_code.encode("utf-8")) > MAX_COMPONENT_ID_BYTES
        ):
            raise SystemModelError("uncertainty detail is malformed")
        _require_sha256(self.uncertainty_sha256, "uncertainty digest")
        if self.uncertainty_sha256 != _digest(self._payload()):
            raise SystemModelError("uncertainty digest mismatch")

    def _body(self):
        return {
            "detail_code": self.detail_code,
            "kind": self.kind,
            "subject": self.subject,
        }

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["uncertainty_sha256"] = self.uncertainty_sha256
        return body


def _seal_uncertainty(*, kind, subject, detail_code):
    values = {
        "kind": kind,
        "subject": subject,
        "detail_code": detail_code,
    }
    provisional = object.__new__(UncertaintyRecord)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return UncertaintyRecord(
        **values,
        uncertainty_sha256=_digest(provisional._payload()),
        _token=_UNCERTAINTY_TOKEN,
    )


@dataclass(frozen=True)
class RepositoryInventory:
    """Deterministic inventory sealed from a trusted repository root."""

    files: tuple
    inventory_sha256: str
    file_count: int
    total_bytes: int
    excluded_count: int
    tcb_file_count: int
    root_fingerprint: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _INVENTORY_TOKEN:
            raise SystemModelError(
                "inventory requires trusted system construction"
            )
        if type(self.files) is not tuple:
            raise SystemModelError("inventory files malformed")
        if len(self.files) > MAX_FILES:
            raise SystemModelError("inventory exceeds file bound")
        if any(not isinstance(item, RepositoryFileRecord) for item in self.files):
            raise SystemModelError("inventory files invalid")
        paths = tuple(item.path for item in self.files)
        if paths != tuple(sorted(set(paths))):
            raise SystemModelError("inventory paths are not canonical")
        if len({path.casefold() for path in paths}) != len(paths):
            raise SystemModelError("inventory paths collide by case")
        if self.file_count != len(self.files):
            raise SystemModelError("inventory file_count mismatch")
        expected_bytes = sum(item.size_bytes for item in self.files)
        if self.total_bytes != expected_bytes:
            raise SystemModelError("inventory total_bytes mismatch")
        if self.total_bytes > MAX_TOTAL_BYTES:
            raise SystemModelError("inventory exceeds byte bound")
        if self.excluded_count != sum(1 for item in self.files if item.excluded):
            raise SystemModelError("excluded_count mismatch")
        if self.tcb_file_count != sum(1 for item in self.files if item.is_tcb):
            raise SystemModelError("tcb_file_count mismatch")
        _require_sha256(self.root_fingerprint, "root fingerprint")
        _require_sha256(self.inventory_sha256, "inventory digest")
        if self.inventory_sha256 != _digest(self._payload()):
            raise SystemModelError("inventory digest mismatch")

    def _body(self):
        return {
            "excluded_count": self.excluded_count,
            "file_count": self.file_count,
            "files": [item.to_dict() for item in self.files],
            "root_fingerprint": self.root_fingerprint,
            "tcb_file_count": self.tcb_file_count,
            "total_bytes": self.total_bytes,
        }

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["inventory_sha256"] = self.inventory_sha256
        return body


def _seal_inventory(*, files, root_fingerprint):
    ordered = tuple(sorted(files, key=lambda item: item.path))
    values = {
        "files": ordered,
        "file_count": len(ordered),
        "total_bytes": sum(item.size_bytes for item in ordered),
        "excluded_count": sum(1 for item in ordered if item.excluded),
        "tcb_file_count": sum(1 for item in ordered if item.is_tcb),
        "root_fingerprint": root_fingerprint,
    }
    provisional = object.__new__(RepositoryInventory)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return RepositoryInventory(
        **values,
        inventory_sha256=_digest(provisional._payload()),
        _token=_INVENTORY_TOKEN,
    )


@dataclass(frozen=True)
class SystemModel:
    """Immutable System Model bound to a trusted repo root and base SHA.

    Zero authority.  Descriptive evidence only.
    """

    model_version: str
    base_sha: str
    root_fingerprint: str
    inventory: RepositoryInventory
    components: tuple
    ownership: tuple
    dependency_edges: tuple
    uncertainties: tuple
    tcb_registry_sha256: str
    model_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _MODEL_TOKEN:
            raise SystemModelError(
                "system model requires trusted system construction"
            )
        if self.model_version != MODEL_VERSION:
            raise SystemModelError("model version is unsupported")
        _require_sha256(self.base_sha, "base_sha")
        _require_sha256(self.root_fingerprint, "root fingerprint")
        _require_sha256(self.tcb_registry_sha256, "tcb registry digest")
        _require_sha256(self.model_sha256, "model digest")
        if not isinstance(self.inventory, RepositoryInventory):
            raise SystemModelError("inventory is invalid")
        if self.inventory.root_fingerprint != self.root_fingerprint:
            raise SystemModelError("inventory root fingerprint mismatch")
        if type(self.components) is not tuple or len(self.components) > MAX_COMPONENTS:
            raise SystemModelError("components malformed or over bound")
        if any(not isinstance(item, SystemComponent) for item in self.components):
            raise SystemModelError("components invalid")
        ids = tuple(item.component_id for item in self.components)
        if ids != tuple(sorted(set(ids))):
            raise SystemModelError("component IDs are not canonical")
        if type(self.ownership) is not tuple or len(self.ownership) > MAX_OWNERSHIP:
            raise SystemModelError("ownership malformed or over bound")
        if any(not isinstance(item, OwnershipRecord) for item in self.ownership):
            raise SystemModelError("ownership invalid")
        ownership_paths = tuple(item.path for item in self.ownership)
        if ownership_paths != tuple(sorted(set(ownership_paths))):
            raise SystemModelError("ownership paths are not canonical")
        if type(self.dependency_edges) is not tuple or (
            len(self.dependency_edges) > MAX_EDGES
        ):
            raise SystemModelError("edges malformed or over bound")
        if any(
            not isinstance(item, DependencyEdge)
            for item in self.dependency_edges
        ):
            raise SystemModelError("edges invalid")
        if type(self.uncertainties) is not tuple or (
            len(self.uncertainties) > MAX_UNCERTAINTIES
        ):
            raise SystemModelError("uncertainties malformed or over bound")
        if any(
            not isinstance(item, UncertaintyRecord)
            for item in self.uncertainties
        ):
            raise SystemModelError("uncertainties invalid")
        _require_no_authority(self)
        # Bind TCB registry digest to the live canonical registry.
        live = create_mootos_tcb_registry_v1()
        if self.tcb_registry_sha256 != live.registry_sha256:
            raise SystemModelError("tcb registry digest mismatch")
        if self.model_sha256 != _digest(self._payload()):
            raise SystemModelError("model digest mismatch")
        if len(self.canonical_bytes()) > MAX_MODEL_BYTES:
            raise SystemModelError("model exceeds byte bound")

    def _body(self):
        return {
            "base_sha": self.base_sha,
            "components": [item.to_dict() for item in self.components],
            "dependency_edges": [
                item.to_dict() for item in self.dependency_edges
            ],
            "github_authorized": False,
            "inventory": self.inventory.to_dict(),
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "model_version": MODEL_VERSION,
            "ownership": [item.to_dict() for item in self.ownership],
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "root_fingerprint": self.root_fingerprint,
            "tcb_registry_sha256": self.tcb_registry_sha256,
            "uncertainties": [item.to_dict() for item in self.uncertainties],
            "worker_output_trusted": False,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        body = self._body()
        body["model_sha256"] = self.model_sha256
        return _canonical(body)

    def to_dict(self):
        body = self._body()
        body["model_sha256"] = self.model_sha256
        return body


def _seal_model(
    *,
    base_sha,
    root_fingerprint,
    inventory,
    components,
    ownership,
    dependency_edges,
    uncertainties,
    tcb_registry_sha256,
):
    ordered_components = tuple(
        sorted(components, key=lambda item: item.component_id)
    )
    ordered_ownership = tuple(sorted(ownership, key=lambda item: item.path))
    ordered_edges = tuple(
        sorted(
            dependency_edges,
            key=lambda item: (
                item.source_component_id,
                item.imported_name,
                item.source_path,
                item.kind,
                item.target_component_id or "",
            ),
        )
    )
    ordered_uncertainties = tuple(
        sorted(
            uncertainties,
            key=lambda item: (item.kind, item.subject, item.detail_code),
        )
    )
    values = {
        "model_version": MODEL_VERSION,
        "base_sha": base_sha,
        "root_fingerprint": root_fingerprint,
        "inventory": inventory,
        "components": ordered_components,
        "ownership": ordered_ownership,
        "dependency_edges": ordered_edges,
        "uncertainties": ordered_uncertainties,
        "tcb_registry_sha256": tcb_registry_sha256,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(SystemModel)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return SystemModel(
        **values,
        model_sha256=_digest(provisional._payload()),
        _token=_MODEL_TOKEN,
    )


@dataclass(frozen=True)
class SystemModelSnapshot:
    """Evidence-only snapshot of a sealed System Model (no timestamps)."""

    model_sha256: str
    model_version: str
    base_sha: str
    root_fingerprint: str
    tcb_registry_sha256: str
    file_count: int
    component_count: int
    edge_count: int
    uncertainty_count: int
    snapshot_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _SNAPSHOT_TOKEN:
            raise SystemModelError(
                "snapshot requires trusted derived evidence"
            )
        if self.model_version != MODEL_VERSION:
            raise SystemModelError("snapshot model version unsupported")
        for value, label in (
            (self.model_sha256, "model digest"),
            (self.base_sha, "base_sha"),
            (self.root_fingerprint, "root fingerprint"),
            (self.tcb_registry_sha256, "tcb registry digest"),
            (self.snapshot_sha256, "snapshot digest"),
        ):
            _require_sha256(value, label)
        for name in (
            "file_count",
            "component_count",
            "edge_count",
            "uncertainty_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise SystemModelError(f"{name} is malformed")
        _require_no_authority(self)
        if self.snapshot_sha256 != _digest(self._payload()):
            raise SystemModelError("snapshot digest mismatch")

    def _body(self):
        return {
            "base_sha": self.base_sha,
            "component_count": self.component_count,
            "edge_count": self.edge_count,
            "file_count": self.file_count,
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "model_sha256": self.model_sha256,
            "model_version": MODEL_VERSION,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "root_fingerprint": self.root_fingerprint,
            "tcb_registry_sha256": self.tcb_registry_sha256,
            "uncertainty_count": self.uncertainty_count,
            "worker_output_trusted": False,
        }

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["snapshot_sha256"] = self.snapshot_sha256
        return body


def create_system_model_snapshot(model):
    """Seal an evidence-only snapshot from a trusted SystemModel."""
    if not isinstance(model, SystemModel):
        raise SystemModelError("model is invalid")
    values = {
        "model_sha256": model.model_sha256,
        "model_version": model.model_version,
        "base_sha": model.base_sha,
        "root_fingerprint": model.root_fingerprint,
        "tcb_registry_sha256": model.tcb_registry_sha256,
        "file_count": model.inventory.file_count,
        "component_count": len(model.components),
        "edge_count": len(model.dependency_edges),
        "uncertainty_count": len(model.uncertainties),
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(SystemModelSnapshot)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return SystemModelSnapshot(
        **values,
        snapshot_sha256=_digest(provisional._payload()),
        _token=_SNAPSHOT_TOKEN,
    )




# ---------------------------------------------------------------------------
# CB-028B inventory from trusted repo root
# ---------------------------------------------------------------------------


def _root_fingerprint(repo_root: Path) -> str:
    resolved = repo_root.resolve(strict=True)
    if not resolved.is_dir():
        raise SystemModelError("repo root must be a directory")
    # Fingerprint binds absolute resolved path text only (no mtime/timestamps).
    return _digest(str(resolved).encode("utf-8"))


def _safe_rel_path(repo_root: Path, full: Path) -> str | None:
    try:
        rel = full.relative_to(repo_root)
    except ValueError:
        return None
    text = rel.as_posix()
    if text.startswith("../") or text == ".." or text.startswith("/"):
        return None
    try:
        return _canonical_repo_path(text, "inventory path")
    except SystemModelError:
        return None


def build_repository_inventory(repo_root, *, include_excluded=False):
    """Build a deterministic inventory from a trusted repository root.

    Walks only regular files under ``repo_root``.  Symlinks are skipped
    (never followed).  Does not import or execute repository modules.
    Does not use network or credentials.  Worker-supplied inventories are
    never accepted — callers must pass a filesystem root the system trusts.
    """
    if not isinstance(repo_root, (str, Path)) or not repo_root:
        raise SystemModelError("repo root is malformed")
    root = Path(repo_root)
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SystemModelError("repo root is unresolvable") from error
    if not root.is_dir():
        raise SystemModelError("repo root must be a directory")

    registry = create_mootos_tcb_registry_v1()
    protected = set(registry.protected_paths)
    fingerprint = _root_fingerprint(root)

    collected = []
    total_bytes = 0
    # Deterministic walk: sort directory iteration.
    stack = [root]
    seen_dirs = {root}
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError as error:
            raise SystemModelError("directory listing failed") from error
        for entry in entries:
            # Never follow symlinks.
            if entry.is_symlink():
                continue
            if entry.is_dir():
                name = entry.name
                if name in _EXCLUDE_DIR_NAMES:
                    continue
                resolved = entry.resolve(strict=False)
                try:
                    resolved.relative_to(root)
                except ValueError:
                    # Escape outside root — skip.
                    continue
                if resolved in seen_dirs:
                    continue
                seen_dirs.add(resolved)
                stack.append(entry)
                continue
            if not entry.is_file():
                continue
            rel = _safe_rel_path(root, entry)
            if rel is None:
                continue
            excluded = _is_excluded_path(rel)
            if excluded and not include_excluded:
                # Still track excluded as records when include_excluded;
                # default inventory omits excluded paths entirely for bound.
                continue
            try:
                size = entry.stat().st_size
            except OSError as error:
                raise SystemModelError("stat failed") from error
            if size > MAX_FILE_BYTES:
                raise SystemModelError("file exceeds bound")
            total_bytes += size
            if total_bytes > MAX_TOTAL_BYTES:
                raise SystemModelError("inventory exceeds byte bound")
            if len(collected) >= MAX_FILES:
                raise SystemModelError("inventory exceeds file bound")
            # Read content for digest — no exec/import.
            try:
                data = entry.read_bytes()
            except OSError as error:
                raise SystemModelError("read failed") from error
            if len(data) != size:
                raise SystemModelError("size changed during read")
            category = _file_category(rel)
            if excluded:
                category = "excluded"
            collected.append(
                _seal_file_record(
                    path=rel,
                    content_sha256=_digest(data),
                    size_bytes=size,
                    category=category,
                    python_package_hint=(
                        None if excluded else _python_package_hint(rel)
                    ),
                    is_tcb=rel in protected,
                    excluded=excluded,
                )
            )

    files = tuple(sorted(collected, key=lambda item: item.path))
    if len({item.path.casefold() for item in files}) != len(files):
        raise SystemModelError("inventory paths collide by case")
    return _seal_inventory(files=files, root_fingerprint=fingerprint)


# ---------------------------------------------------------------------------
# CB-028C ownership + static dependency graph
# ---------------------------------------------------------------------------


def _module_name_from_path(rel_path):
    if not rel_path.endswith(".py"):
        return None
    parts = rel_path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    return ".".join(parts)


def _resolve_import_to_component(imported_name, component_ids):
    """Conservatively map an import name to an internal component.

    Returns (kind, target_component_id).
    Never invents certainty for ambiguous cases.
    """
    if not imported_name or not isinstance(imported_name, str):
        return "unresolved_import", None
    # Stdlib / external heuristic: top-level not in known internal roots.
    top = imported_name.split(".", 1)[0]
    internal_roots = {
        "backend",
        "scripts",
        "tests",
        "frontend",
        "config",
        "database",
        "capability_specs",
    }
    if top not in internal_roots:
        return "external_import", None

    # Prefer longest matching component id derived from import prefixes.
    candidates = []
    # Map common patterns:
    # backend.continuous_builder.foo -> backend.continuous_builder
    # backend.foo -> backend.foo (package) or backend
    if imported_name.startswith("backend.continuous_builder"):
        cid = "backend.continuous_builder"
        if cid in component_ids:
            candidates.append(cid)
    elif imported_name.startswith("backend."):
        rest = imported_name[len("backend."):].split(".", 1)[0]
        cid = f"backend.{rest}"
        if cid in component_ids:
            candidates.append(cid)
        elif "backend" in component_ids:
            candidates.append("backend")
    elif imported_name.startswith("tests"):
        if "tests" in component_ids:
            candidates.append("tests")
    elif imported_name.startswith("scripts"):
        if "scripts" in component_ids:
            candidates.append("scripts")

    # Also try exact package-hint style component match on prefixes.
    parts = imported_name.split(".")
    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in component_ids and prefix not in candidates:
            candidates.append(prefix)

    unique = []
    for item in candidates:
        if item not in unique:
            unique.append(item)
    if len(unique) == 1:
        return "internal_import", unique[0]
    if len(unique) > 1:
        return "ambiguous_import", None
    return "unresolved_import", None


def _parse_python_imports(source_bytes):
    """Return sorted unique absolute/imported module names (static only)."""
    try:
        text = source_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None  # signal parse_failure
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative imports: record as unresolved/ambiguous unless
                # we can reconstruct — keep conservative.
                if node.module:
                    names.add(f".{node.module}")
                else:
                    names.add(".")
            elif node.module:
                names.add(node.module)
    return tuple(sorted(names))


def _build_components_and_ownership(inventory):
    groups = {}
    ambiguities = {}
    for record in inventory.files:
        if record.excluded:
            continue
        cid = _component_id_for_path(record.path)
        # Detect path that could map to multiple ids (should not happen with
        # deterministic function, but keep explicit ambiguity channel).
        if record.path in ambiguities:
            ambiguities[record.path].add(cid)
        else:
            # Check casefold collision across different components later.
            groups.setdefault(cid, []).append(record.path)

    # Casefold ownership collisions across components => ambiguous.
    case_map = {}
    for cid, paths in groups.items():
        for path in paths:
            key = path.casefold()
            case_map.setdefault(key, set()).add(cid)

    components = []
    ownership = []
    uncertainties = []

    claimed = {}
    for cid in sorted(groups):
        paths = sorted(set(groups[cid]))
        clean_paths = []
        for path in paths:
            owners = case_map.get(path.casefold(), {cid})
            if len(owners) > 1:
                ownership.append(
                    _seal_ownership(
                        path=path, component_id=None, state="ambiguous"
                    )
                )
                uncertainties.append(
                    _seal_uncertainty(
                        kind="ambiguous_ownership",
                        subject=path,
                        detail_code="casefold_or_multi_owner",
                    )
                )
            else:
                clean_paths.append(path)
                claimed[path] = cid
                ownership.append(
                    _seal_ownership(
                        path=path, component_id=cid, state="owned"
                    )
                )
        root_path = {
            "backend.continuous_builder": "backend/continuous_builder",
            "tests": "tests",
            "scripts": "scripts",
            "docs": "docs",
            "frontend": "frontend",
            "config": "config",
            "database": "database",
            "capability_specs": "capability_specs",
            "root": "README.md",
        }.get(cid)
        if root_path is None:
            if cid.startswith("backend."):
                root_path = "backend/" + cid.split(".", 1)[1]
            elif cid.startswith("other."):
                root_path = cid.split(".", 1)[1]
            else:
                root_path = cid.replace(".", "/")
        # Ensure root_path is a real file or directory marker present in inventory.
        # Prefer first owned file under component if root missing as file.
        inventory_paths = {item.path for item in inventory.files}
        if root_path not in inventory_paths:
            if clean_paths:
                # Use lexicographically first path as binding root evidence.
                root_path = clean_paths[0]
            else:
                continue
        components.append(
            _seal_component(
                component_id=cid,
                kind=_component_kind(cid),
                root_path=root_path,
                file_paths=tuple(clean_paths),
                ownership_state="owned" if clean_paths else "unknown",
            )
        )

    for record in inventory.files:
        if record.excluded:
            ownership.append(
                _seal_ownership(
                    path=record.path, component_id=None, state="excluded"
                )
            )
            continue
        if record.path not in claimed and not any(
            item.path == record.path and item.state == "ambiguous"
            for item in ownership
        ):
            ownership.append(
                _seal_ownership(
                    path=record.path, component_id=None, state="unowned"
                )
            )

    return tuple(components), tuple(ownership), list(uncertainties)


def _build_dependency_edges(repo_root, inventory, components, uncertainties):
    root = Path(repo_root).resolve(strict=True)
    component_ids = {item.component_id for item in components}
    path_to_component = {}
    for item in components:
        for path in item.file_paths:
            path_to_component[path] = item.component_id

    edges = []
    seen = set()
    for record in inventory.files:
        if record.excluded or record.category not in (
            "python_module",
            "python_package_init",
            "test",
            "script",
        ):
            continue
        if not record.path.endswith(".py"):
            continue
        source_cid = path_to_component.get(record.path)
        if source_cid is None:
            continue
        full = root / record.path
        if full.is_symlink() or not full.is_file():
            uncertainties.append(
                _seal_uncertainty(
                    kind="skipped_non_regular",
                    subject=record.path,
                    detail_code="dependency_scan_skip",
                )
            )
            continue
        try:
            data = full.read_bytes()
        except OSError:
            uncertainties.append(
                _seal_uncertainty(
                    kind="parse_failure",
                    subject=record.path,
                    detail_code="read_failed",
                )
            )
            continue
        if len(data) > MAX_FILE_BYTES:
            uncertainties.append(
                _seal_uncertainty(
                    kind="bounded_truncation",
                    subject=record.path,
                    detail_code="file_too_large_for_parse",
                )
            )
            continue
        imported = _parse_python_imports(data)
        if imported is None:
            uncertainties.append(
                _seal_uncertainty(
                    kind="parse_failure",
                    subject=record.path,
                    detail_code="ast_parse_failed",
                )
            )
            continue
        for name in imported:
            # Relative import markers stay unresolved/ambiguous.
            if name.startswith("."):
                kind = "ambiguous_import" if name != "." else "unresolved_import"
                target = None
                uncertainties.append(
                    _seal_uncertainty(
                        kind=kind,
                        subject=f"{record.path}:{name}",
                        detail_code="relative_import",
                    )
                )
            else:
                kind, target = _resolve_import_to_component(name, component_ids)
                if kind in ("unresolved_import", "ambiguous_import"):
                    uncertainties.append(
                        _seal_uncertainty(
                            kind=kind,
                            subject=f"{record.path}:{name}",
                            detail_code="import_resolution",
                        )
                    )
            # Skip self-edges for internal same-component imports to keep
            # the graph small and inspectable — still record external ones.
            if kind == "internal_import" and target == source_cid:
                continue
            key = (source_cid, target, record.path, name, kind)
            if key in seen:
                continue
            seen.add(key)
            if len(edges) >= MAX_EDGES:
                uncertainties.append(
                    _seal_uncertainty(
                        kind="bounded_truncation",
                        subject=record.path,
                        detail_code="edge_bound_reached",
                    )
                )
                return edges, uncertainties
            edges.append(
                _seal_edge(
                    source_component_id=source_cid,
                    target_component_id=target,
                    source_path=record.path,
                    imported_name=name,
                    kind=kind,
                )
            )
    return edges, uncertainties


def _check_missing_protected_paths(inventory, uncertainties):
    registry = create_mootos_tcb_registry_v1()
    present = {item.path for item in inventory.files if not item.excluded}
    for path in registry.protected_paths:
        if path not in present:
            uncertainties.append(
                _seal_uncertainty(
                    kind="missing_protected_path",
                    subject=path,
                    detail_code="tcb_path_absent_from_inventory",
                )
            )
    return uncertainties


def build_system_model(repo_root, *, base_sha, include_excluded=False):
    """Build a sealed System Model from a trusted repository root.

    ``base_sha`` must be the trusted git commit the caller binds.  The model
    never authorizes action.  TCB membership uses only
    ``create_mootos_tcb_registry_v1()``.
    """
    _require_sha256(base_sha, "base_sha")
    inventory = build_repository_inventory(
        repo_root, include_excluded=include_excluded
    )
    registry = create_mootos_tcb_registry_v1()
    components, ownership, uncertainties = _build_components_and_ownership(
        inventory
    )
    edges, uncertainties = _build_dependency_edges(
        repo_root, inventory, components, uncertainties
    )
    uncertainties = _check_missing_protected_paths(inventory, uncertainties)
    # Dedup uncertainties by body.
    uniq = {}
    for item in uncertainties:
        uniq[(item.kind, item.subject, item.detail_code)] = item
    if len(uniq) > MAX_UNCERTAINTIES:
        raise SystemModelError("uncertainties exceed bound")
    return _seal_model(
        base_sha=base_sha,
        root_fingerprint=inventory.root_fingerprint,
        inventory=inventory,
        components=components,
        ownership=ownership,
        dependency_edges=tuple(edges),
        uncertainties=tuple(uniq.values()),
        tcb_registry_sha256=registry.registry_sha256,
    )


# ---------------------------------------------------------------------------
# CB-028D TCB helpers (canonical policy only)
# ---------------------------------------------------------------------------


def model_tcb_classification(model, path):
    """Classify a path using model evidence + live canonical TCB registry.

    Returns a dict with is_tcb / component evidence, or uncertainty.
    Never downgrades protected paths.  Worker metadata cannot override.
    """
    if not isinstance(model, SystemModel):
        raise SystemModelError("model is invalid")
    live = create_mootos_tcb_registry_v1()
    if model.tcb_registry_sha256 != live.registry_sha256:
        return {
            "path": path,
            "is_tcb": None,
            "state": "uncertain",
            "detail_code": "tcb_registry_mismatch",
            "registry_sha256": live.registry_sha256,
        }
    try:
        canonical = _canonical_repo_path(path, "query path")
    except SystemModelError:
        return {
            "path": path,
            "is_tcb": None,
            "state": "uncertain",
            "detail_code": "malformed_path",
            "registry_sha256": live.registry_sha256,
        }
    in_registry = canonical in live.protected_paths
    record = None
    for item in model.inventory.files:
        if item.path == canonical:
            record = item
            break
    if record is not None and record.is_tcb != in_registry:
        # Model evidence disagreed with live registry — fail closed/uncertain.
        return {
            "path": canonical,
            "is_tcb": True if in_registry else record.is_tcb,
            "state": "uncertain",
            "detail_code": "model_tcb_flag_mismatch",
            "registry_sha256": live.registry_sha256,
            # Protected cannot be downgraded: if registry says TCB, report TCB.
            "protected_cannot_downgrade": True,
        }
    if in_registry:
        component = live.component_for_path(canonical)
        return {
            "path": canonical,
            "is_tcb": True,
            "state": "tcb",
            "detail_code": "canonical_registry_hit",
            "registry_sha256": live.registry_sha256,
            "tcb_component_id": (
                component.component_id if component is not None else None
            ),
            "change_policy": (
                component.change_policy if component is not None else None
            ),
        }
    return {
        "path": canonical,
        "is_tcb": False,
        "state": "non_tcb",
        "detail_code": "not_in_canonical_registry",
        "registry_sha256": live.registry_sha256,
    }


# ---------------------------------------------------------------------------
# CB-028E read-only query / impact interface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImpactAssessment:
    """Conservative impact assessment — never claims SAFE/PASS certainty."""

    changed_paths: tuple
    changed_components: tuple
    impacted_components: tuple
    impact_state: str
    uncertain_subjects: tuple
    assessment_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _QUERY_TOKEN:
            raise SystemModelError(
                "impact assessment requires trusted derivation"
            )
        if self.impact_state not in IMPACT_STATES:
            raise SystemModelError("impact state unsupported")
        _require_no_authority(self)
        _require_sha256(self.assessment_sha256, "assessment digest")
        if self.assessment_sha256 != _digest(self._payload()):
            raise SystemModelError("assessment digest mismatch")

    def _body(self):
        return {
            "changed_components": list(self.changed_components),
            "changed_paths": list(self.changed_paths),
            "github_authorized": False,
            "impact_state": self.impact_state,
            "impacted_components": list(self.impacted_components),
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "uncertain_subjects": list(self.uncertain_subjects),
            "worker_output_trusted": False,
        }

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["assessment_sha256"] = self.assessment_sha256
        return body


def _seal_impact(
    *,
    changed_paths,
    changed_components,
    impacted_components,
    impact_state,
    uncertain_subjects,
):
    values = {
        "changed_paths": tuple(changed_paths),
        "changed_components": tuple(changed_components),
        "impacted_components": tuple(impacted_components),
        "impact_state": impact_state,
        "uncertain_subjects": tuple(uncertain_subjects),
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(ImpactAssessment)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ImpactAssessment(
        **values,
        assessment_sha256=_digest(provisional._payload()),
        _token=_QUERY_TOKEN,
    )


def component_for_path(model, path):
    """Return owning component id or None / 'AMBIGUOUS' / 'UNKNOWN'."""
    if not isinstance(model, SystemModel):
        raise SystemModelError("model is invalid")
    try:
        canonical = _canonical_repo_path(path, "query path")
    except SystemModelError:
        return "UNKNOWN"
    for item in model.ownership:
        if item.path == canonical:
            if item.state == "owned":
                return item.component_id
            if item.state == "ambiguous":
                return "AMBIGUOUS"
            if item.state == "excluded":
                return "EXCLUDED"
            return "UNKNOWN"
    return "UNKNOWN"


def files_for_component(model, component_id):
    """Return sorted file paths for a component, or empty tuple."""
    if not isinstance(model, SystemModel):
        raise SystemModelError("model is invalid")
    if (
        not isinstance(component_id, str)
        or _COMPONENT_ID.fullmatch(component_id) is None
    ):
        return tuple()
    for item in model.components:
        if item.component_id == component_id:
            return item.file_paths
    return tuple()


def dependencies_of(model, component_id):
    """Return dependency edge dicts sourced from component_id."""
    if not isinstance(model, SystemModel):
        raise SystemModelError("model is invalid")
    return tuple(
        item.to_dict()
        for item in model.dependency_edges
        if item.source_component_id == component_id
    )


def dependents_of(model, component_id):
    """Return dependency edge dicts targeting component_id."""
    if not isinstance(model, SystemModel):
        raise SystemModelError("model is invalid")
    return tuple(
        item.to_dict()
        for item in model.dependency_edges
        if item.target_component_id == component_id
    )


def changed_components(model, paths):
    """Map changed paths to components — UNKNOWN/AMBIGUOUS preserved."""
    if not isinstance(model, SystemModel):
        raise SystemModelError("model is invalid")
    if type(paths) not in (list, tuple):
        raise SystemModelError("paths malformed")
    if len(paths) > MAX_QUERY_PATHS:
        raise SystemModelError("paths exceed bound")
    result = []
    seen = set()
    for path in paths:
        cid = component_for_path(model, path)
        if cid not in seen:
            seen.add(cid)
            result.append(cid)
    return tuple(sorted(result, key=lambda value: (value is None, str(value))))


def impacted_components(model, paths):
    """Conservative impact: changed + direct dependents; else POSSIBLE/UNKNOWN."""
    if not isinstance(model, SystemModel):
        raise SystemModelError("model is invalid")
    if type(paths) not in (list, tuple):
        raise SystemModelError("paths malformed")
    if len(paths) > MAX_QUERY_PATHS:
        raise SystemModelError("paths exceed bound")
    normalized = []
    uncertain = []
    for path in paths:
        try:
            normalized.append(_canonical_repo_path(path, "query path"))
        except SystemModelError:
            uncertain.append(f"malformed:{path!r}")
    changed = changed_components(model, tuple(normalized))
    impacted = set()
    for cid in changed:
        if cid in ("UNKNOWN", "AMBIGUOUS", "EXCLUDED"):
            uncertain.append(cid)
            continue
        impacted.add(cid)
        for edge in dependents_of(model, cid):
            impacted.add(edge["source_component_id"])
        for edge in dependencies_of(model, cid):
            if edge["kind"] in ("unresolved_import", "ambiguous_import"):
                uncertain.append(f"{cid}:{edge['imported_name']}")
    if uncertain and not impacted:
        state = "unknown"
    elif uncertain:
        state = "possible_impact"
    elif impacted:
        state = "impacted"
    else:
        state = "not_impacted"
    return _seal_impact(
        changed_paths=tuple(sorted(set(normalized))),
        changed_components=changed,
        impacted_components=tuple(sorted(impacted)),
        impact_state=state,
        uncertain_subjects=tuple(sorted(set(uncertain))),
    )


def system_model_is_descriptive_only():
    """TRUST REVIEW helper: True — model has no enforcement authority."""
    return True
