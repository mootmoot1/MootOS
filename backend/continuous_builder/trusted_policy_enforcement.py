"""TCB enforcement wiring for Continuous Builder (CB-027B).

Turns the canonical TCB registry into an operational decision boundary for
bounded worker-proposed changed-path sets. Classification always derives from
``create_mootos_tcb_registry_v1()`` — callers cannot supply an alternate
registry. Decisions are evidence only: every authority flag is structurally
false. Workers propose paths; the system owns truth.

CB-027C adds immutable decision receipts. CB-027D adds narrow admission
binding for authoritative changed-path inventories. Zero authority.
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
RECEIPT_VERSION = "cb-trusted-policy-decision-receipt-v1"

MAX_CHANGED_PATHS = 256
MAX_PATH_BYTES = 4096
MAX_DECISION_BYTES = 64 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
MAX_IDENTITY_BYTES = 128
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
_RECEIPT_TOKEN = object()
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


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


def _optional_identity(value, label):
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or _IDENTITY.fullmatch(value) is None
        or len(value.encode("utf-8")) > MAX_IDENTITY_BYTES
    ):
        raise TrustedPolicyEnforcementError(f"{label} is malformed")
    return value


def _optional_digest(value, label):
    if value is None:
        return None
    _sha256(value, label)
    return value


@dataclass(frozen=True)
class TrustedPolicyDecisionReceipt:
    """Immutable evidence that trusted policy observed one decision.

    Receipt = "trusted policy observed this", never authorization. Workers
    cannot mint a valid receipt by supplying arbitrary field values.
    """

    receipt_version: str
    policy_version: str
    registry_version: str
    registry_sha256: str
    decision_sha256: str
    outcome: str
    canonical_paths_sha256: str
    tcb_match_count: int
    tcb_matches_sha256: str
    reason_codes: tuple
    reason_codes_sha256: str
    candidate_digest: str
    worker_request_digest: str
    input_identity: str
    receipt_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _RECEIPT_TOKEN:
            raise TrustedPolicyEnforcementError(
                "trusted policy receipt requires trusted derived evidence"
            )
        if self.receipt_version != RECEIPT_VERSION:
            raise TrustedPolicyEnforcementError(
                "receipt version is unsupported"
            )
        if self.policy_version != ENFORCEMENT_POLICY_VERSION:
            raise TrustedPolicyEnforcementError(
                "receipt policy version is unsupported"
            )
        if self.registry_version != "mootos-tcb-registry-v1":
            raise TrustedPolicyEnforcementError(
                "receipt registry version is unsupported"
            )
        if self.outcome not in OUTCOMES:
            raise TrustedPolicyEnforcementError("receipt outcome unsupported")
        for value, label in (
            (self.registry_sha256, "registry digest"),
            (self.decision_sha256, "decision digest"),
            (self.canonical_paths_sha256, "canonical paths digest"),
            (self.tcb_matches_sha256, "TCB matches digest"),
            (self.reason_codes_sha256, "reason codes digest"),
            (self.receipt_sha256, "receipt digest"),
        ):
            _sha256(value, label)
        for value, label in (
            (self.candidate_digest, "candidate digest"),
            (self.worker_request_digest, "worker request digest"),
        ):
            _optional_digest(value, label)
        _optional_identity(self.input_identity, "input identity")
        if type(self.tcb_match_count) is not int or self.tcb_match_count < 0:
            raise TrustedPolicyEnforcementError(
                "TCB match count is malformed"
            )
        if type(self.reason_codes) is not tuple:
            raise TrustedPolicyEnforcementError("reason codes malformed")
        reasons = tuple(_reason_code(code) for code in self.reason_codes)
        if reasons != tuple(sorted(set(reasons))):
            raise TrustedPolicyEnforcementError(
                "reason codes are not canonical"
            )
        object.__setattr__(self, "reason_codes", reasons)
        if self.reason_codes_sha256 != _digest(_canonical(list(reasons))):
            raise TrustedPolicyEnforcementError(
                "reason codes digest mismatch"
            )
        if any(getattr(self, name) is not False for name in AUTHORITY_FLAGS):
            raise TrustedPolicyEnforcementError(
                "receipt cannot claim authority"
            )
        if self.receipt_sha256 != _digest(self._payload()):
            raise TrustedPolicyEnforcementError("receipt digest mismatch")
        if len(self.canonical_bytes()) > MAX_RECEIPT_BYTES:
            raise TrustedPolicyEnforcementError("receipt exceeds byte bound")

    def _body(self):
        return {
            "candidate_digest": self.candidate_digest,
            "canonical_paths_sha256": self.canonical_paths_sha256,
            "decision_sha256": self.decision_sha256,
            "github_authorized": False,
            "input_identity": self.input_identity,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "outcome": self.outcome,
            "policy_version": ENFORCEMENT_POLICY_VERSION,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "reason_codes": list(self.reason_codes),
            "reason_codes_sha256": self.reason_codes_sha256,
            "receipt_version": RECEIPT_VERSION,
            "registry_sha256": self.registry_sha256,
            "registry_version": self.registry_version,
            "tcb_match_count": self.tcb_match_count,
            "tcb_matches_sha256": self.tcb_matches_sha256,
            "worker_output_trusted": False,
            "worker_request_digest": self.worker_request_digest,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        body = self._body()
        body["receipt_sha256"] = self.receipt_sha256
        return _canonical(body)

    def to_dict(self):
        body = self._body()
        body["receipt_sha256"] = self.receipt_sha256
        return body


def create_trusted_policy_decision_receipt(
    decision,
    *,
    candidate_digest=None,
    worker_request_digest=None,
    input_identity=None,
):
    """Seal evidence that trusted policy observed ``decision``.

    Only a validated ``TrustedPolicyDecision`` may be wrapped. Optional
    identity digests bind the receipt to a candidate / request when known.
    """
    if not isinstance(decision, TrustedPolicyDecision):
        raise TrustedPolicyEnforcementError("decision is invalid")
    try:
        TrustedPolicyDecision(
            outcome=decision.outcome,
            policy_version=decision.policy_version,
            registry_version=decision.registry_version,
            registry_sha256=decision.registry_sha256,
            canonical_paths=decision.canonical_paths,
            canonical_paths_sha256=decision.canonical_paths_sha256,
            ordinary_paths=decision.ordinary_paths,
            tcb_matches=decision.tcb_matches,
            reason_codes=decision.reason_codes,
            input_path_count=decision.input_path_count,
            decision_sha256=decision.decision_sha256,
            publication_authorized=decision.publication_authorized,
            queue_transition_authorized=decision.queue_transition_authorized,
            github_authorized=decision.github_authorized,
            merge_authorized=decision.merge_authorized,
            main_advancement_authorized=decision.main_advancement_authorized,
            worker_output_trusted=decision.worker_output_trusted,
            _token=getattr(decision, "_token"),
        )
    except TrustedPolicyEnforcementError as error:
        raise TrustedPolicyEnforcementError(
            "decision failed authoritative validation"
        ) from error

    registry = create_mootos_tcb_registry_v1()
    if decision.registry_sha256 != registry.registry_sha256:
        raise TrustedPolicyEnforcementError(
            "decision registry digest mismatch"
        )

    candidate_digest = _optional_digest(candidate_digest, "candidate digest")
    worker_request_digest = _optional_digest(
        worker_request_digest, "worker request digest"
    )
    input_identity = _optional_identity(input_identity, "input identity")

    matches_body = [match.to_dict() for match in decision.tcb_matches]
    values = {
        "receipt_version": RECEIPT_VERSION,
        "policy_version": ENFORCEMENT_POLICY_VERSION,
        "registry_version": decision.registry_version,
        "registry_sha256": decision.registry_sha256,
        "decision_sha256": decision.decision_sha256,
        "outcome": decision.outcome,
        "canonical_paths_sha256": decision.canonical_paths_sha256,
        "tcb_match_count": len(decision.tcb_matches),
        "tcb_matches_sha256": _digest(_canonical(matches_body)),
        "reason_codes": decision.reason_codes,
        "reason_codes_sha256": _digest(
            _canonical(list(decision.reason_codes))
        ),
        "candidate_digest": candidate_digest,
        "worker_request_digest": worker_request_digest,
        "input_identity": input_identity,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(TrustedPolicyDecisionReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return TrustedPolicyDecisionReceipt(
        **values,
        receipt_sha256=_digest(provisional._payload()),
        _token=_RECEIPT_TOKEN,
    )


# --- CB-027D: narrow admission integration ---------------------------------

ADMISSION_VERSION = "cb-trusted-policy-admission-v1"

ADMISSION_ORDINARY = "admission_ordinary_continue"
ADMISSION_REVIEW = "admission_protected_review_required"
ADMISSION_FORBIDDEN = "admission_protected_forbidden"
ADMISSION_MALFORMED = "admission_malformed_stop"
ADMISSION_UNCERTAIN = "admission_policy_uncertain_stop"
ADMISSION_IDENTITY_MISMATCH = "admission_identity_mismatch_stop"
ADMISSION_STALE_RECEIPT = "admission_stale_receipt_stop"
ADMISSION_INVENTORY_INCOMPLETE = "admission_inventory_incomplete_stop"

ADMISSION_STATUSES = frozenset({
    ADMISSION_ORDINARY,
    ADMISSION_REVIEW,
    ADMISSION_FORBIDDEN,
    ADMISSION_MALFORMED,
    ADMISSION_UNCERTAIN,
    ADMISSION_IDENTITY_MISMATCH,
    ADMISSION_STALE_RECEIPT,
    ADMISSION_INVENTORY_INCOMPLETE,
})

_OUTCOME_TO_ADMISSION = {
    OUTCOME_ORDINARY: ADMISSION_ORDINARY,
    OUTCOME_REVIEW: ADMISSION_REVIEW,
    OUTCOME_FORBIDDEN: ADMISSION_FORBIDDEN,
    OUTCOME_MALFORMED: ADMISSION_MALFORMED,
    OUTCOME_UNCERTAIN: ADMISSION_UNCERTAIN,
}

_ADMISSION_TOKEN = object()


@dataclass(frozen=True)
class TrustedPolicyAdmission:
    """Narrow TCB admission result bound to candidate / request identities.

    Ordinary continuation is allowed only for admission_ordinary_continue.
    Review-required is an explicit non-authorized review state. All other
    statuses stop advancement. Zero authority; authorized is always false.
    """

    status: str
    decision_sha256: str
    receipt_sha256: str
    registry_sha256: str
    outcome: str
    candidate_digest: str
    worker_request_digest: str
    inventory_sha256: str
    changed_paths_sha256: str
    admission_sha256: str
    policy_version: str = ADMISSION_VERSION
    authorized: bool = False
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    worker_output_trusted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _ADMISSION_TOKEN:
            raise TrustedPolicyEnforcementError(
                "trusted policy admission requires trusted system construction"
            )
        if self.status not in ADMISSION_STATUSES:
            raise TrustedPolicyEnforcementError(
                "admission status is unsupported"
            )
        if self.policy_version != ADMISSION_VERSION:
            raise TrustedPolicyEnforcementError(
                "admission policy version is unsupported"
            )
        if self.outcome not in OUTCOMES:
            raise TrustedPolicyEnforcementError(
                "admission outcome is unsupported"
            )
        for value, label in (
            (self.decision_sha256, "decision digest"),
            (self.receipt_sha256, "receipt digest"),
            (self.registry_sha256, "registry digest"),
            (self.admission_sha256, "admission digest"),
            (self.changed_paths_sha256, "changed paths digest"),
        ):
            _sha256(value, label)
        for value, label in (
            (self.candidate_digest, "candidate digest"),
            (self.worker_request_digest, "worker request digest"),
            (self.inventory_sha256, "inventory digest"),
        ):
            _optional_digest(value, label)
        if self.authorized is not False:
            raise TrustedPolicyEnforcementError(
                "admission cannot self-authorize"
            )
        if any(getattr(self, name) is not False for name in AUTHORITY_FLAGS):
            raise TrustedPolicyEnforcementError(
                "admission cannot claim authority"
            )
        if (
            self.status == ADMISSION_ORDINARY
            and self.outcome != OUTCOME_ORDINARY
        ):
            raise TrustedPolicyEnforcementError(
                "ordinary admission outcome mismatch"
            )
        if (
            self.status == ADMISSION_REVIEW
            and self.outcome != OUTCOME_REVIEW
        ):
            raise TrustedPolicyEnforcementError(
                "review admission outcome mismatch"
            )
        if self.admission_sha256 != _digest(self._payload()):
            raise TrustedPolicyEnforcementError("admission digest mismatch")

    @property
    def allows_continuation(self):
        return self.status == ADMISSION_ORDINARY

    @property
    def requires_review(self):
        return self.status == ADMISSION_REVIEW

    def _body(self):
        return {
            "authorized": False,
            "candidate_digest": self.candidate_digest,
            "changed_paths_sha256": self.changed_paths_sha256,
            "decision_sha256": self.decision_sha256,
            "github_authorized": False,
            "inventory_sha256": self.inventory_sha256,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "outcome": self.outcome,
            "policy_version": ADMISSION_VERSION,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "receipt_sha256": self.receipt_sha256,
            "registry_sha256": self.registry_sha256,
            "status": self.status,
            "worker_output_trusted": False,
            "worker_request_digest": self.worker_request_digest,
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        body = self._body()
        body["admission_sha256"] = self.admission_sha256
        return _canonical(body)

    def to_dict(self):
        body = self._body()
        body["admission_sha256"] = self.admission_sha256
        return body


def _seal_admission(
    *,
    status,
    decision,
    receipt,
    candidate_digest,
    worker_request_digest,
    inventory_sha256,
    changed_paths_sha256,
    outcome=None,
):
    values = {
        "status": status,
        "decision_sha256": decision.decision_sha256,
        "receipt_sha256": receipt.receipt_sha256,
        "registry_sha256": decision.registry_sha256,
        "outcome": decision.outcome if outcome is None else outcome,
        "candidate_digest": candidate_digest,
        "worker_request_digest": worker_request_digest,
        "inventory_sha256": inventory_sha256,
        "changed_paths_sha256": changed_paths_sha256,
        "policy_version": ADMISSION_VERSION,
        "authorized": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(TrustedPolicyAdmission)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return TrustedPolicyAdmission(
        **values,
        admission_sha256=_digest(provisional._payload()),
        _token=_ADMISSION_TOKEN,
    )


def admit_changed_paths_against_tcb(
    authoritative_changed_paths,
    *,
    candidate_digest=None,
    worker_request_digest=None,
    inventory_sha256=None,
    worker_declared_paths=None,
    prior_receipt=None,
):
    """Admit one authoritative changed-path inventory against the TCB.

    ``authoritative_changed_paths`` must be the system-owned inventory.
    Worker-declared paths cannot override it. A prior receipt must bind the
    same candidate / request / path-set identities or admission stops.
    """
    candidate_digest = _optional_digest(candidate_digest, "candidate digest")
    worker_request_digest = _optional_digest(
        worker_request_digest, "worker request digest"
    )
    inventory_sha256 = _optional_digest(inventory_sha256, "inventory digest")

    if authoritative_changed_paths is None:
        decision = evaluate_changed_paths_against_tcb(())
        receipt = create_trusted_policy_decision_receipt(
            decision,
            candidate_digest=candidate_digest,
            worker_request_digest=worker_request_digest,
            input_identity="inventory_missing",
        )
        return _seal_admission(
            status=ADMISSION_INVENTORY_INCOMPLETE,
            decision=decision,
            receipt=receipt,
            candidate_digest=candidate_digest,
            worker_request_digest=worker_request_digest,
            inventory_sha256=inventory_sha256,
            changed_paths_sha256=_digest(_canonical([])),
            outcome=OUTCOME_MALFORMED,
        )

    decision = evaluate_changed_paths_against_tcb(authoritative_changed_paths)
    changed_paths_sha256 = decision.canonical_paths_sha256

    if worker_declared_paths is not None:
        declared = evaluate_changed_paths_against_tcb(worker_declared_paths)
        if (
            declared.canonical_paths_sha256 != decision.canonical_paths_sha256
            or declared.outcome != decision.outcome
        ):
            receipt = create_trusted_policy_decision_receipt(
                decision,
                candidate_digest=candidate_digest,
                worker_request_digest=worker_request_digest,
                input_identity="worker_path_disagreement",
            )
            return _seal_admission(
                status=ADMISSION_IDENTITY_MISMATCH,
                decision=decision,
                receipt=receipt,
                candidate_digest=candidate_digest,
                worker_request_digest=worker_request_digest,
                inventory_sha256=inventory_sha256,
                changed_paths_sha256=changed_paths_sha256,
                outcome=OUTCOME_MALFORMED,
            )

    receipt = create_trusted_policy_decision_receipt(
        decision,
        candidate_digest=candidate_digest,
        worker_request_digest=worker_request_digest,
        input_identity="authoritative_inventory",
    )

    if prior_receipt is not None:
        if not isinstance(prior_receipt, TrustedPolicyDecisionReceipt):
            raise TrustedPolicyEnforcementError("prior receipt is invalid")
        try:
            TrustedPolicyDecisionReceipt(
                receipt_version=prior_receipt.receipt_version,
                policy_version=prior_receipt.policy_version,
                registry_version=prior_receipt.registry_version,
                registry_sha256=prior_receipt.registry_sha256,
                decision_sha256=prior_receipt.decision_sha256,
                outcome=prior_receipt.outcome,
                canonical_paths_sha256=prior_receipt.canonical_paths_sha256,
                tcb_match_count=prior_receipt.tcb_match_count,
                tcb_matches_sha256=prior_receipt.tcb_matches_sha256,
                reason_codes=prior_receipt.reason_codes,
                reason_codes_sha256=prior_receipt.reason_codes_sha256,
                candidate_digest=prior_receipt.candidate_digest,
                worker_request_digest=prior_receipt.worker_request_digest,
                input_identity=prior_receipt.input_identity,
                receipt_sha256=prior_receipt.receipt_sha256,
                publication_authorized=prior_receipt.publication_authorized,
                queue_transition_authorized=(
                    prior_receipt.queue_transition_authorized
                ),
                github_authorized=prior_receipt.github_authorized,
                merge_authorized=prior_receipt.merge_authorized,
                main_advancement_authorized=(
                    prior_receipt.main_advancement_authorized
                ),
                worker_output_trusted=prior_receipt.worker_output_trusted,
                _token=getattr(prior_receipt, "_token"),
            )
        except TrustedPolicyEnforcementError as error:
            raise TrustedPolicyEnforcementError(
                "prior receipt failed authoritative validation"
            ) from error
        stale = False
        if prior_receipt.decision_sha256 != decision.decision_sha256:
            stale = True
        if prior_receipt.canonical_paths_sha256 != changed_paths_sha256:
            stale = True
        if prior_receipt.registry_sha256 != decision.registry_sha256:
            stale = True
        if (
            candidate_digest is not None
            and prior_receipt.candidate_digest is not None
            and prior_receipt.candidate_digest != candidate_digest
        ):
            stale = True
        if (
            worker_request_digest is not None
            and prior_receipt.worker_request_digest is not None
            and prior_receipt.worker_request_digest != worker_request_digest
        ):
            stale = True
        if stale:
            return _seal_admission(
                status=ADMISSION_STALE_RECEIPT,
                decision=decision,
                receipt=receipt,
                candidate_digest=candidate_digest,
                worker_request_digest=worker_request_digest,
                inventory_sha256=inventory_sha256,
                changed_paths_sha256=changed_paths_sha256,
            )

    return _seal_admission(
        status=_OUTCOME_TO_ADMISSION[decision.outcome],
        decision=decision,
        receipt=receipt,
        candidate_digest=candidate_digest,
        worker_request_digest=worker_request_digest,
        inventory_sha256=inventory_sha256,
        changed_paths_sha256=changed_paths_sha256,
    )


def tcb_failure_codes_for_admission(admission):
    """Map an admission status to verifier-core failure codes."""
    if not isinstance(admission, TrustedPolicyAdmission):
        raise TrustedPolicyEnforcementError("admission is invalid")
    mapping = {
        ADMISSION_ORDINARY: (),
        ADMISSION_REVIEW: ("tcb_protected_change_requires_review",),
        ADMISSION_FORBIDDEN: ("tcb_protected_change_forbidden",),
        ADMISSION_MALFORMED: ("tcb_malformed_change",),
        ADMISSION_UNCERTAIN: ("tcb_policy_uncertain",),
        ADMISSION_IDENTITY_MISMATCH: ("tcb_identity_mismatch",),
        ADMISSION_STALE_RECEIPT: ("tcb_stale_receipt",),
        ADMISSION_INVENTORY_INCOMPLETE: ("tcb_inventory_incomplete",),
    }
    return mapping[admission.status]
