"""Trusted Computing Base (TCB) path registry for Continuous Builder.

CB-027A defines an immutable, content-addressed registry of the minimal
referee / authority surfaces that Continuous Builder must treat as trusted
policy.  It classifies repository-relative paths only.  It does not enforce
worker rejection, does not grant publication/queue/GitHub/merge authority,
and does not expose a worker-facing constructor that can mark arbitrary
paths as protected.

The sole public factory is ``create_mootos_tcb_registry_v1()``.  Query
helpers always derive from that canonical registry.  Snapshot receipts are
evidence only: every authority flag is structurally false.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field

from .paths import PathCanonicalizationError, canonicalize_repo_path


class TrustedPolicyError(ValueError):
    """Raised when TCB registry evidence cannot be produced safely."""


POLICY_VERSION = "cb-trusted-policy-tcb-v1"
REGISTRY_VERSION = "mootos-tcb-registry-v1"
MAX_COMPONENTS = 64
MAX_PATHS_PER_COMPONENT = 32
MAX_PROTECTED_PATHS = 256
MAX_REGISTRY_BYTES = 64 * 1024
MAX_SNAPSHOT_BYTES = 32 * 1024
MAX_COMPONENT_ID_BYTES = 64
MAX_RATIONALE_BYTES = 64

CATEGORIES = frozenset({
    "verifier",
    "sandbox",
    "execution_policy",
    "artifact_intake",
    "approval_authority",
    "publication_authority",
    "worker_authorization",
    "trusted_policy",
})

CHANGE_POLICIES = frozenset({
    "human_only",
    "trusted_system_only",
    "protected_core_review",
})

AUTHORITY_FLAGS = (
    "publication_authorized",
    "queue_transition_authorized",
    "github_authorized",
    "merge_authorized",
    "main_advancement_authorized",
    "result_trusted",
    "worker_output_trusted",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMPONENT_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RATIONALE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_GLOB_META = re.compile(r"[*?\[\]{}]")
_SELF_PATH = "backend/continuous_builder/trusted_policy.py"
_COMPONENT_TOKEN = object()
_REGISTRY_TOKEN = object()
_SNAPSHOT_TOKEN = object()


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _sha256(value, label):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise TrustedPolicyError(f"{label} is malformed")


def _canonical_tcb_path(value, label):
    if not isinstance(value, str) or not value:
        raise TrustedPolicyError(f"{label} is malformed")
    if _GLOB_META.search(value):
        raise TrustedPolicyError(f"{label} must not use globs")
    if value.endswith("/"):
        raise TrustedPolicyError(f"{label} must be an exact file path")
    try:
        canonical = canonicalize_repo_path(value)
    except PathCanonicalizationError as error:
        raise TrustedPolicyError(f"{label} is unsafe") from error
    if canonical != value:
        raise TrustedPolicyError(f"{label} is not canonical")
    segments = value.split("/")
    if any(segment in (".git", ".env") for segment in segments):
        raise TrustedPolicyError(f"{label} names a forbidden path class")
    if any(segment.startswith(".") for segment in segments):
        raise TrustedPolicyError(f"{label} names a dot-segment path")
    return canonical


def _canonical_paths(values, label, maximum):
    if type(values) is not tuple:
        raise TrustedPolicyError(f"{label} is malformed")
    if not values:
        raise TrustedPolicyError(f"{label} must be non-empty")
    if len(values) > maximum:
        raise TrustedPolicyError(f"{label} exceeds bound")
    normalized = tuple(_canonical_tcb_path(value, label) for value in values)
    if normalized != tuple(sorted(set(normalized))):
        raise TrustedPolicyError(f"{label} is not canonical")
    if len({value.casefold() for value in normalized}) != len(normalized):
        raise TrustedPolicyError(f"{label} collides by case")
    return normalized


@dataclass(frozen=True)
class TrustedComponent:
    """One immutable TCB component with exclusive path ownership."""

    component_id: str
    category: str
    paths: tuple
    rationale_code: str
    change_policy: str
    registry_version: str
    component_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _COMPONENT_TOKEN:
            raise TrustedPolicyError(
                "trusted component requires trusted system construction"
            )
        if (
            not isinstance(self.component_id, str)
            or _COMPONENT_ID.fullmatch(self.component_id) is None
            or len(self.component_id.encode("utf-8")) > MAX_COMPONENT_ID_BYTES
        ):
            raise TrustedPolicyError("component ID is malformed")
        if self.category not in CATEGORIES:
            raise TrustedPolicyError("component category is unsupported")
        if self.change_policy not in CHANGE_POLICIES:
            raise TrustedPolicyError("change policy is unsupported")
        if self.registry_version != REGISTRY_VERSION:
            raise TrustedPolicyError("component registry version mismatch")
        if (
            not isinstance(self.rationale_code, str)
            or _RATIONALE.fullmatch(self.rationale_code) is None
            or len(self.rationale_code.encode("utf-8")) > MAX_RATIONALE_BYTES
        ):
            raise TrustedPolicyError("rationale code is malformed")
        paths = _canonical_paths(
            self.paths, "component paths", MAX_PATHS_PER_COMPONENT
        )
        object.__setattr__(self, "paths", paths)
        _sha256(self.component_sha256, "component digest")
        if self.component_sha256 != _digest(self._payload()):
            raise TrustedPolicyError("component digest mismatch")

    def _body(self):
        return {
            "category": self.category,
            "change_policy": self.change_policy,
            "component_id": self.component_id,
            "paths": list(self.paths),
            "rationale_code": self.rationale_code,
            "registry_version": self.registry_version,
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
    category,
    paths,
    rationale_code,
    change_policy,
):
    values = {
        "component_id": component_id,
        "category": category,
        "paths": tuple(sorted(paths)),
        "rationale_code": rationale_code,
        "change_policy": change_policy,
        "registry_version": REGISTRY_VERSION,
    }
    provisional = object.__new__(TrustedComponent)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return TrustedComponent(
        **values,
        component_sha256=_digest(provisional._payload()),
        _token=_COMPONENT_TOKEN,
    )


@dataclass(frozen=True)
class TrustedPolicyRegistry:
    """Canonical immutable TCB registry for one policy version."""

    version: str
    components: tuple
    protected_paths: tuple
    registry_sha256: str
    policy_version: str = POLICY_VERSION
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _REGISTRY_TOKEN:
            raise TrustedPolicyError(
                "trusted policy registry requires trusted system construction"
            )
        if self.version != REGISTRY_VERSION:
            raise TrustedPolicyError("registry version is unsupported")
        if self.policy_version != POLICY_VERSION:
            raise TrustedPolicyError("policy version is unsupported")
        if type(self.components) is not tuple or not self.components:
            raise TrustedPolicyError("registry components are malformed")
        if len(self.components) > MAX_COMPONENTS:
            raise TrustedPolicyError("registry exceeds component bound")
        if any(
            not isinstance(component, TrustedComponent)
            for component in self.components
        ):
            raise TrustedPolicyError("registry components are invalid")
        ids = tuple(component.component_id for component in self.components)
        if ids != tuple(sorted(set(ids))):
            raise TrustedPolicyError("component IDs are not canonical")
        if len({value.casefold() for value in ids}) != len(ids):
            raise TrustedPolicyError("component IDs collide by case")
        ordered = tuple(
            sorted(self.components, key=lambda item: item.component_id)
        )
        if self.components != ordered:
            raise TrustedPolicyError("components are not deterministically ordered")
        owned = []
        for component in self.components:
            if not component.paths:
                raise TrustedPolicyError("empty component is forbidden")
            owned.extend(component.paths)
        if len(owned) != len(set(owned)):
            raise TrustedPolicyError("overlapping TCB path ownership")
        if len({path.casefold() for path in owned}) != len(owned):
            raise TrustedPolicyError("TCB path ownership collides by case")
        protected = _canonical_paths(
            self.protected_paths, "protected paths", MAX_PROTECTED_PATHS
        )
        if protected != tuple(sorted(set(owned))):
            raise TrustedPolicyError("protected paths do not match components")
        object.__setattr__(self, "protected_paths", protected)
        if _SELF_PATH not in protected:
            raise TrustedPolicyError("registry must protect its own path")
        _sha256(self.registry_sha256, "registry digest")
        if self.registry_sha256 != _digest(self._payload()):
            raise TrustedPolicyError("registry digest mismatch")
        if len(self.canonical_bytes()) > MAX_REGISTRY_BYTES:
            raise TrustedPolicyError("registry exceeds byte bound")

    def _body(self):
        return {
            "components": [component.to_dict() for component in self.components],
            "policy_version": POLICY_VERSION,
            "protected_paths": list(self.protected_paths),
            "version": self.version,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        body = self._body()
        body["registry_sha256"] = self.registry_sha256
        return _canonical(body)

    def to_dict(self):
        body = self._body()
        body["registry_sha256"] = self.registry_sha256
        return body

    def component_for_path(self, path):
        try:
            canonical = _canonical_tcb_path(path, "query path")
        except TrustedPolicyError:
            return None
        for component in self.components:
            if canonical in component.paths:
                return component
        return None


def _seal_registry(components):
    ordered = tuple(sorted(components, key=lambda item: item.component_id))
    protected = tuple(
        sorted({path for component in ordered for path in component.paths})
    )
    values = {
        "version": REGISTRY_VERSION,
        "components": ordered,
        "protected_paths": protected,
        "policy_version": POLICY_VERSION,
    }
    provisional = object.__new__(TrustedPolicyRegistry)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return TrustedPolicyRegistry(
        **values,
        registry_sha256=_digest(provisional._payload()),
        _token=_REGISTRY_TOKEN,
    )


def create_mootos_tcb_registry_v1():
    """Return the canonical MootOS Continuous Builder TCB registry.

    Workers cannot supply arbitrary paths.  The protected set is fixed by
    this trusted factory and includes this module's own path.
    """
    components = (
        _seal_component(
            component_id="cb_artifact_intake",
            category="artifact_intake",
            paths=(
                "backend/continuous_builder/worker_artifact.py",
            ),
            rationale_code="cb_artifact_quarantine_boundary",
            change_policy="protected_core_review",
        ),
        _seal_component(
            component_id="cb_approval_authority",
            category="approval_authority",
            paths=(
                "backend/continuous_builder/chief_builder.py",
            ),
            rationale_code="cb_blueprint_approval_evidence",
            change_policy="human_only",
        ),
        _seal_component(
            component_id="cb_check_runner",
            category="verifier",
            paths=(
                "backend/continuous_builder/check_runner.py",
                "backend/continuous_builder/check_runtime.py",
            ),
            rationale_code="cb_bounded_check_runner",
            change_policy="protected_core_review",
        ),
        _seal_component(
            component_id="cb_publication_authority",
            category="publication_authority",
            paths=(
                "scripts/capability_build/pr_publication_authorization.py",
            ),
            rationale_code="cb_pr_publication_authorization",
            change_policy="human_only",
        ),
        _seal_component(
            component_id="cb_runtime_enforcement",
            category="execution_policy",
            paths=(
                "backend/continuous_builder/runtime_enforcement.py",
            ),
            rationale_code="cb_runtime_enforcement_contract",
            change_policy="protected_core_review",
        ),
        _seal_component(
            component_id="cb_sandbox_policy",
            category="sandbox",
            paths=(
                "backend/continuous_builder/sandbox_policy.py",
            ),
            rationale_code="cb_sandbox_deny_by_default",
            change_policy="protected_core_review",
        ),
        _seal_component(
            component_id="cb_trusted_policy",
            category="trusted_policy",
            paths=(_SELF_PATH,),
            rationale_code="cb_tcb_registry_self_protection",
            change_policy="human_only",
        ),
        _seal_component(
            component_id="cb_verifier_core",
            category="verifier",
            paths=(
                "backend/continuous_builder/adversarial_verifier.py",
                "backend/continuous_builder/verifier_core.py",
            ),
            rationale_code="cb_structural_verifier_referee",
            change_policy="protected_core_review",
        ),
        _seal_component(
            component_id="cb_worker_authorization",
            category="worker_authorization",
            paths=(
                "backend/continuous_builder/worker_authorization.py",
            ),
            rationale_code="cb_dispatch_authorization_boundary",
            change_policy="protected_core_review",
        ),
    )
    return _seal_registry(components)


@dataclass(frozen=True)
class TrustedPolicySnapshot:
    """Evidence-only snapshot of the canonical TCB registry.

    Zero authority: every publication/queue/GitHub/merge/main and trust
    flag is structurally false.  A snapshot never authorizes action.
    """

    registry_sha256: str
    protected_path_count: int
    protected_paths_sha256: str
    component_count: int
    policy_version: str
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
            raise TrustedPolicyError(
                "trusted policy snapshot requires trusted derived evidence"
            )
        if self.policy_version != POLICY_VERSION:
            raise TrustedPolicyError("snapshot policy version is unsupported")
        for value, label in (
            (self.registry_sha256, "registry digest"),
            (self.protected_paths_sha256, "protected paths digest"),
            (self.snapshot_sha256, "snapshot digest"),
        ):
            _sha256(value, label)
        if type(self.protected_path_count) is not int or self.protected_path_count < 1:
            raise TrustedPolicyError("protected path count is malformed")
        if type(self.component_count) is not int or self.component_count < 1:
            raise TrustedPolicyError("component count is malformed")
        if any(getattr(self, name) is not False for name in AUTHORITY_FLAGS):
            raise TrustedPolicyError("snapshot cannot claim authority")
        if self.snapshot_sha256 != _digest(self._payload()):
            raise TrustedPolicyError("snapshot digest mismatch")
        if len(self.canonical_bytes()) > MAX_SNAPSHOT_BYTES:
            raise TrustedPolicyError("snapshot exceeds byte bound")

    def _body(self):
        return {
            "component_count": self.component_count,
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "policy_version": POLICY_VERSION,
            "protected_path_count": self.protected_path_count,
            "protected_paths_sha256": self.protected_paths_sha256,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "registry_sha256": self.registry_sha256,
            "result_trusted": False,
            "worker_output_trusted": False,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        body = self._body()
        body["snapshot_sha256"] = self.snapshot_sha256
        return _canonical(body)

    def to_dict(self):
        body = self._body()
        body["snapshot_sha256"] = self.snapshot_sha256
        return body


def create_trusted_policy_snapshot():
    """Seal an evidence-only snapshot of the canonical TCB registry."""
    registry = create_mootos_tcb_registry_v1()
    values = {
        "registry_sha256": registry.registry_sha256,
        "protected_path_count": len(registry.protected_paths),
        "protected_paths_sha256": _digest(
            _canonical(list(registry.protected_paths))
        ),
        "component_count": len(registry.components),
        "policy_version": POLICY_VERSION,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(TrustedPolicySnapshot)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return TrustedPolicySnapshot(
        **values,
        snapshot_sha256=_digest(provisional._payload()),
        _token=_SNAPSHOT_TOKEN,
    )


@dataclass(frozen=True)
class TCBPathClassification:
    """Read-only classification of one path against the canonical registry."""

    path: str
    component_id: str
    category: str
    change_policy: str
    rationale_code: str
    registry_sha256: str
    is_tcb: bool = True


def classify_tcb_path(path):
    """Classify one path against the canonical TCB registry.

    Unknown, malformed, or non-TCB paths return ``None``.  Callers cannot
    supply an alternate registry; classification always uses
    ``create_mootos_tcb_registry_v1()``.
    """
    registry = create_mootos_tcb_registry_v1()
    try:
        canonical = _canonical_tcb_path(path, "query path")
    except TrustedPolicyError:
        return None
    component = registry.component_for_path(canonical)
    if component is None:
        return None
    return TCBPathClassification(
        path=canonical,
        component_id=component.component_id,
        category=component.category,
        change_policy=component.change_policy,
        rationale_code=component.rationale_code,
        registry_sha256=registry.registry_sha256,
        is_tcb=True,
    )


def is_tcb_path(path):
    """Return True only when the path is in the canonical TCB registry."""
    return classify_tcb_path(path) is not None
