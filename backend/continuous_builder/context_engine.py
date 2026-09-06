"""Continuous Builder Context Engine v1 (CB-029A–H).

THE SYSTEM OWNS TRUTH. THE WORKER ONLY PROPOSES CHANGES.

Context Engine is a read-only evidence librarian over the System Model map.
It reconstructs the smallest sufficient context package for a frozen task.
It is NOT authority, permission, worker, executor, queue, GitHub, router,
or Task Decomposer.

TRUST REVIEW: descriptive only. Retrieval cannot grant authority or enlarge
scope/permissions/risk/budget/allowed paths/acceptance/checkpoints.
Visibility ≠ write permission. Outside TCB while policy independently checks
permissions. If this module alone would authorize execution/scope/TCB/policy,
HOLD and expand TCB only via create_mootos_tcb_registry_v1().
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .paths import PathCanonicalizationError, canonicalize_repo_path
from .system_model import (
    SystemModel,
    SystemModelError,
    component_for_path,
    dependencies_of,
    dependents_of,
    files_for_component,
    impacted_components,
    model_tcb_classification,
)
from .trusted_policy import (
    AUTHORITY_FLAGS as TCB_AUTHORITY_FLAGS,
    create_mootos_tcb_registry_v1,
    is_tcb_path,
)


class ContextEngineError(ValueError):
    """Raised when Context Engine evidence cannot be produced safely."""


ENGINE_VERSION = "cb-context-engine-v1"
AUTHORITY_FLAGS = TCB_AUTHORITY_FLAGS

# Hard budgets (bytes). Default soft target ~256KiB; hard max documented.
DEFAULT_PACKAGE_BUDGET_BYTES = 256 * 1024
HARD_MAX_PACKAGE_BUDGET_BYTES = 1024 * 1024
DEFAULT_EXCERPT_BUDGET_BYTES = 16 * 1024
HARD_MAX_EXCERPT_BUDGET_BYTES = 64 * 1024
MAX_SEED_PATHS = 64
MAX_ALLOWED_PATHS = 256
MAX_FORBIDDEN_PATHS = 256
MAX_COMPONENTS = 64
MAX_EXCERPTS = 128
MAX_UNCERTAINTIES = 256
MAX_OBJECTIVE_BYTES = 4096
MAX_ACCEPTANCE_BYTES = 8192
MAX_TEXT_FIELD_BYTES = 2048
DEFAULT_DEP_DEPTH = 1
MAX_DEP_DEPTH = 2
MAX_SUPPLEMENTS_PER_PACKAGE = 8
MAX_SUPPLEMENT_BUDGET_BYTES = 64 * 1024
MAX_INTERFACE_SYMBOLS = 64
MAX_IMPORTS = 128
MAX_RELATED_TESTS = 32
MAX_ARCH_DOCS = 16
AVG_CHARS_PER_TOKEN = 4  # conservative rough estimate only

SELECTION_TAGS = frozenset({
    "REQUIRED",
    "SUPPORTING",
    "POSSIBLE",
    "OMITTED",
    "UNKNOWN",
})

COMPLETENESS_STATES = frozenset({
    "sufficient",
    "sufficient_with_uncertainty",
    "incomplete",
    "restricted",
    "conflicting",
    "unknown",
})

UNCERTAINTY_KINDS = frozenset({
    "missing_source",
    "restricted_secret",
    "restricted_path",
    "parse_failure",
    "non_text",
    "truncated",
    "unknown_ownership",
    "ambiguous_ownership",
    "budget_exhausted",
    "critical_missing",
    "model_uncertainty",
    "path_rejected",
    "supplement_denied",
    "unknown",
})

SUPPLEMENT_CATEGORIES = frozenset({
    "file_excerpt",
    "interface_summary",
    "component_dependencies",
    "component_dependents",
    "related_tests",
    "architecture_evidence",
    "tcb_classification",
})

SOURCE_KINDS = frozenset({
    "file_excerpt",
    "interface_summary",
    "dependency_summary",
    "test_ref",
    "architecture_evidence",
    "tcb_warning",
    "task_contract",
    "authority_non_goals",
    "acceptance",
    "editable_path",
})

TEST_RELATION_KINDS = frozenset({
    "related",
    "required",
    "probable",
    "unknown",
})

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_TASK_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_COMPONENT_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")

# Fail-closed secret / credential path policy (names + suffixes).
_SECRET_FILE_NAMES = frozenset({
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.staging",
    ".env.test",
    "credentials.json",
    "credentials.yml",
    "credentials.yaml",
    "secrets.json",
    "secrets.yml",
    "secrets.yaml",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "authorized_keys",
    "known_hosts",
    "cookies",
    "cookies.txt",
    "cookie.jar",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "aws_credentials",
    "gcloud_credentials.json",
    "service_account.json",
})
_SECRET_NAME_PREFIXES = (".env",)
_SECRET_NAME_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".kdbx",
)
_SECRET_PATH_SEGMENTS = frozenset({
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".kube",
    "credentials",
    "private_keys",
    "private-keys",
})
_SECRET_CONTENT_MARKERS = (
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN CERTIFICATE-----",
    "AWS_SECRET_ACCESS_KEY",
    "Authorization: Bearer ",
    "AUTHORIZATION: Bearer ",
)

_REQUEST_TOKEN = object()
_SCOPE_TOKEN = object()
_BUDGET_TOKEN = object()
_SOURCE_TOKEN = object()
_EXCERPT_TOKEN = object()
_DEP_TOKEN = object()
_INTERFACE_TOKEN = object()
_SELECTION_TOKEN = object()
_UNCERTAINTY_TOKEN = object()
_PACKAGE_TOKEN = object()
_RECEIPT_TOKEN = object()
_SUPP_REQ_TOKEN = object()
_SUPP_TOKEN = object()


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
        raise ContextEngineError(f"{label} is malformed")


def _require_base_sha(value, label="base_sha"):
    if not isinstance(value, str) or not (
        _SHA256.fullmatch(value) or _GIT_SHA.fullmatch(value)
    ):
        raise ContextEngineError(f"{label} is malformed")


def _require_no_authority(obj):
    for name in AUTHORITY_FLAGS:
        if getattr(obj, name, False) is not False:
            raise ContextEngineError("context engine cannot claim authority")


def _utf8_len(value):
    if not isinstance(value, str):
        raise ContextEngineError("text field malformed")
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ContextEngineError("text field is not utf-8 safe") from error


def _require_text(value, label, max_bytes):
    if not isinstance(value, str) or not value:
        raise ContextEngineError(f"{label} is malformed")
    if _utf8_len(value) > max_bytes:
        raise ContextEngineError(f"{label} exceeds byte bound")
    return value


def _canonical_repo_path(value, label="path"):
    try:
        return canonicalize_repo_path(value)
    except PathCanonicalizationError as error:
        raise ContextEngineError(f"{label} is unsafe: {error}") from error


def _sorted_unique_paths(values, label, max_count):
    if type(values) not in (list, tuple):
        raise ContextEngineError(f"{label} malformed")
    if len(values) > max_count:
        raise ContextEngineError(f"{label} exceeds bound")
    out = []
    seen = set()
    for item in values:
        path = _canonical_repo_path(item, label)
        if path not in seen:
            seen.add(path)
            out.append(path)
    return tuple(sorted(out))


def _sorted_unique_components(values, label, max_count):
    if type(values) not in (list, tuple):
        raise ContextEngineError(f"{label} malformed")
    if len(values) > max_count:
        raise ContextEngineError(f"{label} exceeds bound")
    out = []
    seen = set()
    for item in values:
        if not isinstance(item, str) or _COMPONENT_ID.fullmatch(item) is None:
            raise ContextEngineError(f"{label} component id malformed")
        if item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(sorted(out))


def _zero_authority_dict():
    return {name: False for name in AUTHORITY_FLAGS}


def _authority_body():
    body = {}
    for name in AUTHORITY_FLAGS:
        body[name] = False
    return body


# ---------------------------------------------------------------------------
# CB-029A — frozen contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextBudget:
    """Bounded budgets for package / excerpt / depth / counts."""

    package_budget_bytes: int
    excerpt_budget_bytes: int
    max_excerpts: int
    max_components: int
    max_seed_paths: int
    dep_depth: int
    budget_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _BUDGET_TOKEN:
            raise ContextEngineError(
                "context budget requires trusted system construction"
            )
        for name, value, lo, hi in (
            ("package_budget_bytes", self.package_budget_bytes, 1024,
             HARD_MAX_PACKAGE_BUDGET_BYTES),
            ("excerpt_budget_bytes", self.excerpt_budget_bytes, 256,
             HARD_MAX_EXCERPT_BUDGET_BYTES),
            ("max_excerpts", self.max_excerpts, 1, MAX_EXCERPTS),
            ("max_components", self.max_components, 1, MAX_COMPONENTS),
            ("max_seed_paths", self.max_seed_paths, 1, MAX_SEED_PATHS),
            ("dep_depth", self.dep_depth, 0, MAX_DEP_DEPTH),
        ):
            if type(value) is not int or value < lo or value > hi:
                raise ContextEngineError(f"{name} out of bounds")
        _require_no_authority(self)
        _require_sha256(self.budget_sha256, "budget digest")
        if self.budget_sha256 != _digest(self._payload()):
            raise ContextEngineError("budget digest mismatch")

    def _body(self):
        body = {
            "dep_depth": self.dep_depth,
            "excerpt_budget_bytes": self.excerpt_budget_bytes,
            "max_components": self.max_components,
            "max_excerpts": self.max_excerpts,
            "max_seed_paths": self.max_seed_paths,
            "package_budget_bytes": self.package_budget_bytes,
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["budget_sha256"] = self.budget_sha256
        return body


def seal_context_budget(
    *,
    package_budget_bytes=DEFAULT_PACKAGE_BUDGET_BYTES,
    excerpt_budget_bytes=DEFAULT_EXCERPT_BUDGET_BYTES,
    max_excerpts=MAX_EXCERPTS,
    max_components=MAX_COMPONENTS,
    max_seed_paths=MAX_SEED_PATHS,
    dep_depth=DEFAULT_DEP_DEPTH,
):
    values = {
        "package_budget_bytes": package_budget_bytes,
        "excerpt_budget_bytes": excerpt_budget_bytes,
        "max_excerpts": max_excerpts,
        "max_components": max_components,
        "max_seed_paths": max_seed_paths,
        "dep_depth": dep_depth,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(ContextBudget)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ContextBudget(
        **values,
        budget_sha256=_digest(provisional._payload()),
        _token=_BUDGET_TOKEN,
    )


@dataclass(frozen=True)
class ContextScope:
    """Declared scope — intent only; not write permission."""

    allowed_paths: tuple
    forbidden_paths: tuple
    seed_paths: tuple
    components: tuple
    scope_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _SCOPE_TOKEN:
            raise ContextEngineError(
                "context scope requires trusted system construction"
            )
        if type(self.allowed_paths) is not tuple:
            raise ContextEngineError("allowed_paths malformed")
        if type(self.forbidden_paths) is not tuple:
            raise ContextEngineError("forbidden_paths malformed")
        if type(self.seed_paths) is not tuple:
            raise ContextEngineError("seed_paths malformed")
        if type(self.components) is not tuple:
            raise ContextEngineError("components malformed")
        if len(self.allowed_paths) > MAX_ALLOWED_PATHS:
            raise ContextEngineError("allowed_paths exceed bound")
        if len(self.forbidden_paths) > MAX_FORBIDDEN_PATHS:
            raise ContextEngineError("forbidden_paths exceed bound")
        if len(self.seed_paths) > MAX_SEED_PATHS:
            raise ContextEngineError("seed_paths exceed bound")
        if len(self.components) > MAX_COMPONENTS:
            raise ContextEngineError("components exceed bound")
        if self.allowed_paths != tuple(sorted(set(self.allowed_paths))):
            raise ContextEngineError("allowed_paths not canonical")
        if self.forbidden_paths != tuple(sorted(set(self.forbidden_paths))):
            raise ContextEngineError("forbidden_paths not canonical")
        if self.seed_paths != tuple(sorted(set(self.seed_paths))):
            raise ContextEngineError("seed_paths not canonical")
        if self.components != tuple(sorted(set(self.components))):
            raise ContextEngineError("components not canonical")
        overlap = set(self.allowed_paths) & set(self.forbidden_paths)
        if overlap:
            raise ContextEngineError("allowed/forbidden path conflict")
        for path in self.seed_paths:
            if path in self.forbidden_paths:
                raise ContextEngineError("seed path is forbidden")
        _require_no_authority(self)
        _require_sha256(self.scope_sha256, "scope digest")
        if self.scope_sha256 != _digest(self._payload()):
            raise ContextEngineError("scope digest mismatch")

    def _body(self):
        body = {
            "allowed_paths": list(self.allowed_paths),
            "components": list(self.components),
            "forbidden_paths": list(self.forbidden_paths),
            "seed_paths": list(self.seed_paths),
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["scope_sha256"] = self.scope_sha256
        return body


def seal_context_scope(
    *,
    allowed_paths=(),
    forbidden_paths=(),
    seed_paths=(),
    components=(),
):
    allowed = _sorted_unique_paths(
        allowed_paths, "allowed_paths", MAX_ALLOWED_PATHS
    )
    forbidden = _sorted_unique_paths(
        forbidden_paths, "forbidden_paths", MAX_FORBIDDEN_PATHS
    )
    seeds = _sorted_unique_paths(seed_paths, "seed_paths", MAX_SEED_PATHS)
    comps = _sorted_unique_components(
        components, "components", MAX_COMPONENTS
    )
    values = {
        "allowed_paths": allowed,
        "forbidden_paths": forbidden,
        "seed_paths": seeds,
        "components": comps,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(ContextScope)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ContextScope(
        **values,
        scope_sha256=_digest(provisional._payload()),
        _token=_SCOPE_TOKEN,
    )


@dataclass(frozen=True)
class ContextTaskRequest:
    """Frozen task intent for context assembly — NOT permission.

    Binds task_id, base_sha, objective, acceptance, scope, budget.
    Zero authority. No timestamps in digests. No secrets/network/creds.
    """

    engine_version: str
    task_id: str
    base_sha: str
    objective: str
    acceptance: tuple
    scope: ContextScope
    budget: ContextBudget
    non_goals: tuple
    request_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _REQUEST_TOKEN:
            raise ContextEngineError(
                "context task request requires trusted system construction"
            )
        if self.engine_version != ENGINE_VERSION:
            raise ContextEngineError("engine version unsupported")
        if not isinstance(self.task_id, str) or (
            _TASK_ID.fullmatch(self.task_id) is None
        ):
            raise ContextEngineError("task_id malformed")
        _require_base_sha(self.base_sha)
        _require_text(self.objective, "objective", MAX_OBJECTIVE_BYTES)
        if type(self.acceptance) is not tuple:
            raise ContextEngineError("acceptance malformed")
        if len(self.acceptance) > 64:
            raise ContextEngineError("acceptance exceeds bound")
        total_acc = 0
        for item in self.acceptance:
            _require_text(item, "acceptance item", MAX_TEXT_FIELD_BYTES)
            total_acc += _utf8_len(item)
        if total_acc > MAX_ACCEPTANCE_BYTES:
            raise ContextEngineError("acceptance exceeds byte bound")
        if type(self.non_goals) is not tuple or len(self.non_goals) > 64:
            raise ContextEngineError("non_goals malformed")
        for item in self.non_goals:
            _require_text(item, "non_goal", MAX_TEXT_FIELD_BYTES)
        if not isinstance(self.scope, ContextScope):
            raise ContextEngineError("scope invalid")
        if not isinstance(self.budget, ContextBudget):
            raise ContextEngineError("budget invalid")
        if len(self.scope.seed_paths) > self.budget.max_seed_paths:
            raise ContextEngineError("seed paths exceed budget bound")
        if len(self.scope.components) > self.budget.max_components:
            raise ContextEngineError("components exceed budget bound")
        _require_no_authority(self)
        _require_sha256(self.request_sha256, "request digest")
        if self.request_sha256 != _digest(self._payload()):
            raise ContextEngineError("request digest mismatch")

    def _body(self):
        body = {
            "acceptance": list(self.acceptance),
            "base_sha": self.base_sha,
            "budget": self.budget.to_dict(),
            "engine_version": ENGINE_VERSION,
            "non_goals": list(self.non_goals),
            "objective": self.objective,
            "scope": self.scope.to_dict(),
            "task_id": self.task_id,
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["request_sha256"] = self.request_sha256
        return body

    def canonical_bytes(self):
        return _canonical(self.to_dict())


def seal_context_task_request(
    *,
    task_id,
    base_sha,
    objective,
    acceptance=(),
    allowed_paths=(),
    forbidden_paths=(),
    seed_paths=(),
    components=(),
    non_goals=(),
    budget=None,
):
    """Seal a frozen ContextTaskRequest. Request = intent, not permission."""
    scope = seal_context_scope(
        allowed_paths=allowed_paths,
        forbidden_paths=forbidden_paths,
        seed_paths=seed_paths,
        components=components,
    )
    if budget is None:
        budget = seal_context_budget()
    elif not isinstance(budget, ContextBudget):
        raise ContextEngineError("budget invalid")
    if type(acceptance) not in (list, tuple):
        raise ContextEngineError("acceptance malformed")
    if type(non_goals) not in (list, tuple):
        raise ContextEngineError("non_goals malformed")
    values = {
        "engine_version": ENGINE_VERSION,
        "task_id": task_id,
        "base_sha": base_sha,
        "objective": objective,
        "acceptance": tuple(acceptance),
        "scope": scope,
        "budget": budget,
        "non_goals": tuple(non_goals),
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(ContextTaskRequest)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ContextTaskRequest(
        **values,
        request_sha256=_digest(provisional._payload()),
        _token=_REQUEST_TOKEN,
    )


@dataclass(frozen=True)
class ContextUncertainty:
    """Descriptive uncertainty — never invents certainty."""

    kind: str
    subject: str
    detail_code: str
    uncertainty_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _UNCERTAINTY_TOKEN:
            raise ContextEngineError(
                "uncertainty requires trusted system construction"
            )
        if self.kind not in UNCERTAINTY_KINDS:
            raise ContextEngineError("uncertainty kind unsupported")
        _require_text(self.subject, "subject", MAX_TEXT_FIELD_BYTES)
        _require_text(self.detail_code, "detail_code", 128)
        _require_no_authority(self)
        _require_sha256(self.uncertainty_sha256, "uncertainty digest")
        if self.uncertainty_sha256 != _digest(self._payload()):
            raise ContextEngineError("uncertainty digest mismatch")

    def _body(self):
        body = {
            "detail_code": self.detail_code,
            "kind": self.kind,
            "subject": self.subject,
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["uncertainty_sha256"] = self.uncertainty_sha256
        return body


def seal_uncertainty(*, kind, subject, detail_code):
    values = {
        "kind": kind,
        "subject": subject,
        "detail_code": detail_code,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(ContextUncertainty)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ContextUncertainty(
        **values,
        uncertainty_sha256=_digest(provisional._payload()),
        _token=_UNCERTAINTY_TOKEN,
    )


@dataclass(frozen=True)
class SourceRef:
    """Provenance-bearing reference to included evidence."""

    kind: str
    path: str | None
    selection_tag: str
    digest: str
    region: tuple | None
    source_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _SOURCE_TOKEN:
            raise ContextEngineError(
                "source ref requires trusted system construction"
            )
        if self.kind not in SOURCE_KINDS:
            raise ContextEngineError("source kind unsupported")
        if self.selection_tag not in SELECTION_TAGS:
            raise ContextEngineError("selection tag unsupported")
        if self.path is not None:
            _canonical_repo_path(self.path, "source path")
        _require_sha256(self.digest, "source content digest")
        if self.region is not None:
            if (
                type(self.region) is not tuple
                or len(self.region) != 2
                or type(self.region[0]) is not int
                or type(self.region[1]) is not int
                or self.region[0] < 1
                or self.region[1] < self.region[0]
            ):
                raise ContextEngineError("region malformed")
        _require_no_authority(self)
        _require_sha256(self.source_sha256, "source ref digest")
        if self.source_sha256 != _digest(self._payload()):
            raise ContextEngineError("source ref digest mismatch")

    def _body(self):
        body = {
            "digest": self.digest,
            "kind": self.kind,
            "path": self.path,
            "region": list(self.region) if self.region is not None else None,
            "selection_tag": self.selection_tag,
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["source_sha256"] = self.source_sha256
        return body


def seal_source_ref(*, kind, path, selection_tag, digest, region=None):
    canon_path = None if path is None else _canonical_repo_path(path)
    values = {
        "kind": kind,
        "path": canon_path,
        "selection_tag": selection_tag,
        "digest": digest,
        "region": None if region is None else tuple(region),
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(SourceRef)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return SourceRef(
        **values,
        source_sha256=_digest(provisional._payload()),
        _token=_SOURCE_TOKEN,
    )


def context_engine_is_descriptive_only():
    """TRUST REVIEW helper: True — engine has no enforcement authority."""
    return True


def context_request_grants_write_permission(request):
    """Visibility/intent ≠ write permission. Always False."""
    if not isinstance(request, ContextTaskRequest):
        raise ContextEngineError("request invalid")
    return False



# ---------------------------------------------------------------------------
# CB-029B — trusted excerpt extraction (secret-safe, fail-closed)
# ---------------------------------------------------------------------------


def classify_secret_path(path):
    """Return detail_code if path is secret-restricted, else None."""
    try:
        canon = _canonical_repo_path(path, "secret path")
    except ContextEngineError:
        return "malformed_path"
    segments = canon.split("/")
    name = segments[-1]
    lower = name.lower()
    if name in _SECRET_FILE_NAMES or lower in _SECRET_FILE_NAMES:
        return "secret_filename"
    for prefix in _SECRET_NAME_PREFIXES:
        if name.startswith(prefix) and name != ".env.example":
            return "secret_env_file"
    for suffix in _SECRET_NAME_SUFFIXES:
        if lower.endswith(suffix):
            return "secret_key_material"
    for seg in segments[:-1]:
        if seg.lower() in _SECRET_PATH_SEGMENTS:
            return "secret_path_segment"
    # API-key style filenames
    if "api_key" in lower or "apikey" in lower or lower.endswith(".api_key"):
        return "secret_api_key_file"
    if "access_token" in lower or lower.endswith(".token"):
        return "secret_token_file"
    return None


def _content_looks_secret(text):
    for marker in _SECRET_CONTENT_MARKERS:
        if marker in text:
            return True
    return False


def _is_probably_text(data):
    if b"\x00" in data:
        return False
    # Reject high ratio of non-text bytes.
    if not data:
        return True
    sample = data[:4096]
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    nonprint = sum(
        1 for b in sample
        if b < 9 or (13 < b < 32) or b == 127
    )
    return (nonprint / max(len(sample), 1)) < 0.05


def _resolve_regular_file(repo_root, rel_path):
    root = Path(repo_root)
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ContextEngineError("repo root is unresolvable") from error
    if not root.is_dir():
        raise ContextEngineError("repo root must be a directory")
    canon = _canonical_repo_path(rel_path)
    # Reject .git dumps and DB/WAL.
    segments = canon.split("/")
    if ".git" in segments:
        raise ContextEngineError("git object path rejected")
    name = segments[-1]
    if name.startswith("mootos.db") or name.endswith(
        ("-wal", "-shm", "-journal")
    ):
        if "mootos.db" in name:
            raise ContextEngineError("database path rejected")
    full = root.joinpath(*segments)
    # Never follow symlinks: reject if any ancestor or file is a symlink.
    cursor = root
    for seg in segments:
        cursor = cursor / seg
        try:
            if cursor.is_symlink():
                raise ContextEngineError("symlink rejected")
        except OSError as error:
            raise ContextEngineError("path stat failed") from error
    try:
        if not full.is_file() or full.is_symlink():
            raise ContextEngineError("path is not a regular file")
        resolved = full.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError, RuntimeError) as error:
        raise ContextEngineError("path escapes repository or missing") from error
    if resolved.is_symlink():
        raise ContextEngineError("symlink rejected")
    return root, canon, resolved


@dataclass(frozen=True)
class ContextExcerpt:
    """Sealed line-oriented excerpt bound to path + file digest + revision."""

    path: str
    base_sha: str
    file_sha256: str
    excerpt_sha256: str
    start_line: int
    end_line: int
    text: str
    truncated: bool
    available: bool
    restriction: str | None
    provenance: str
    record_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _EXCERPT_TOKEN:
            raise ContextEngineError(
                "excerpt requires trusted system construction"
            )
        _canonical_repo_path(self.path)
        _require_base_sha(self.base_sha)
        _require_sha256(self.file_sha256, "file digest")
        _require_sha256(self.excerpt_sha256, "excerpt digest")
        if type(self.start_line) is not int or type(self.end_line) is not int:
            raise ContextEngineError("line bounds malformed")
        if self.available:
            if not isinstance(self.text, str):
                raise ContextEngineError("excerpt text malformed")
            if self.restriction is not None:
                raise ContextEngineError("available excerpt cannot be restricted")
            if self.text == "":
                # Empty file / empty selection after truncation.
                if self.start_line != 0 or self.end_line != 0:
                    raise ContextEngineError("empty excerpt bounds invalid")
            elif self.start_line < 1 or self.end_line < self.start_line:
                raise ContextEngineError("line bounds invalid")
        else:
            if self.text != "":
                raise ContextEngineError("unavailable excerpt must be empty")
            if self.restriction is None:
                raise ContextEngineError("unavailable excerpt needs restriction")
            _require_text(self.restriction, "restriction", 128)
        if type(self.truncated) is not bool:
            raise ContextEngineError("truncated flag malformed")
        _require_text(self.provenance, "provenance", 128)
        _require_no_authority(self)
        _require_sha256(self.record_sha256, "excerpt record digest")
        if self.record_sha256 != _digest(self._payload()):
            raise ContextEngineError("excerpt record digest mismatch")

    def _body(self):
        body = {
            "available": self.available,
            "base_sha": self.base_sha,
            "end_line": self.end_line,
            "excerpt_sha256": self.excerpt_sha256,
            "file_sha256": self.file_sha256,
            "path": self.path,
            "provenance": self.provenance,
            "restriction": self.restriction,
            "start_line": self.start_line,
            "text": self.text,
            "truncated": self.truncated,
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["record_sha256"] = self.record_sha256
        return body


def _seal_excerpt(
    *,
    path,
    base_sha,
    file_sha256,
    excerpt_sha256,
    start_line,
    end_line,
    text,
    truncated,
    available,
    restriction,
    provenance,
):
    values = {
        "path": path,
        "base_sha": base_sha,
        "file_sha256": file_sha256,
        "excerpt_sha256": excerpt_sha256,
        "start_line": start_line,
        "end_line": end_line,
        "text": text,
        "truncated": truncated,
        "available": available,
        "restriction": restriction,
        "provenance": provenance,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(ContextExcerpt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ContextExcerpt(
        **values,
        record_sha256=_digest(provisional._payload()),
        _token=_EXCERPT_TOKEN,
    )


def _unavailable_excerpt(*, path, base_sha, restriction, provenance):
    empty = ""
    return _seal_excerpt(
        path=path,
        base_sha=base_sha,
        file_sha256=_digest(b""),
        excerpt_sha256=_digest(empty),
        start_line=0,
        end_line=0,
        text=empty,
        truncated=False,
        available=False,
        restriction=restriction,
        provenance=provenance,
    )


def extract_excerpt(
    repo_root,
    *,
    base_sha,
    path,
    region=None,
    budget_bytes=DEFAULT_EXCERPT_BUDGET_BYTES,
):
    """Trusted excerpt extraction: root+base_sha+path(+region)+budget.

    Regular files only. No symlink/traversal/absolute/.git/DB/WAL/creds.
    Secret policy fail-closed: never puts secret bytes in package/logs/errors.
    Binary → unavailable/non-text. Line-oriented text with truncation flag.
    """
    _require_base_sha(base_sha)
    if type(budget_bytes) is not int or budget_bytes < 256:
        raise ContextEngineError("excerpt budget malformed")
    if budget_bytes > HARD_MAX_EXCERPT_BUDGET_BYTES:
        raise ContextEngineError("excerpt budget exceeds hard max")

    secret = classify_secret_path(path)
    if secret is not None:
        # Never read secret bytes — structured restriction only.
        try:
            canon = _canonical_repo_path(path)
        except ContextEngineError:
            canon = "restricted"
        return _unavailable_excerpt(
            path=canon if secret != "malformed_path" else "restricted",
            base_sha=base_sha,
            restriction=secret,
            provenance="secret_policy",
        )

    try:
        _root, canon, full = _resolve_regular_file(repo_root, path)
    except ContextEngineError as error:
        # Do not echo path details that might include secrets in odd cases.
        code = str(error)
        if "symlink" in code:
            restriction = "symlink_rejected"
        elif "git" in code:
            restriction = "git_path_rejected"
        elif "database" in code:
            restriction = "database_rejected"
        elif "regular file" in code or "missing" in code or "escapes" in code:
            restriction = "path_unavailable"
        else:
            restriction = "path_rejected"
        try:
            canon = _canonical_repo_path(path)
        except ContextEngineError:
            canon = "rejected"
        return _unavailable_excerpt(
            path=canon,
            base_sha=base_sha,
            restriction=restriction,
            provenance="path_policy",
        )

    try:
        size = full.stat().st_size
    except OSError as error:
        raise ContextEngineError("stat failed") from error
    max_read = HARD_MAX_EXCERPT_BUDGET_BYTES * 32
    if size > max_read:
        return _unavailable_excerpt(
            path=canon,
            base_sha=base_sha,
            restriction="file_too_large",
            provenance="size_policy",
        )
    try:
        data = full.read_bytes()
    except OSError as error:
        raise ContextEngineError("read failed") from error
    if len(data) != size:
        raise ContextEngineError("size changed during read")
    file_digest = _digest(data)

    if not _is_probably_text(data):
        return _unavailable_excerpt(
            path=canon,
            base_sha=base_sha,
            restriction="non_text",
            provenance="binary_policy",
        )

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _unavailable_excerpt(
            path=canon,
            base_sha=base_sha,
            restriction="non_text",
            provenance="decode_policy",
        )

    if _content_looks_secret(text):
        # Fail closed — do not return secret bytes.
        return _unavailable_excerpt(
            path=canon,
            base_sha=base_sha,
            restriction="secret_content",
            provenance="secret_content_policy",
        )

    lines = text.splitlines(keepends=True)
    if not lines and text == "":
        lines = []
    total = len(lines)
    if region is None:
        start, end = 1, max(total, 0)
    else:
        if (
            type(region) not in (list, tuple)
            or len(region) != 2
            or type(region[0]) is not int
            or type(region[1]) is not int
            or region[0] < 1
            or region[1] < region[0]
        ):
            raise ContextEngineError("region malformed")
        start, end = region[0], region[1]
        if total == 0:
            start, end = 1, 0
        else:
            end = min(end, total)
            start = min(start, total) if total else 1
            if start > end:
                start, end = 1, 0

    if total == 0:
        selected = ""
        start_line, end_line = 0, 0
        truncated = False
    else:
        # region is 1-indexed inclusive
        chunk_lines = lines[start - 1:end]
        selected = "".join(chunk_lines)
        start_line, end_line = start, start - 1 + len(chunk_lines)
        truncated = False
        if _utf8_len(selected) > budget_bytes:
            # Truncate by whole lines to budget.
            out = []
            size = 0
            for line in chunk_lines:
                line_size = len(line.encode("utf-8"))
                if size + line_size > budget_bytes:
                    truncated = True
                    break
                out.append(line)
                size += line_size
            selected = "".join(out)
            end_line = start_line - 1 + len(out) if out else 0
            if not out:
                start_line, end_line = 0, 0
                truncated = True

    excerpt_digest = _digest(selected)
    return _seal_excerpt(
        path=canon,
        base_sha=base_sha,
        file_sha256=file_digest,
        excerpt_sha256=excerpt_digest,
        start_line=start_line,
        end_line=end_line,
        text=selected,
        truncated=truncated,
        available=True,
        restriction=None,
        provenance="trusted_extraction",
    )



# ---------------------------------------------------------------------------
# CB-029C — deterministic planner (System Model only; no LLM)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionItem:
    """One planned evidence item with selection tag."""

    path: str | None
    component_id: str | None
    selection_tag: str
    reason_code: str
    editable: bool
    item_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _SELECTION_TOKEN:
            raise ContextEngineError(
                "selection item requires trusted system construction"
            )
        if self.selection_tag not in SELECTION_TAGS:
            raise ContextEngineError("selection tag unsupported")
        if self.path is not None:
            _canonical_repo_path(self.path)
        if self.component_id is not None:
            if _COMPONENT_ID.fullmatch(self.component_id) is None:
                raise ContextEngineError("component id malformed")
        _require_text(self.reason_code, "reason_code", 128)
        if type(self.editable) is not bool:
            raise ContextEngineError("editable flag malformed")
        _require_no_authority(self)
        _require_sha256(self.item_sha256, "selection item digest")
        if self.item_sha256 != _digest(self._payload()):
            raise ContextEngineError("selection item digest mismatch")

    def _body(self):
        body = {
            "component_id": self.component_id,
            "editable": self.editable,
            "path": self.path,
            "reason_code": self.reason_code,
            "selection_tag": self.selection_tag,
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["item_sha256"] = self.item_sha256
        return body


def _seal_selection_item(
    *, path, component_id, selection_tag, reason_code, editable
):
    values = {
        "path": path,
        "component_id": component_id,
        "selection_tag": selection_tag,
        "reason_code": reason_code,
        "editable": editable,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(SelectionItem)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return SelectionItem(
        **values,
        item_sha256=_digest(provisional._payload()),
        _token=_SELECTION_TOKEN,
    )


@dataclass(frozen=True)
class ContextSelectionPlan:
    """Deterministic selection plan — visibility ≠ edit permission."""

    request_sha256: str
    model_sha256: str
    base_sha: str
    items: tuple
    uncertainties: tuple
    plan_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _SELECTION_TOKEN:
            raise ContextEngineError(
                "selection plan requires trusted system construction"
            )
        _require_sha256(self.request_sha256, "request digest")
        _require_sha256(self.model_sha256, "model digest")
        _require_base_sha(self.base_sha)
        if type(self.items) is not tuple or len(self.items) > MAX_EXCERPTS * 2:
            raise ContextEngineError("selection items malformed")
        if any(not isinstance(item, SelectionItem) for item in self.items):
            raise ContextEngineError("selection items invalid")
        if type(self.uncertainties) is not tuple or (
            len(self.uncertainties) > MAX_UNCERTAINTIES
        ):
            raise ContextEngineError("plan uncertainties malformed")
        _require_no_authority(self)
        _require_sha256(self.plan_sha256, "plan digest")
        if self.plan_sha256 != _digest(self._payload()):
            raise ContextEngineError("plan digest mismatch")

    def _body(self):
        body = {
            "base_sha": self.base_sha,
            "items": [item.to_dict() for item in self.items],
            "model_sha256": self.model_sha256,
            "request_sha256": self.request_sha256,
            "uncertainties": [item.to_dict() for item in self.uncertainties],
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["plan_sha256"] = self.plan_sha256
        return body


def _seal_selection_plan(
    *, request_sha256, model_sha256, base_sha, items, uncertainties
):
    ordered_items = tuple(
        sorted(
            items,
            key=lambda item: (
                item.selection_tag,
                item.path or "",
                item.component_id or "",
                item.reason_code,
            ),
        )
    )
    ordered_unc = tuple(
        sorted(
            uncertainties,
            key=lambda item: (item.kind, item.subject, item.detail_code),
        )
    )
    values = {
        "request_sha256": request_sha256,
        "model_sha256": model_sha256,
        "base_sha": base_sha,
        "items": ordered_items,
        "uncertainties": ordered_unc,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(ContextSelectionPlan)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ContextSelectionPlan(
        **values,
        plan_sha256=_digest(provisional._payload()),
        _token=_SELECTION_TOKEN,
    )


def _path_is_editable(path, scope):
    """Visibility ≠ edit. Editable only if in allowed and not forbidden."""
    if path in scope.forbidden_paths:
        return False
    if scope.allowed_paths and path not in scope.allowed_paths:
        return False
    if not scope.allowed_paths:
        # No allowed list declared — nothing is editable via context alone.
        return False
    return True


def _inventory_paths(model):
    return {item.path for item in model.inventory.files}


def _expand_component_neighborhood(model, seed_components, depth, budget_max):
    """Bounded BFS over dependency/dependent edges. depth <= MAX_DEP_DEPTH."""
    selected = {}
    for cid in seed_components:
        selected[cid] = "REQUIRED"
    frontier = list(seed_components)
    for _level in range(max(depth, 0)):
        nxt = []
        for cid in frontier:
            if len(selected) >= budget_max:
                return selected, True
            for edge in dependencies_of(model, cid):
                tgt = edge.get("target_component_id")
                if tgt and tgt not in selected:
                    selected[tgt] = "SUPPORTING"
                    nxt.append(tgt)
                elif edge.get("kind") in (
                    "unresolved_import", "ambiguous_import"
                ):
                    pass
            for edge in dependents_of(model, cid):
                src = edge.get("source_component_id")
                if src and src not in selected:
                    selected[src] = "SUPPORTING"
                    nxt.append(src)
            if len(selected) >= budget_max:
                return selected, True
        frontier = nxt
        if not frontier:
            break
    truncated = len(selected) >= budget_max
    return selected, truncated


def plan_context_selection(request, model):
    """Deterministic planner using System Model only (no LLM).

    Signals: allowed/seed, ownership, deps/dependents, impact, TCB, tests,
    arch docs when deterministic. Tags REQUIRED/SUPPORTING/POSSIBLE/OMITTED/
    UNKNOWN. Conservative; no unbounded recursion. Visibility ≠ edit.
    """
    if not isinstance(request, ContextTaskRequest):
        raise ContextEngineError("request invalid")
    if not isinstance(model, SystemModel):
        raise ContextEngineError("model invalid")
    if request.base_sha != model.base_sha:
        raise ContextEngineError("request/model base_sha mismatch")

    uncertainties = []
    items = []
    seen_paths = set()
    inventory = _inventory_paths(model)
    scope = request.scope
    budget = request.budget

    # Seed paths → REQUIRED
    for path in scope.seed_paths:
        if path in scope.forbidden_paths:
            uncertainties.append(
                seal_uncertainty(
                    kind="restricted_path",
                    subject=path,
                    detail_code="seed_forbidden",
                )
            )
            continue
        if path not in inventory:
            uncertainties.append(
                seal_uncertainty(
                    kind="missing_source",
                    subject=path,
                    detail_code="seed_not_in_model",
                )
            )
            items.append(
                _seal_selection_item(
                    path=path,
                    component_id=None,
                    selection_tag="UNKNOWN",
                    reason_code="seed_missing",
                    editable=False,
                )
            )
            continue
        cid = component_for_path(model, path)
        if cid in ("UNKNOWN", "AMBIGUOUS", "EXCLUDED"):
            tag = "UNKNOWN" if cid == "UNKNOWN" else "POSSIBLE"
            uncertainties.append(
                seal_uncertainty(
                    kind=(
                        "ambiguous_ownership"
                        if cid == "AMBIGUOUS"
                        else "unknown_ownership"
                    ),
                    subject=path,
                    detail_code=str(cid).lower(),
                )
            )
            comp = None if cid in ("UNKNOWN", "EXCLUDED") else None
        else:
            tag = "REQUIRED"
            comp = cid
        secret = classify_secret_path(path)
        if secret is not None:
            uncertainties.append(
                seal_uncertainty(
                    kind="restricted_secret",
                    subject=path,
                    detail_code=secret,
                )
            )
            tag = "OMITTED"
            editable = False
        else:
            editable = _path_is_editable(path, scope)
        items.append(
            _seal_selection_item(
                path=path,
                component_id=comp,
                selection_tag=tag,
                reason_code="seed_path",
                editable=editable,
            )
        )
        seen_paths.add(path)

    # Allowed paths not already seeded → REQUIRED (declared editable intent)
    for path in scope.allowed_paths:
        if path in seen_paths:
            continue
        if path not in inventory:
            uncertainties.append(
                seal_uncertainty(
                    kind="missing_source",
                    subject=path,
                    detail_code="allowed_not_in_model",
                )
            )
            continue
        if classify_secret_path(path) is not None:
            uncertainties.append(
                seal_uncertainty(
                    kind="restricted_secret",
                    subject=path,
                    detail_code=classify_secret_path(path),
                )
            )
            items.append(
                _seal_selection_item(
                    path=path,
                    component_id=None,
                    selection_tag="OMITTED",
                    reason_code="secret_excluded",
                    editable=False,
                )
            )
            seen_paths.add(path)
            continue
        cid = component_for_path(model, path)
        comp = cid if cid not in ("UNKNOWN", "AMBIGUOUS", "EXCLUDED") else None
        items.append(
            _seal_selection_item(
                path=path,
                component_id=comp,
                selection_tag="REQUIRED",
                reason_code="allowed_path",
                editable=_path_is_editable(path, scope),
            )
        )
        seen_paths.add(path)

    # Seed components from request + ownership of seeds
    seed_components = list(scope.components)
    for item in items:
        if item.component_id and item.component_id not in seed_components:
            seed_components.append(item.component_id)
    seed_components = seed_components[: budget.max_components]

    neighborhood, neigh_trunc = _expand_component_neighborhood(
        model,
        seed_components,
        budget.dep_depth,
        budget.max_components,
    )
    if neigh_trunc:
        uncertainties.append(
            seal_uncertainty(
                kind="budget_exhausted",
                subject="components",
                detail_code="component_bound",
            )
        )

    # Impact from seed+allowed paths
    impact_paths = tuple(
        sorted(set(list(scope.seed_paths) + list(scope.allowed_paths)))
    )[:256]
    if impact_paths:
        impact = impacted_components(model, impact_paths)
        for cid in impact.impacted_components:
            if cid not in neighborhood:
                if len(neighborhood) < budget.max_components:
                    neighborhood[cid] = "POSSIBLE"
        for subject in impact.uncertain_subjects:
            uncertainties.append(
                seal_uncertainty(
                    kind="model_uncertainty",
                    subject=str(subject)[:200],
                    detail_code="impact_uncertain",
                )
            )

    # Collect files from neighborhood components (bounded)
    path_budget = budget.max_excerpts
    for cid, tag in sorted(neighborhood.items()):
        files = files_for_component(model, cid)
        # Prefer module files; include tests/docs as SUPPORTING/POSSIBLE
        for fpath in files:
            if len(seen_paths) >= path_budget:
                uncertainties.append(
                    seal_uncertainty(
                        kind="budget_exhausted",
                        subject="excerpts",
                        detail_code="excerpt_bound",
                    )
                )
                break
            if fpath in seen_paths:
                continue
            if fpath in scope.forbidden_paths:
                items.append(
                    _seal_selection_item(
                        path=fpath,
                        component_id=cid,
                        selection_tag="OMITTED",
                        reason_code="forbidden",
                        editable=False,
                    )
                )
                seen_paths.add(fpath)
                continue
            if classify_secret_path(fpath) is not None:
                items.append(
                    _seal_selection_item(
                        path=fpath,
                        component_id=cid,
                        selection_tag="OMITTED",
                        reason_code="secret_excluded",
                        editable=False,
                    )
                )
                seen_paths.add(fpath)
                continue
            name = fpath.split("/")[-1]
            is_test = (
                fpath.startswith("tests/")
                or name.startswith("test_")
                or name.endswith("_test.py")
            )
            is_doc = fpath.startswith("docs/") or name.endswith(".md")
            if tag == "REQUIRED" and not is_test and not is_doc:
                sel = "REQUIRED"
                reason = "owned_component"
            elif is_test:
                sel = "SUPPORTING"
                reason = "related_test"
            elif is_doc:
                # Architecture docs when under docs/future/architecture or ADR-ish
                if (
                    "/architecture/" in fpath
                    or "/adr/" in fpath.lower()
                    or "ARCHITECTURE" in name.upper()
                    or name.upper().startswith("ADR")
                ):
                    sel = "SUPPORTING"
                    reason = "architecture_doc"
                else:
                    sel = "POSSIBLE"
                    reason = "documentation"
            else:
                sel = "SUPPORTING" if tag == "SUPPORTING" else "POSSIBLE"
                reason = "neighborhood"
            # TCB warning signal — still visible descriptively, not editable
            # via context alone unless allowed.
            editable = _path_is_editable(fpath, scope)
            if is_tcb_path(fpath):
                reason = "tcb_path"
                # Still may be SUPPORTING/REQUIRED for visibility.
            items.append(
                _seal_selection_item(
                    path=fpath,
                    component_id=cid,
                    selection_tag=sel,
                    reason_code=reason,
                    editable=editable,
                )
            )
            seen_paths.add(fpath)
        if len(seen_paths) >= path_budget:
            break

    # Explicit component-only entries for seed components without files listed
    for cid in seed_components:
        if any(item.component_id == cid for item in items):
            continue
        items.append(
            _seal_selection_item(
                path=None,
                component_id=cid,
                selection_tag="REQUIRED",
                reason_code="seed_component",
                editable=False,
            )
        )

    if len(uncertainties) > MAX_UNCERTAINTIES:
        uncertainties = uncertainties[:MAX_UNCERTAINTIES]

    return _seal_selection_plan(
        request_sha256=request.request_sha256,
        model_sha256=model.model_sha256,
        base_sha=request.base_sha,
        items=items,
        uncertainties=uncertainties,
    )


def selection_grants_edit_permission(plan, path):
    """Explicit proof: visibility on plan ≠ write permission."""
    if not isinstance(plan, ContextSelectionPlan):
        raise ContextEngineError("plan invalid")
    try:
        canon = _canonical_repo_path(path)
    except ContextEngineError:
        return False
    for item in plan.items:
        if item.path == canon and item.editable:
            # editable flag is intent from allowed_paths — still not authority.
            # Context Engine never grants write; policy must re-check.
            return False
    return False



# ---------------------------------------------------------------------------
# CB-029D — static AST enrichment (no execute / import / eval)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InterfaceSummary:
    """Static interface summary for a Python module — evidence only."""

    path: str
    base_sha: str
    file_sha256: str
    classes: tuple
    functions: tuple
    constants: tuple
    imports: tuple
    available: bool
    restriction: str | None
    summary_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _INTERFACE_TOKEN:
            raise ContextEngineError(
                "interface summary requires trusted system construction"
            )
        _canonical_repo_path(self.path)
        _require_base_sha(self.base_sha)
        _require_sha256(self.file_sha256, "file digest")
        for field_name, value, bound in (
            ("classes", self.classes, MAX_INTERFACE_SYMBOLS),
            ("functions", self.functions, MAX_INTERFACE_SYMBOLS),
            ("constants", self.constants, MAX_INTERFACE_SYMBOLS),
            ("imports", self.imports, MAX_IMPORTS),
        ):
            if type(value) is not tuple or len(value) > bound:
                raise ContextEngineError(f"{field_name} malformed")
        if type(self.available) is not bool:
            raise ContextEngineError("available malformed")
        if self.available and self.restriction is not None:
            raise ContextEngineError("available summary cannot be restricted")
        if not self.available and self.restriction is None:
            raise ContextEngineError("unavailable summary needs restriction")
        _require_no_authority(self)
        _require_sha256(self.summary_sha256, "summary digest")
        if self.summary_sha256 != _digest(self._payload()):
            raise ContextEngineError("summary digest mismatch")

    def _body(self):
        body = {
            "available": self.available,
            "base_sha": self.base_sha,
            "classes": list(self.classes),
            "constants": list(self.constants),
            "file_sha256": self.file_sha256,
            "functions": list(self.functions),
            "imports": list(self.imports),
            "path": self.path,
            "restriction": self.restriction,
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["summary_sha256"] = self.summary_sha256
        return body


def _seal_interface_summary(
    *,
    path,
    base_sha,
    file_sha256,
    classes,
    functions,
    constants,
    imports,
    available,
    restriction,
):
    values = {
        "path": path,
        "base_sha": base_sha,
        "file_sha256": file_sha256,
        "classes": tuple(classes),
        "functions": tuple(functions),
        "constants": tuple(constants),
        "imports": tuple(imports),
        "available": available,
        "restriction": restriction,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(InterfaceSummary)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return InterfaceSummary(
        **values,
        summary_sha256=_digest(provisional._payload()),
        _token=_INTERFACE_TOKEN,
    )


def _format_signature(node):
    """Format a function/method signature without evaluating defaults."""
    args = node.args
    parts = []
    for arg in args.posonlyargs:
        parts.append(arg.arg)
    if args.posonlyargs:
        parts.append("/")
    for arg in args.args:
        parts.append(arg.arg)
    if args.vararg is not None:
        parts.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        parts.append("*")
    for arg in args.kwonlyargs:
        parts.append(arg.arg)
    if args.kwarg is not None:
        parts.append("**" + args.kwarg.arg)
    # Never render default values (may execute-like / secret-ish literals).
    return f"{node.name}({', '.join(parts)})"


def _safe_constant_name(node):
    if isinstance(node, ast.Name) and node.id.isupper():
        return node.id
    if isinstance(node, ast.Tuple):
        names = []
        for elt in node.elts:
            if isinstance(elt, ast.Name) and elt.id.isupper():
                names.append(elt.id)
            else:
                return None
        return ",".join(names) if names else None
    return None


def enrich_interface_summary(repo_root, *, base_sha, path):
    """Static AST enrichment: classes/fns/signatures/constants/imports.

    No execute, import, eval, decorator execution, or default evaluation.
    AST fail → unavailable with parse_failure uncertainty-compatible code.
    """
    _require_base_sha(base_sha)
    secret = classify_secret_path(path)
    if secret is not None:
        try:
            canon = _canonical_repo_path(path)
        except ContextEngineError:
            canon = "restricted"
        return _seal_interface_summary(
            path=canon,
            base_sha=base_sha,
            file_sha256=_digest(b""),
            classes=(),
            functions=(),
            constants=(),
            imports=(),
            available=False,
            restriction=secret,
        )

    excerpt = extract_excerpt(
        repo_root,
        base_sha=base_sha,
        path=path,
        budget_bytes=HARD_MAX_EXCERPT_BUDGET_BYTES,
    )
    if not excerpt.available:
        return _seal_interface_summary(
            path=excerpt.path,
            base_sha=base_sha,
            file_sha256=excerpt.file_sha256,
            classes=(),
            functions=(),
            constants=(),
            imports=(),
            available=False,
            restriction=excerpt.restriction or "unavailable",
        )
    if not excerpt.path.endswith(".py"):
        return _seal_interface_summary(
            path=excerpt.path,
            base_sha=base_sha,
            file_sha256=excerpt.file_sha256,
            classes=(),
            functions=(),
            constants=(),
            imports=(),
            available=False,
            restriction="non_python",
        )
    # Prefer full file for interface when within hard max; else use excerpt.
    try:
        _root, canon, full = _resolve_regular_file(repo_root, excerpt.path)
        data = full.read_bytes()
        if len(data) > HARD_MAX_EXCERPT_BUDGET_BYTES * 4:
            source = excerpt.text
            file_digest = excerpt.file_sha256
        else:
            source = data.decode("utf-8")
            file_digest = _digest(data)
            if _content_looks_secret(source):
                return _seal_interface_summary(
                    path=canon,
                    base_sha=base_sha,
                    file_sha256=file_digest,
                    classes=(),
                    functions=(),
                    constants=(),
                    imports=(),
                    available=False,
                    restriction="secret_content",
                )
    except (ContextEngineError, OSError, UnicodeDecodeError):
        source = excerpt.text
        file_digest = excerpt.file_sha256
        canon = excerpt.path

    try:
        tree = ast.parse(source, filename=canon)
    except SyntaxError:
        return _seal_interface_summary(
            path=canon,
            base_sha=base_sha,
            file_sha256=file_digest,
            classes=(),
            functions=(),
            constants=(),
            imports=(),
            available=False,
            restriction="parse_failure",
        )

    classes = []
    functions = []
    constants = []
    imports = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = []
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(_format_signature(child))
            entry = {
                "name": node.name,
                "methods": methods[:MAX_INTERFACE_SYMBOLS],
                "bases": [
                    ast.dump(b) if not isinstance(b, ast.Name) else b.id
                    for b in node.bases[:8]
                ],
            }
            classes.append(entry)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_format_signature(node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                name = _safe_constant_name(target)
                if name:
                    constants.append(name)
        elif isinstance(node, ast.AnnAssign):
            name = _safe_constant_name(node.target)
            if name:
                constants.append(name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                if node.level:
                    # Relative import — record conservatively without resolving.
                    imports.append("." * node.level + mod + ":" + alias.name)
                else:
                    imports.append((mod + ":" + alias.name) if mod else alias.name)

    return _seal_interface_summary(
        path=canon,
        base_sha=base_sha,
        file_sha256=file_digest,
        classes=classes[:MAX_INTERFACE_SYMBOLS],
        functions=functions[:MAX_INTERFACE_SYMBOLS],
        constants=sorted(set(constants))[:MAX_INTERFACE_SYMBOLS],
        imports=imports[:MAX_IMPORTS],
        available=True,
        restriction=None,
    )


def interface_summary_for_neighbors(repo_root, *, base_sha, paths):
    """Build interface summaries for neighbor modules (bounded)."""
    if type(paths) not in (list, tuple):
        raise ContextEngineError("paths malformed")
    if len(paths) > MAX_EXCERPTS:
        raise ContextEngineError("paths exceed bound")
    out = []
    for path in paths:
        if not str(path).endswith(".py"):
            continue
        out.append(
            enrich_interface_summary(
                repo_root, base_sha=base_sha, path=path
            )
        )
        if len(out) >= MAX_EXCERPTS:
            break
    return tuple(out)



# ---------------------------------------------------------------------------
# CB-029E — deterministic ADR / arch / docs / tests retrieval (no LLM)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DependencySummary:
    """Component dependency/dependent evidence from System Model."""

    component_id: str
    dependencies: tuple
    dependents: tuple
    summary_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _DEP_TOKEN:
            raise ContextEngineError(
                "dependency summary requires trusted system construction"
            )
        if _COMPONENT_ID.fullmatch(self.component_id) is None:
            raise ContextEngineError("component id malformed")
        if type(self.dependencies) is not tuple or type(self.dependents) is not tuple:
            raise ContextEngineError("dependency lists malformed")
        _require_no_authority(self)
        _require_sha256(self.summary_sha256, "dep summary digest")
        if self.summary_sha256 != _digest(self._payload()):
            raise ContextEngineError("dep summary digest mismatch")

    def _body(self):
        body = {
            "component_id": self.component_id,
            "dependencies": list(self.dependencies),
            "dependents": list(self.dependents),
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["summary_sha256"] = self.summary_sha256
        return body


def seal_dependency_summary(model, component_id):
    if not isinstance(model, SystemModel):
        raise ContextEngineError("model invalid")
    if not isinstance(component_id, str) or (
        _COMPONENT_ID.fullmatch(component_id) is None
    ):
        raise ContextEngineError("component id malformed")
    deps = tuple(
        sorted(
            dependencies_of(model, component_id),
            key=lambda e: (
                e.get("imported_name", ""),
                e.get("kind", ""),
                e.get("source_path", ""),
            ),
        )
    )
    dents = tuple(
        sorted(
            dependents_of(model, component_id),
            key=lambda e: (
                e.get("source_component_id", ""),
                e.get("imported_name", ""),
                e.get("source_path", ""),
            ),
        )
    )
    values = {
        "component_id": component_id,
        "dependencies": deps,
        "dependents": dents,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(DependencySummary)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return DependencySummary(
        **values,
        summary_sha256=_digest(provisional._payload()),
        _token=_DEP_TOKEN,
    )


def _is_architecture_doc(path):
    lower = path.lower()
    name = path.split("/")[-1]
    if "/architecture/" in lower or "/adr/" in lower:
        return True
    upper = name.upper()
    if upper.startswith("ADR") or "ARCHITECTURE" in upper:
        return True
    if path.startswith("docs/future/") and name.endswith(".md"):
        # Continuous Builder / system intelligence docs are architecture-adjacent.
        if any(
            key in upper
            for key in (
                "SYSTEM", "ARCHITECTURE", "THREAT", "TRUST", "TCB",
                "CONTINUOUS_BUILDER", "WORKER",
            )
        ):
            return True
    return False


def _is_test_path(path):
    name = path.split("/")[-1]
    return (
        path.startswith("tests/")
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _module_stem_from_path(path):
    if not path.endswith(".py"):
        return None
    name = path.split("/")[-1]
    if name == "__init__.py":
        return None
    return name[:-3]


def classify_test_relation(seed_paths, test_path):
    """Distinguish related / required / probable / unknown — deterministic."""
    if not _is_test_path(test_path):
        return "unknown"
    test_name = test_path.split("/")[-1]
    stems = []
    for seed in seed_paths:
        stem = _module_stem_from_path(seed)
        if stem:
            stems.append(stem)
    for stem in stems:
        # required: test_<stem> or <stem>_test
        if test_name in (f"test_{stem}.py", f"{stem}_test.py"):
            return "required"
        if stem in test_name:
            return "related"
    # probable: same component directory naming
    for seed in seed_paths:
        seed_dir = "/".join(seed.split("/")[:-1])
        test_dir = "/".join(test_path.split("/")[:-1])
        if seed_dir and (
            test_path.startswith("tests/")
            and seed_dir.replace("backend/", "").replace("/", "_") in test_name
        ):
            return "probable"
        if seed.startswith("backend/continuous_builder/") and (
            "continuous_builder" in test_name or "context_engine" in test_name
        ):
            return "probable"
    return "unknown"


def retrieve_architecture_evidence(
    repo_root, model, *, base_sha, seed_paths=(), budget_docs=MAX_ARCH_DOCS
):
    """Deterministic arch/ADR/docs retrieval with digests/regions — no LLM."""
    if not isinstance(model, SystemModel):
        raise ContextEngineError("model invalid")
    _require_base_sha(base_sha)
    if type(budget_docs) is not int or budget_docs < 1 or budget_docs > MAX_ARCH_DOCS:
        raise ContextEngineError("budget_docs out of bounds")
    docs = [
        item.path for item in model.inventory.files
        if item.category == "documentation" or item.path.endswith(".md")
    ]
    selected = []
    for path in sorted(docs):
        if not _is_architecture_doc(path):
            continue
        if classify_secret_path(path) is not None:
            continue
        selected.append(path)
        if len(selected) >= budget_docs:
            break
    evidence = []
    for path in selected:
        ex = extract_excerpt(
            repo_root,
            base_sha=base_sha,
            path=path,
            region=(1, 80),
            budget_bytes=DEFAULT_EXCERPT_BUDGET_BYTES,
        )
        evidence.append(ex)
    return tuple(evidence)


def retrieve_related_tests(
    model, *, seed_paths=(), budget_tests=MAX_RELATED_TESTS
):
    """Deterministic related-tests listing with relation kinds."""
    if not isinstance(model, SystemModel):
        raise ContextEngineError("model invalid")
    if type(seed_paths) not in (list, tuple):
        raise ContextEngineError("seed_paths malformed")
    if type(budget_tests) is not int or budget_tests < 1 or (
        budget_tests > MAX_RELATED_TESTS
    ):
        raise ContextEngineError("budget_tests out of bounds")
    seeds = tuple(_canonical_repo_path(p) for p in seed_paths)
    tests = [
        item.path for item in model.inventory.files
        if item.category == "test" or _is_test_path(item.path)
    ]
    scored = []
    for path in tests:
        kind = classify_test_relation(seeds, path)
        if kind == "unknown":
            # Still include as unknown only when under tests/ and component-ish
            continue
        scored.append((kind, path))
    order = {"required": 0, "related": 1, "probable": 2, "unknown": 3}
    scored.sort(key=lambda item: (order[item[0]], item[1]))
    out = []
    for kind, path in scored[:budget_tests]:
        out.append(
            {
                "path": path,
                "relation": kind,
                "digest": next(
                    (
                        item.content_sha256
                        for item in model.inventory.files
                        if item.path == path
                    ),
                    _digest(b""),
                ),
            }
        )
    # If nothing matched, include unknown tests sharing component prefix.
    if not out:
        for path in sorted(tests)[:budget_tests]:
            out.append(
                {
                    "path": path,
                    "relation": "unknown",
                    "digest": next(
                        (
                            item.content_sha256
                            for item in model.inventory.files
                            if item.path == path
                        ),
                        _digest(b""),
                    ),
                }
            )
    return tuple(out)



# ---------------------------------------------------------------------------
# CB-029F — package assembly + hard budgets + receipt
# ---------------------------------------------------------------------------


# Priority order when package is full (critical first):
_ASSEMBLY_PRIORITY = (
    "task_contract",
    "authority_non_goals",
    "editable_path",
    "acceptance",
    "tcb_warning",
    "interface_summary",
    "dependency_summary",
    "test_ref",
    "architecture_evidence",
    "file_excerpt",  # supporting excerpts last among content
)


@dataclass(frozen=True)
class ContextPackage:
    """Bounded context package — disposable view, not a source of truth."""

    engine_version: str
    request_sha256: str
    model_sha256: str
    base_sha: str
    completeness: str
    excerpts: tuple
    interfaces: tuple
    dependency_summaries: tuple
    tests: tuple
    architecture: tuple
    source_refs: tuple
    uncertainties: tuple
    tcb_warnings: tuple
    bytes_used: int
    token_estimate: int
    needs_review: bool
    package_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _PACKAGE_TOKEN:
            raise ContextEngineError(
                "context package requires trusted system construction"
            )
        if self.engine_version != ENGINE_VERSION:
            raise ContextEngineError("engine version unsupported")
        _require_sha256(self.request_sha256, "request digest")
        _require_sha256(self.model_sha256, "model digest")
        _require_base_sha(self.base_sha)
        if self.completeness not in COMPLETENESS_STATES:
            raise ContextEngineError("completeness unsupported")
        if type(self.bytes_used) is not int or self.bytes_used < 0:
            raise ContextEngineError("bytes_used malformed")
        if type(self.token_estimate) is not int or self.token_estimate < 0:
            raise ContextEngineError("token_estimate malformed")
        if type(self.needs_review) is not bool:
            raise ContextEngineError("needs_review malformed")
        for name in (
            "excerpts", "interfaces", "dependency_summaries", "tests",
            "architecture", "source_refs", "uncertainties", "tcb_warnings",
        ):
            value = getattr(self, name)
            if type(value) is not tuple:
                raise ContextEngineError(f"{name} malformed")
        if len(self.excerpts) > MAX_EXCERPTS:
            raise ContextEngineError("excerpts exceed bound")
        _require_no_authority(self)
        _require_sha256(self.package_sha256, "package digest")
        if self.package_sha256 != _digest(self._payload()):
            raise ContextEngineError("package digest mismatch")

    def _body(self):
        body = {
            "architecture": [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in self.architecture
            ],
            "base_sha": self.base_sha,
            "bytes_used": self.bytes_used,
            "completeness": self.completeness,
            "dependency_summaries": [
                item.to_dict() for item in self.dependency_summaries
            ],
            "engine_version": ENGINE_VERSION,
            "excerpts": [item.to_dict() for item in self.excerpts],
            "interfaces": [item.to_dict() for item in self.interfaces],
            "model_sha256": self.model_sha256,
            "needs_review": self.needs_review,
            "request_sha256": self.request_sha256,
            "source_refs": [item.to_dict() for item in self.source_refs],
            "tcb_warnings": list(self.tcb_warnings),
            "tests": list(self.tests),
            "token_estimate": self.token_estimate,
            "uncertainties": [item.to_dict() for item in self.uncertainties],
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["package_sha256"] = self.package_sha256
        return body

    def canonical_bytes(self):
        return _canonical(self.to_dict())


def _seal_package(**fields):
    values = dict(fields)
    values["engine_version"] = ENGINE_VERSION
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(ContextPackage)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ContextPackage(
        **values,
        package_sha256=_digest(provisional._payload()),
        _token=_PACKAGE_TOKEN,
    )


@dataclass(frozen=True)
class ContextReceipt:
    """Receipt binding package/task/model/base digests and counts."""

    package_sha256: str
    request_sha256: str
    model_sha256: str
    base_sha: str
    excerpt_count: int
    interface_count: int
    test_count: int
    architecture_count: int
    uncertainty_count: int
    bytes_used: int
    token_estimate: int
    completeness: str
    needs_review: bool
    flags: tuple
    receipt_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _RECEIPT_TOKEN:
            raise ContextEngineError(
                "receipt requires trusted system construction"
            )
        for label, value in (
            ("package", self.package_sha256),
            ("request", self.request_sha256),
            ("model", self.model_sha256),
            ("receipt", self.receipt_sha256),
        ):
            _require_sha256(value, f"{label} digest")
        _require_base_sha(self.base_sha)
        if self.completeness not in COMPLETENESS_STATES:
            raise ContextEngineError("completeness unsupported")
        if type(self.flags) is not tuple:
            raise ContextEngineError("flags malformed")
        _require_no_authority(self)
        if self.receipt_sha256 != _digest(self._payload()):
            raise ContextEngineError("receipt digest mismatch")

    def _body(self):
        body = {
            "architecture_count": self.architecture_count,
            "base_sha": self.base_sha,
            "bytes_used": self.bytes_used,
            "completeness": self.completeness,
            "excerpt_count": self.excerpt_count,
            "flags": list(self.flags),
            "interface_count": self.interface_count,
            "model_sha256": self.model_sha256,
            "needs_review": self.needs_review,
            "package_sha256": self.package_sha256,
            "request_sha256": self.request_sha256,
            "test_count": self.test_count,
            "token_estimate": self.token_estimate,
            "uncertainty_count": self.uncertainty_count,
        }
        body.update(_authority_body())
        return body

    def _payload(self):
        return _canonical(self._body())

    def to_dict(self):
        body = self._body()
        body["receipt_sha256"] = self.receipt_sha256
        return body


def _seal_receipt(**fields):
    values = dict(fields)
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(ContextReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return ContextReceipt(
        **values,
        receipt_sha256=_digest(provisional._payload()),
        _token=_RECEIPT_TOKEN,
    )


def _estimate_tokens(byte_count):
    # Conservative rough estimate only — never used as authority.
    if byte_count <= 0:
        return 0
    return max(1, (byte_count + AVG_CHARS_PER_TOKEN - 1) // AVG_CHARS_PER_TOKEN)


def _measure(obj):
    if hasattr(obj, "canonical_bytes"):
        return len(obj.canonical_bytes())
    if hasattr(obj, "to_dict"):
        return len(_canonical(obj.to_dict()))
    return len(_canonical(obj))


def assemble_context_package(repo_root, request, model):
    """Assemble bounded context package from plan + extractions.

    Priority when full: task contract → authority/non-goals → editable paths
    → acceptance → TCB warnings → interfaces → deps → tests → arch →
    supporting. Never silently drop critical; incomplete/needs_review if
    critical missing. Completeness is descriptive only.
    """
    if not isinstance(request, ContextTaskRequest):
        raise ContextEngineError("request invalid")
    if not isinstance(model, SystemModel):
        raise ContextEngineError("model invalid")
    if request.base_sha != model.base_sha:
        raise ContextEngineError("request/model base_sha mismatch")
    budget = request.budget
    if budget.package_budget_bytes > HARD_MAX_PACKAGE_BUDGET_BYTES:
        raise ContextEngineError("package budget exceeds hard max")

    plan = plan_context_selection(request, model)
    uncertainties = list(plan.uncertainties)
    excerpts = []
    interfaces = []
    dep_summaries = []
    tests = []
    architecture = []
    source_refs = []
    tcb_warnings = []
    flags = []
    bytes_used = 0
    critical_missing = False
    restricted_hit = False

    # Critical envelope: task contract + non-goals + acceptance (always first)
    contract_blob = {
        "kind": "task_contract",
        "task_id": request.task_id,
        "objective": request.objective,
        "request_sha256": request.request_sha256,
        "base_sha": request.base_sha,
    }
    non_goals_blob = {
        "kind": "authority_non_goals",
        "non_goals": list(request.non_goals),
        "authority_flags": _zero_authority_dict(),
        "write_permission_granted": False,
    }
    acceptance_blob = {
        "kind": "acceptance",
        "acceptance": list(request.acceptance),
    }
    for blob in (contract_blob, non_goals_blob, acceptance_blob):
        size = len(_canonical(blob))
        if bytes_used + size > budget.package_budget_bytes:
            critical_missing = True
            uncertainties.append(
                seal_uncertainty(
                    kind="critical_missing",
                    subject=blob["kind"],
                    detail_code="budget_blocked_critical",
                )
            )
            flags.append("critical_budget_pressure")
            break
        bytes_used += size
        source_refs.append(
            seal_source_ref(
                kind=blob["kind"],
                path=None,
                selection_tag="REQUIRED",
                digest=_digest(_canonical(blob)),
            )
        )

    # Editable / allowed paths as explicit refs
    for path in request.scope.allowed_paths:
        blob = {"kind": "editable_path", "path": path, "editable_intent": True}
        size = len(_canonical(blob))
        if bytes_used + size > budget.package_budget_bytes:
            critical_missing = True
            uncertainties.append(
                seal_uncertainty(
                    kind="critical_missing",
                    subject=path,
                    detail_code="editable_path_omitted",
                )
            )
            continue
        bytes_used += size
        # Bind inventory digest when present
        digest = next(
            (
                item.content_sha256
                for item in model.inventory.files
                if item.path == path
            ),
            _digest(path),
        )
        source_refs.append(
            seal_source_ref(
                kind="editable_path",
                path=path,
                selection_tag="REQUIRED",
                digest=digest,
            )
        )
        if is_tcb_path(path):
            warning = {
                "path": path,
                "is_tcb": True,
                "detail_code": "tcb_editable_intent",
                "classification": model_tcb_classification(model, path),
            }
            # Strip any accidental large payloads — classification is small.
            wsize = len(_canonical(warning))
            if bytes_used + wsize <= budget.package_budget_bytes:
                bytes_used += wsize
                tcb_warnings.append(warning)

    # REQUIRED excerpts from plan (critical)
    required_items = [
        item for item in plan.items
        if item.selection_tag == "REQUIRED" and item.path is not None
        and item.reason_code != "secret_excluded"
    ]
    supporting_items = [
        item for item in plan.items
        if item.selection_tag in ("SUPPORTING", "POSSIBLE")
        and item.path is not None
    ]

    def _add_excerpt(item, tag):
        nonlocal bytes_used, critical_missing, restricted_hit
        if len(excerpts) >= budget.max_excerpts:
            return False
        if item.path in request.scope.forbidden_paths:
            return False
        if classify_secret_path(item.path) is not None:
            restricted_hit = True
            uncertainties.append(
                seal_uncertainty(
                    kind="restricted_secret",
                    subject=item.path,
                    detail_code="omitted_from_package",
                )
            )
            return False
        ex = extract_excerpt(
            repo_root,
            base_sha=request.base_sha,
            path=item.path,
            budget_bytes=budget.excerpt_budget_bytes,
        )
        size = _measure(ex)
        if bytes_used + size > budget.package_budget_bytes:
            if tag == "REQUIRED":
                critical_missing = True
                uncertainties.append(
                    seal_uncertainty(
                        kind="critical_missing",
                        subject=item.path,
                        detail_code="required_excerpt_budget",
                    )
                )
            else:
                uncertainties.append(
                    seal_uncertainty(
                        kind="budget_exhausted",
                        subject=item.path,
                        detail_code="supporting_omitted",
                    )
                )
            return False
        if not ex.available:
            if ex.restriction and "secret" in ex.restriction:
                restricted_hit = True
            if tag == "REQUIRED":
                critical_missing = True
                uncertainties.append(
                    seal_uncertainty(
                        kind="critical_missing",
                        subject=item.path,
                        detail_code=ex.restriction or "unavailable",
                    )
                )
            else:
                uncertainties.append(
                    seal_uncertainty(
                        kind="missing_source",
                        subject=item.path,
                        detail_code=ex.restriction or "unavailable",
                    )
                )
            # Still record unavailable structured excerpt without secret bytes.
            excerpts.append(ex)
            bytes_used += size
            return True
        excerpts.append(ex)
        bytes_used += size
        region = None
        if ex.available and ex.start_line >= 1 and ex.end_line >= ex.start_line:
            region = (ex.start_line, ex.end_line)
        source_refs.append(
            seal_source_ref(
                kind="file_excerpt",
                path=ex.path,
                selection_tag=tag,
                digest=ex.excerpt_sha256,
                region=region,
            )
        )
        if is_tcb_path(ex.path):
            warning = {
                "path": ex.path,
                "is_tcb": True,
                "detail_code": "tcb_visible_in_context",
            }
            wsize = len(_canonical(warning))
            if bytes_used + wsize <= budget.package_budget_bytes:
                bytes_used += wsize
                tcb_warnings.append(warning)
        return True

    for item in required_items:
        if len(excerpts) >= budget.max_excerpts:
            break
        _add_excerpt(item, "REQUIRED")

    # Interfaces for required python neighbors
    iface_paths = []
    for item in required_items:
        if item.path and item.path.endswith(".py") and item.path not in iface_paths:
            iface_paths.append(item.path)
    for item in supporting_items:
        if item.path and item.path.endswith(".py") and item.selection_tag == "SUPPORTING":
            if item.path not in iface_paths:
                iface_paths.append(item.path)
        if len(iface_paths) >= 16:
            break
    for path in iface_paths[:16]:
        summary = enrich_interface_summary(
            repo_root, base_sha=request.base_sha, path=path
        )
        size = _measure(summary)
        if bytes_used + size > budget.package_budget_bytes:
            uncertainties.append(
                seal_uncertainty(
                    kind="budget_exhausted",
                    subject=path,
                    detail_code="interface_omitted",
                )
            )
            continue
        interfaces.append(summary)
        bytes_used += size
        if summary.available:
            source_refs.append(
                seal_source_ref(
                    kind="interface_summary",
                    path=path,
                    selection_tag="SUPPORTING",
                    digest=summary.summary_sha256,
                )
            )
        elif summary.restriction == "parse_failure":
            uncertainties.append(
                seal_uncertainty(
                    kind="parse_failure",
                    subject=path,
                    detail_code="ast_failed",
                )
            )

    # Dependency summaries for seed components
    comp_ids = list(request.scope.components)
    for item in plan.items:
        if item.component_id and item.component_id not in comp_ids:
            if item.selection_tag == "REQUIRED":
                comp_ids.append(item.component_id)
    for cid in comp_ids[: budget.max_components]:
        dep = seal_dependency_summary(model, cid)
        size = _measure(dep)
        if bytes_used + size > budget.package_budget_bytes:
            uncertainties.append(
                seal_uncertainty(
                    kind="budget_exhausted",
                    subject=cid,
                    detail_code="deps_omitted",
                )
            )
            continue
        dep_summaries.append(dep)
        bytes_used += size

    # Related tests
    seed_paths = list(request.scope.seed_paths) + list(request.scope.allowed_paths)
    related = retrieve_related_tests(model, seed_paths=seed_paths)
    for test in related:
        size = len(_canonical(test))
        if bytes_used + size > budget.package_budget_bytes:
            uncertainties.append(
                seal_uncertainty(
                    kind="budget_exhausted",
                    subject=test["path"],
                    detail_code="test_omitted",
                )
            )
            break
        tests.append(test)
        bytes_used += size
        source_refs.append(
            seal_source_ref(
                kind="test_ref",
                path=test["path"],
                selection_tag="SUPPORTING",
                digest=test["digest"],
            )
        )

    # Architecture evidence
    arch = retrieve_architecture_evidence(
        repo_root,
        model,
        base_sha=request.base_sha,
        seed_paths=seed_paths,
    )
    for ex in arch:
        size = _measure(ex)
        if bytes_used + size > budget.package_budget_bytes:
            uncertainties.append(
                seal_uncertainty(
                    kind="budget_exhausted",
                    subject=ex.path,
                    detail_code="arch_omitted",
                )
            )
            break
        architecture.append(ex)
        bytes_used += size
        if ex.available:
            region = None
            if ex.start_line >= 1 and ex.end_line >= ex.start_line:
                region = (ex.start_line, ex.end_line)
            source_refs.append(
                seal_source_ref(
                    kind="architecture_evidence",
                    path=ex.path,
                    selection_tag="SUPPORTING",
                    digest=ex.excerpt_sha256,
                    region=region,
                )
            )

    # Supporting excerpts last
    for item in supporting_items:
        if len(excerpts) >= budget.max_excerpts:
            uncertainties.append(
                seal_uncertainty(
                    kind="budget_exhausted",
                    subject="excerpts",
                    detail_code="excerpt_count_bound",
                )
            )
            break
        if any(ex.path == item.path for ex in excerpts):
            continue
        if not _add_excerpt(item, item.selection_tag):
            # budget stop for supporting is fine
            if any(
                u.detail_code == "supporting_omitted"
                for u in uncertainties[-3:]
            ):
                # keep going until hard stop on bytes repeatedly
                pass

    # Completeness (descriptive only — never merge/execute/trust/approve)
    if critical_missing:
        completeness = "incomplete"
        needs_review = True
        flags.append("critical_missing")
    elif restricted_hit and uncertainties:
        completeness = "restricted"
        needs_review = True
        flags.append("restricted_content")
    elif any(
        item.kind in ("ambiguous_ownership", "model_uncertainty")
        for item in uncertainties
    ) and any(
        item.kind == "critical_missing" for item in uncertainties
    ):
        completeness = "conflicting"
        needs_review = True
    elif uncertainties:
        completeness = "sufficient_with_uncertainty"
        needs_review = True
    elif not excerpts and not request.scope.seed_paths:
        completeness = "unknown"
        needs_review = True
    else:
        completeness = "sufficient"
        needs_review = False

    if len(uncertainties) > MAX_UNCERTAINTIES:
        uncertainties = uncertainties[:MAX_UNCERTAINTIES]
        flags.append("uncertainty_truncated")

    # Canonical order of collections
    excerpts = tuple(
        sorted(excerpts, key=lambda item: (item.path, item.start_line))
    )
    interfaces = tuple(sorted(interfaces, key=lambda item: item.path))
    dep_summaries = tuple(
        sorted(dep_summaries, key=lambda item: item.component_id)
    )
    tests = tuple(sorted(tests, key=lambda item: item["path"]))
    architecture = tuple(sorted(architecture, key=lambda item: item.path))
    source_refs = tuple(
        sorted(
            source_refs,
            key=lambda item: (item.kind, item.path or "", item.digest),
        )
    )
    uncertainties = tuple(
        sorted(
            uncertainties,
            key=lambda item: (item.kind, item.subject, item.detail_code),
        )
    )
    tcb_warnings = tuple(
        sorted(tcb_warnings, key=lambda item: item.get("path", ""))
    )
    flags = tuple(sorted(set(flags)))

    package = _seal_package(
        request_sha256=request.request_sha256,
        model_sha256=model.model_sha256,
        base_sha=request.base_sha,
        completeness=completeness,
        excerpts=excerpts,
        interfaces=interfaces,
        dependency_summaries=dep_summaries,
        tests=tests,
        architecture=architecture,
        source_refs=source_refs,
        uncertainties=uncertainties,
        tcb_warnings=tcb_warnings,
        bytes_used=bytes_used,
        token_estimate=_estimate_tokens(bytes_used),
        needs_review=needs_review,
    )
    receipt = _seal_receipt(
        package_sha256=package.package_sha256,
        request_sha256=request.request_sha256,
        model_sha256=model.model_sha256,
        base_sha=request.base_sha,
        excerpt_count=len(excerpts),
        interface_count=len(interfaces),
        test_count=len(tests),
        architecture_count=len(architecture),
        uncertainty_count=len(uncertainties),
        bytes_used=bytes_used,
        token_estimate=package.token_estimate,
        completeness=completeness,
        needs_review=needs_review,
        flags=flags,
    )
    return package, receipt
