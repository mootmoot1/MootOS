"""TCB enforcement wiring for Continuous Builder (CB-027B).

Turns the canonical TCB registry into an operational decision boundary for
bounded worker-proposed changed-path sets. Classification always derives from
``create_mootos_tcb_registry_v1()`` — callers cannot supply an alternate
registry. Decisions are evidence only: every authority flag is structurally
false. Workers propose paths; the system owns truth.

CB-027B is POLICY ENFORCEMENT only. Receipt sealing and admission wiring are
later slices.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field

from .paths import PathCanonicalizationError, canonicalize_repo_path
from .trusted_policy import (
    CHANGE_POLICIES,
    POLICY_VERSION as REGISTRY_POLICY_VERSION,
    TrustedPolicyError,
    create_mootos_tcb_registry_v1,
)


class TrustedPolicyEnforcementError(ValueError):
    """Raised when TCB enforcement evidence cannot be produced safely."""


ENFORCEMENT_POLICY_VERSION = "cb-trusted-policy-enforcement-v1"

MAX_CHANGED_PATHS = 256
MAX_PATH_BYTES = 4096
MAX_DECISION_BYTES = 64 * 1024
MAX_REASON_CODES = 64
MAX_MATCHES = 256

OUTCOME_ORDINARY = "ordinary_change"
OUTCOME_REVIEW = "protected_change_requires_review"
OUTCOME_FORBIDDEN = "protected_change_forbidden"
OUTCOME_MALFORMED = "malformed_change"
OUTCOME_UNCERTAIN = "policy_uncertain"

OUTCOMES = frozenset({
    OUTCOME_ORDINARY,
    OUTCOME_REVIEW,
    OUTCOME_FORBIDDEN,
    OUTCOME_MALFORMED,
    OUTCOME_UNCERTAIN,
})

# Severity: higher blocks harder. Mixed sets take the worst outcome.
_OUTCOME_SEVERITY = {
    OUTCOME_ORDINARY: 0,
    OUTCOME_REVIEW: 1,
    OUTCOME_FORBIDDEN: 2,
    OUTCOME_UNCERTAIN: 3,
    OUTCOME_MALFORMED: 4,
}

# Worker-facing change_policy → decision outcome for a TCB hit.
_POLICY_OUTCOME = {
    "protected_core_review": OUTCOME_REVIEW,
    "human_only": OUTCOME_FORBIDDEN,
    "trusted_system_only": OUTCOME_FORBIDDEN,
}

AUTHORITY_FLAGS = (
    "publication_authorized",
    "queue_transition_authorized",
    "github_authorized",
    "merge_authorized",
    "main_advancement_authorized",
    "worker_output_trusted",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_GLOB_META = re.compile(r"[*?\[\]{}]")
_DECISION_TOKEN = object()
_MATCH_TOKEN = object()


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _sha256(value, label):
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise TrustedPolicyEnforcementError(f"{label} is malformed")


def _reason_code(value, label="reason code"):
    if not isinstance(value, str) or _REASON.fullmatch(value) is None:
        raise TrustedPolicyEnforcementError(f"{label} is malformed")
    return value


@dataclass(frozen=True)
class TCBMatchRecord:
    """One immutable TCB hit discovered during enforcement."""

    path: str
    component_id: str
    category: str
    change_policy: str
    protected: bool
    outcome: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _MATCH_TOKEN:
            raise TrustedPolicyEnforcementError(
                "TCB match requires trusted system construction"
            )
        if not isinstance(self.path, str) or not self.path:
            raise TrustedPolicyEnforcementError("match path is malformed")
        if not isinstance(self.component_id, str) or not self.component_id:
            raise TrustedPolicyEnforcementError("match component is malformed")
        if not isinstance(self.category, str) or not self.category:
            raise TrustedPolicyEnforcementError("match category is malformed")
        if self.change_policy not in CHANGE_POLICIES:
            raise TrustedPolicyEnforcementError("match policy is unsupported")
        if self.protected is not True:
            raise TrustedPolicyEnforcementError("TCB match must be protected")
        if self.outcome not in OUTCOMES or self.outcome == OUTCOME_ORDINARY:
            raise TrustedPolicyEnforcementError("match outcome is malformed")

    def to_dict(self):
        return {
            "category": self.category,
            "change_policy": self.change_policy,
            "component_id": self.component_id,
            "outcome": self.outcome,
            "path": self.path,
            "protected": True,
        }


def _seal_match(*, path, component_id, category, change_policy, outcome):
    return TCBMatchRecord(
        path=path,
        component_id=component_id,
        category=category,
        change_policy=change_policy,
        protected=True,
        outcome=outcome,
        _token=_MATCH_TOKEN,
    )


@dataclass(frozen=True)
class TrustedPolicyDecision:
    """Operational TCB enforcement decision for one changed-path set.

    Zero authority. A decision never authorizes publication, queue, GitHub,
    merge, Main advancement, or worker-output trust.
    """

    outcome: str
    policy_version: str
    registry_version: str
    registry_sha256: str
    canonical_paths: tuple
    canonical_paths_sha256: str
    ordinary_paths: tuple
    tcb_matches: tuple
    reason_codes: tuple
    input_path_count: int
    decision_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _DECISION_TOKEN:
            raise TrustedPolicyEnforcementError(
                "trusted policy decision requires trusted system construction"
            )
        if self.outcome not in OUTCOMES:
            raise TrustedPolicyEnforcementError("decision outcome unsupported")
        if self.policy_version != ENFORCEMENT_POLICY_VERSION:
            raise TrustedPolicyEnforcementError(
                "enforcement policy version is unsupported"
            )
        if self.registry_version != "mootos-tcb-registry-v1":
            raise TrustedPolicyEnforcementError(
                "registry version is unsupported"
            )
        for value, label in (
            (self.registry_sha256, "registry digest"),
            (self.canonical_paths_sha256, "canonical paths digest"),
            (self.decision_sha256, "decision digest"),
        ):
            _sha256(value, label)
        if type(self.canonical_paths) is not tuple:
            raise TrustedPolicyEnforcementError("canonical paths malformed")
        if type(self.ordinary_paths) is not tuple:
            raise TrustedPolicyEnforcementError("ordinary paths malformed")
        if type(self.tcb_matches) is not tuple:
            raise TrustedPolicyEnforcementError("TCB matches malformed")
        if type(self.reason_codes) is not tuple:
            raise TrustedPolicyEnforcementError("reason codes malformed")
        if len(self.canonical_paths) > MAX_CHANGED_PATHS:
            raise TrustedPolicyEnforcementError("canonical paths exceed bound")
        if len(self.tcb_matches) > MAX_MATCHES:
            raise TrustedPolicyEnforcementError("TCB matches exceed bound")
        if len(self.reason_codes) > MAX_REASON_CODES:
            raise TrustedPolicyEnforcementError("reason codes exceed bound")
        if self.canonical_paths != tuple(sorted(self.canonical_paths)):
            raise TrustedPolicyEnforcementError(
                "canonical paths are not deterministically ordered"
            )
        if len(set(self.canonical_paths)) != len(self.canonical_paths):
            raise TrustedPolicyEnforcementError("canonical paths duplicate")
        if self.ordinary_paths != tuple(sorted(self.ordinary_paths)):
            raise TrustedPolicyEnforcementError(
                "ordinary paths are not deterministically ordered"
            )
        if any(
            not isinstance(match, TCBMatchRecord) for match in self.tcb_matches
        ):
            raise TrustedPolicyEnforcementError("TCB matches are invalid")
        match_paths = tuple(match.path for match in self.tcb_matches)
        if match_paths != tuple(sorted(match_paths)):
            raise TrustedPolicyEnforcementError(
                "TCB matches are not deterministically ordered"
            )
        if len(set(match_paths)) != len(match_paths):
            raise TrustedPolicyEnforcementError("TCB match paths duplicate")
        reasons = tuple(_reason_code(code) for code in self.reason_codes)
        if reasons != tuple(sorted(set(reasons))):
            raise TrustedPolicyEnforcementError(
                "reason codes are not canonical"
            )
        object.__setattr__(self, "reason_codes", reasons)
        if type(self.input_path_count) is not int or self.input_path_count < 0:
            raise TrustedPolicyEnforcementError("input path count malformed")
        if self.canonical_paths_sha256 != _digest(
            _canonical(list(self.canonical_paths))
        ):
            raise TrustedPolicyEnforcementError(
                "canonical paths digest mismatch"
            )
        if any(getattr(self, name) is not False for name in AUTHORITY_FLAGS):
            raise TrustedPolicyEnforcementError(
                "decision cannot claim authority"
            )
        if self.decision_sha256 != _digest(self._payload()):
            raise TrustedPolicyEnforcementError("decision digest mismatch")
        if len(self.canonical_bytes()) > MAX_DECISION_BYTES:
            raise TrustedPolicyEnforcementError("decision exceeds byte bound")

    @property
    def allows_ordinary_continuation(self):
        return self.outcome == OUTCOME_ORDINARY

    @property
    def requires_human_review(self):
        return self.outcome == OUTCOME_REVIEW

    @property
    def blocks_advancement(self):
        return self.outcome != OUTCOME_ORDINARY

    def _body(self):
        return {
            "canonical_paths": list(self.canonical_paths),
            "canonical_paths_sha256": self.canonical_paths_sha256,
            "github_authorized": False,
            "input_path_count": self.input_path_count,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "ordinary_paths": list(self.ordinary_paths),
            "outcome": self.outcome,
            "policy_version": ENFORCEMENT_POLICY_VERSION,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "reason_codes": list(self.reason_codes),
            "registry_sha256": self.registry_sha256,
            "registry_version": self.registry_version,
            "tcb_matches": [match.to_dict() for match in self.tcb_matches],
            "worker_output_trusted": False,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        body = self._body()
        body["decision_sha256"] = self.decision_sha256
        return _canonical(body)

    def to_dict(self):
        body = self._body()
        body["decision_sha256"] = self.decision_sha256
        return body


def _seal_decision(
    *,
    outcome,
    registry,
    canonical_paths,
    ordinary_paths,
    tcb_matches,
    reason_codes,
    input_path_count,
):
    values = {
        "outcome": outcome,
        "policy_version": ENFORCEMENT_POLICY_VERSION,
        "registry_version": registry.version,
        "registry_sha256": registry.registry_sha256,
        "canonical_paths": tuple(canonical_paths),
        "canonical_paths_sha256": _digest(
            _canonical(list(canonical_paths))
        ),
        "ordinary_paths": tuple(ordinary_paths),
        "tcb_matches": tuple(tcb_matches),
        "reason_codes": tuple(sorted(set(reason_codes))),
        "input_path_count": input_path_count,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(TrustedPolicyDecision)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return TrustedPolicyDecision(
        **values,
        decision_sha256=_digest(provisional._payload()),
        _token=_DECISION_TOKEN,
    )


def _fail_closed(registry, reason_codes, outcome, input_path_count):
    return _seal_decision(
        outcome=outcome,
        registry=registry,
        canonical_paths=(),
        ordinary_paths=(),
        tcb_matches=(),
        reason_codes=reason_codes,
        input_path_count=input_path_count,
    )


def _normalize_input_paths(changed_paths):
    if changed_paths is None:
        raise TrustedPolicyEnforcementError("changed paths are missing")
    if isinstance(changed_paths, (str, bytes, bytearray, dict)):
        raise TrustedPolicyEnforcementError("changed paths are malformed")
    try:
        values = list(changed_paths)
    except TypeError as error:
        raise TrustedPolicyEnforcementError(
            "changed paths are malformed"
        ) from error
    if len(values) > MAX_CHANGED_PATHS:
        raise TrustedPolicyEnforcementError("changed paths exceed bound")
    return values


def evaluate_changed_paths_against_tcb(changed_paths):
    """Classify a bounded worker-proposed path set against the canonical TCB.

    Fail closed on absolute/traversal/non-canonical/case-collision/duplicate/
    forbidden/malformed inputs. Never accepts a caller-supplied registry.
    """
    try:
        registry = create_mootos_tcb_registry_v1()
    except TrustedPolicyError as error:
        raise TrustedPolicyEnforcementError(
            "canonical TCB registry unavailable"
        ) from error

    if registry.policy_version != REGISTRY_POLICY_VERSION:
        return _fail_closed(
            registry,
            ("registry_policy_version_mismatch",),
            OUTCOME_UNCERTAIN,
            0,
        )
    if registry.registry_sha256 != _digest(registry._payload()):
        return _fail_closed(
            registry,
            ("registry_digest_mismatch",),
            OUTCOME_UNCERTAIN,
            0,
        )

    try:
        values = _normalize_input_paths(changed_paths)
    except TrustedPolicyEnforcementError as error:
        message = str(error)
        if "exceed bound" in message:
            reason = "changed_paths_exceed_bound"
        elif "missing" in message:
            reason = "changed_paths_missing"
        else:
            reason = "changed_paths_malformed"
        return _fail_closed(registry, (reason,), OUTCOME_MALFORMED, 0)

    input_path_count = len(values)
    if input_path_count == 0:
        return _seal_decision(
            outcome=OUTCOME_ORDINARY,
            registry=registry,
            canonical_paths=(),
            ordinary_paths=(),
            tcb_matches=(),
            reason_codes=("empty_change_set",),
            input_path_count=0,
        )

    reasons = []
    canonical = []
    seen = set()
    seen_case = {}

    for raw in values:
        if not isinstance(raw, str) or not raw:
            reasons.append("path_malformed")
            continue
        if len(raw.encode("utf-8")) > MAX_PATH_BYTES:
            reasons.append("path_exceeds_bound")
            continue
        if _GLOB_META.search(raw):
            reasons.append("path_glob_forbidden")
            continue
        if raw.endswith("/"):
            reasons.append("path_directory_forbidden")
            continue
        if "\\" in raw:
            reasons.append("path_separator_forbidden")
            continue
        try:
            normalized = canonicalize_repo_path(raw)
        except PathCanonicalizationError:
            reasons.append("path_unsafe")
            continue
        if normalized != raw:
            reasons.append("path_not_canonical")
            continue
        segments = raw.split("/")
        if any(segment in (".git", ".env") for segment in segments):
            reasons.append("path_forbidden_class")
            continue
        if any(segment.startswith(".") for segment in segments):
            reasons.append("path_dot_segment")
            continue
        folded = normalized.casefold()
        if folded in seen_case and seen_case[folded] != normalized:
            reasons.append("path_case_collision")
            continue
        if normalized in seen:
            reasons.append("path_duplicate")
            continue
        seen.add(normalized)
        seen_case[folded] = normalized
        canonical.append(normalized)

    if reasons:
        return _fail_closed(
            registry,
            tuple(sorted(set(reasons))),
            OUTCOME_MALFORMED,
            input_path_count,
        )

    canonical = tuple(sorted(canonical))
    ordinary = []
    matches = []
    path_outcomes = []

    for path in canonical:
        component = registry.component_for_path(path)
        if component is None:
            folded = path.casefold()
            colliding = [
                protected
                for protected in registry.protected_paths
                if protected.casefold() == folded and protected != path
            ]
            if colliding:
                return _fail_closed(
                    registry,
                    ("tcb_case_collision",),
                    OUTCOME_MALFORMED,
                    input_path_count,
                )
            ordinary.append(path)
            path_outcomes.append(OUTCOME_ORDINARY)
            continue
        policy = component.change_policy
        if policy not in CHANGE_POLICIES:
            return _fail_closed(
                registry,
                ("unsupported_change_policy",),
                OUTCOME_UNCERTAIN,
                input_path_count,
            )
        outcome = _POLICY_OUTCOME.get(policy)
        if outcome is None:
            return _fail_closed(
                registry,
                ("unsupported_change_policy",),
                OUTCOME_UNCERTAIN,
                input_path_count,
            )
        matches.append(
            _seal_match(
                path=path,
                component_id=component.component_id,
                category=component.category,
                change_policy=policy,
                outcome=outcome,
            )
        )
        path_outcomes.append(outcome)

    matches = tuple(sorted(matches, key=lambda item: item.path))
    ordinary = tuple(sorted(ordinary))
    worst = OUTCOME_ORDINARY
    for item in path_outcomes:
        if _OUTCOME_SEVERITY[item] > _OUTCOME_SEVERITY[worst]:
            worst = item

    reason_codes = []
    if worst == OUTCOME_ORDINARY:
        reason_codes.append("all_ordinary_paths")
    if any(item.outcome == OUTCOME_REVIEW for item in matches):
        reason_codes.append("tcb_protected_core_review")
    if any(item.outcome == OUTCOME_FORBIDDEN for item in matches):
        reason_codes.append("tcb_change_forbidden")
    if matches and worst in (OUTCOME_REVIEW, OUTCOME_FORBIDDEN):
        reason_codes.append("tcb_path_detected")

    return _seal_decision(
        outcome=worst,
        registry=registry,
        canonical_paths=canonical,
        ordinary_paths=ordinary,
        tcb_matches=matches,
        reason_codes=reason_codes,
        input_path_count=input_path_count,
    )
