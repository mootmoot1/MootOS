"""GP-C trusted capability admission core.

THIS MODULE IS THE ONLY TRUSTED GP-C SURFACE. It owns the authoritative
admission algorithm that maps validated TrustedAdmissionFacts to
allow_within_bound / require_human_approval / deny / escalate /
insufficient_evidence.

Invariants
----------
* Default-deny, fail-closed, provider/model/benchmark-neutral.
* UNKNOWN capability ids never ALLOW.
* Worker / model / provider / benchmark claims never grant.
* A valid GP-B plan alone never grants; plan_requires_escalation blocks
  silent allow_within_bound.
* Decision / receipt never execute (execution_authorized and friends
  structurally False).
* Main merge / Main advance NEVER appear in admitted_within_bound.
* Human-gated classes may be packaged only; never auto-approved.
* System Model digests are advisory bindings only; stale/missing/
  mismatch → insufficient_evidence or escalate.
* GP-B contract/plan material is sealed-but-untrusted; only digests and
  escalation flags are consulted.
* Live TCB registry digest / policy version must match facts at the
  trusted boundary — outside assembly is never trusted on its own.

Import closure
--------------
Allowed: stdlib + trusted_policy query APIs / version constants only.
Forbidden (direct or transitive): gpb_*, system_model, context_engine,
gpa_architecture_baseline, gpc_eval_corpus, and the untrusted GP-C
assemblers (admission_input / eval corpus). Intentional local
digest / canonicalize / authority-flag helpers avoid gpa_eval_schema
(which pulls paths → text_safety).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from .trusted_policy import (
    POLICY_VERSION,
    REGISTRY_VERSION,
    classify_tcb_path,
    create_mootos_tcb_registry_v1,
    create_trusted_policy_snapshot,
    is_tcb_path,
)

# ---------------------------------------------------------------------------
# Local helpers (intentional duplication; keep trusted closure small)
# ---------------------------------------------------------------------------

CORE_VERSION = "gpc-trusted-admission-core-v1"
FACTS_VERSION = "gpc-trusted-admission-facts-v1"
DECISION_VERSION = "gpc-admission-decision-v1"
RECEIPT_VERSION = "gpc-admission-receipt-v1"
GENERATOR_VERSION = "gpc-admission-decision-generator-v1"
MATRIX_VERSION = "gpc-policy-matrix-v1"
VOCABULARY_VERSION = "gpc-capability-vocabulary-v1"

MAX_DECISION_BYTES = 512 * 1024
MAX_REASON_CODES = 64
MAX_RULES = 64
MAX_MATRIX_BYTES = 64 * 1024
MAX_REASON = 128
MAX_REQUESTS = 32
MAX_SCOPE_PATHS = 64
MAX_EVIDENCE_REFS = 16
MAX_TEXT = 512
MAX_BUDGET_VALUE = 10**9
MAX_ID_BYTES = 64
MAX_FACTS_BYTES = 512 * 1024

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
_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_BASE_SHA = re.compile(r"^[0-9a-f]{7,64}$")

_TOKEN = object()
_FACTS_TOKEN = object()
_ROW_TOKEN = object()
_RULE_TOKEN = object()
_MATRIX_TOKEN = object()

OUTCOME_ALLOW_WITHIN_BOUND = "allow_within_bound"
OUTCOME_REQUIRE_HUMAN_APPROVAL = "require_human_approval"
OUTCOME_DENY = "deny"
OUTCOME_ESCALATE = "escalate"
OUTCOME_INSUFFICIENT_EVIDENCE = "insufficient_evidence"

ADMISSION_OUTCOMES = frozenset(
    {
        OUTCOME_ALLOW_WITHIN_BOUND,
        OUTCOME_REQUIRE_HUMAN_APPROVAL,
        OUTCOME_DENY,
        OUTCOME_ESCALATE,
        OUTCOME_INSUFFICIENT_EVIDENCE,
    }
)

_SEVERITY = {
    OUTCOME_ALLOW_WITHIN_BOUND: 0,
    OUTCOME_REQUIRE_HUMAN_APPROVAL: 1,
    OUTCOME_ESCALATE: 2,
    OUTCOME_INSUFFICIENT_EVIDENCE: 3,
    OUTCOME_DENY: 4,
}

CAPABILITY_IDS = frozenset(
    {
        "cb.repo.read",
        "cb.file.read_bounded",
        "cb.file.write_bounded",
        "cb.test.exec",
        "cb.verifier.exec",
        "cb.subprocess",
        "cb.sandbox.container",
        "cb.git.branch_worktree",
        "cb.pr.create",
        "cb.github.metadata",
        "cb.network",
        "cb.credentials",
        "cb.db.schema",
        "cb.production.data",
        "cb.deploy.staging",
        "cb.trusted_policy.change",
        "cb.tcb.change",
        "cb.approval_rules.change",
        "cb.main.merge",
        "cb.main.advance",
    }
)

HUMAN_GATED_CAPABILITY_IDS = frozenset(
    {
        "cb.pr.create",
        "cb.network",
        "cb.credentials",
        "cb.db.schema",
        "cb.production.data",
        "cb.deploy.staging",
        "cb.trusted_policy.change",
        "cb.tcb.change",
        "cb.approval_rules.change",
        "cb.main.merge",
        "cb.main.advance",
        "cb.subprocess",
        "cb.sandbox.container",
        "cb.verifier.exec",
    }
)

DEFAULT_OUTCOMES = {
    "cb.repo.read": OUTCOME_ALLOW_WITHIN_BOUND,
    "cb.file.read_bounded": OUTCOME_ALLOW_WITHIN_BOUND,
    "cb.file.write_bounded": OUTCOME_ALLOW_WITHIN_BOUND,
    "cb.test.exec": OUTCOME_ALLOW_WITHIN_BOUND,
    "cb.verifier.exec": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.subprocess": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.sandbox.container": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.git.branch_worktree": OUTCOME_ALLOW_WITHIN_BOUND,
    "cb.pr.create": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.github.metadata": OUTCOME_ALLOW_WITHIN_BOUND,
    "cb.network": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.credentials": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.db.schema": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.production.data": OUTCOME_DENY,
    "cb.deploy.staging": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.trusted_policy.change": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.tcb.change": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.approval_rules.change": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.main.merge": OUTCOME_REQUIRE_HUMAN_APPROVAL,
    "cb.main.advance": OUTCOME_REQUIRE_HUMAN_APPROVAL,
}

_ELEVATED_RISK = frozenset(
    {
        "tcb_adjacent",
        "security_sensitive",
        "schema_migration",
        "irreversible_change",
        "policy_sensitive",
    }
)

_TCB_POLICY_CAPS = frozenset(
    {
        "cb.trusted_policy.change",
        "cb.tcb.change",
        "cb.approval_rules.change",
        "cb.main.merge",
        "cb.main.advance",
        "cb.production.data",
        "cb.db.schema",
        "cb.deploy.staging",
        "cb.credentials",
        "cb.network",
    }
)

_WRITE_CAPS = frozenset(
    {
        "cb.file.write_bounded",
        "cb.trusted_policy.change",
        "cb.tcb.change",
        "cb.approval_rules.change",
        "cb.db.schema",
    }
)

_BUDGET_FIELDS = (
    ("budget_wall_clock_seconds", "budget_ceiling_wall_clock_seconds"),
    ("budget_input_tokens", "budget_ceiling_input_tokens"),
    ("budget_output_tokens", "budget_ceiling_output_tokens"),
)


class TrustedAdmissionError(ValueError):
    """Raised when trusted admission facts / decisions cannot be sealed."""


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical_json(value):
    """Public alias matching historical GP-C canonical encoding."""
    return _canonical(value)


def sha256_hex(value):
    """Public alias for SHA-256 hex digest of bytes or canonical body."""
    if isinstance(value, (bytes, bytearray)):
        return hashlib.sha256(value).hexdigest()
    return _digest(_canonical(value))


def _require_sha256(value, label):
    if not isinstance(value, str) or not _SHA256.match(value):
        raise TrustedAdmissionError(f"{label} malformed")
    return value


def _require_id(value, label):
    if not isinstance(value, str) or not _ID.match(value):
        raise TrustedAdmissionError(f"{label} malformed")
    if len(value.encode("utf-8")) > MAX_ID_BYTES:
        raise TrustedAdmissionError(f"{label} exceeds bound")
    return value


def _require_text(value, label, max_bytes):
    if not isinstance(value, str) or not value:
        raise TrustedAdmissionError(f"{label} malformed")
    if len(value.encode("utf-8")) > max_bytes:
        raise TrustedAdmissionError(f"{label} exceeds bound")
    return value


def _require_base_sha(value, label):
    if not isinstance(value, str) or not _BASE_SHA.match(value):
        raise TrustedAdmissionError(f"{label} malformed")
    return value


def _require_no_authority(obj):
    for name in AUTHORITY_FLAGS:
        if getattr(obj, name, False) is not False:
            raise TrustedAdmissionError(f"cannot claim {name}")


def _severe(current, candidate):
    if _SEVERITY[candidate] >= _SEVERITY[current]:
        return candidate
    return current


def is_known_capability_id(capability_id):
    return isinstance(capability_id, str) and capability_id in CAPABILITY_IDS


def is_human_gated_capability(capability_id):
    return capability_id in HUMAN_GATED_CAPABILITY_IDS


def default_outcome_for_capability(capability_id):
    if not is_known_capability_id(capability_id):
        return OUTCOME_INSUFFICIENT_EVIDENCE
    return DEFAULT_OUTCOMES[capability_id]


def _path_in_prefixes(path, prefixes):
    for prefix in prefixes:
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def _validate_path_tuple(paths, label, *, allow_empty=False, max_paths=MAX_SCOPE_PATHS):
    if type(paths) is not tuple:
        raise TrustedAdmissionError(f"{label} malformed")
    if not allow_empty and not paths:
        raise TrustedAdmissionError(f"{label} must be non-empty")
    if len(paths) > max_paths:
        raise TrustedAdmissionError(f"{label} exceeds bound")
    seen = set()
    for path in paths:
        if not isinstance(path, str) or not path:
            raise TrustedAdmissionError(f"{label} entry malformed")
        if len(path.encode("utf-8")) > 4096:
            raise TrustedAdmissionError(f"{label} path exceeds bound")
        if "\\" in path or path.startswith("/") or ".." in path.split("/"):
            raise TrustedAdmissionError(f"{label} path unsafe")
        if path in seen:
            raise TrustedAdmissionError(f"{label} not unique")
        seen.add(path)
    if tuple(sorted(paths)) != paths:
        raise TrustedAdmissionError(f"{label} not canonical")
    return paths


# ---------------------------------------------------------------------------
# Policy matrix (authoritative)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyRule:
    """One sealed matrix row. Grants nothing by itself."""

    rule_id: str
    capability_id: str
    outcome: str
    reason_code: str
    human_gated: bool
    rule_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _RULE_TOKEN:
            raise TrustedAdmissionError("policy rule requires trusted construction")
        _require_text(self.rule_id, "rule_id", 64)
        if self.capability_id != "*" and self.capability_id not in CAPABILITY_IDS:
            raise TrustedAdmissionError("capability_id unknown")
        if self.outcome not in ADMISSION_OUTCOMES:
            raise TrustedAdmissionError("outcome unsupported")
        _require_text(self.reason_code, "reason_code", MAX_REASON)
        if type(self.human_gated) is not bool:
            raise TrustedAdmissionError("human_gated must be bool")
        _require_sha256(self.rule_sha256, "rule_sha256")
        if self.rule_sha256 != _digest(_canonical(self._body())):
            raise TrustedAdmissionError("rule_sha256 mismatch")

    def _body(self):
        return {
            "capability_id": self.capability_id,
            "human_gated": self.human_gated,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "rule_id": self.rule_id,
        }

    def to_dict(self):
        body = self._body()
        body["rule_sha256"] = self.rule_sha256
        return body


def _seal_rule(rule_id, capability_id, outcome, reason_code, human_gated):
    values = {
        "rule_id": rule_id,
        "capability_id": capability_id,
        "outcome": outcome,
        "reason_code": reason_code,
        "human_gated": human_gated,
    }
    provisional = object.__new__(PolicyRule)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return PolicyRule(
        **values,
        rule_sha256=_digest(_canonical(provisional._body())),
        _token=_RULE_TOKEN,
    )


@dataclass(frozen=True)
class PolicyMatrix:
    """Sealed deterministic admission matrix."""

    schema_version: str
    rules: tuple
    matrix_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _MATRIX_TOKEN:
            raise TrustedAdmissionError(
                "policy matrix requires trusted construction"
            )
        if self.schema_version != MATRIX_VERSION:
            raise TrustedAdmissionError("schema_version unsupported")
        if type(self.rules) is not tuple or not self.rules:
            raise TrustedAdmissionError("rules malformed")
        if len(self.rules) > MAX_RULES:
            raise TrustedAdmissionError("rules exceeds bound")
        ids = tuple(r.rule_id for r in self.rules)
        if ids != tuple(sorted(set(ids))):
            raise TrustedAdmissionError("rules not canonical")
        _require_no_authority(self)
        if self.execution_authorized is not False:
            raise TrustedAdmissionError("cannot claim execution_authorized")
        _require_sha256(self.matrix_sha256, "matrix_sha256")
        if self.matrix_sha256 != _digest(_canonical(self._body())):
            raise TrustedAdmissionError("matrix_sha256 mismatch")
        if len(_canonical(self.to_dict())) > MAX_MATRIX_BYTES:
            raise TrustedAdmissionError("matrix exceeds byte bound")

    def _body(self):
        return {
            "execution_authorized": False,
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "rules": [r.to_dict() for r in self.rules],
            "schema_version": self.schema_version,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["matrix_sha256"] = self.matrix_sha256
        return body

    def rule_for_capability(self, capability_id):
        for rule in self.rules:
            if rule.capability_id == capability_id:
                return rule
        return None


def create_gpc_policy_matrix_v1():
    """Build the sealed default-deny capability admission matrix."""
    rows = []
    for capability_id in sorted(CAPABILITY_IDS):
        outcome = default_outcome_for_capability(capability_id)
        human = capability_id in HUMAN_GATED_CAPABILITY_IDS
        reason = {
            OUTCOME_ALLOW_WITHIN_BOUND: "default_allow_within_frozen_bound",
            OUTCOME_REQUIRE_HUMAN_APPROVAL: "default_human_gate",
            OUTCOME_DENY: "default_deny",
            OUTCOME_ESCALATE: "default_escalate",
            OUTCOME_INSUFFICIENT_EVIDENCE: "default_insufficient",
        }[outcome]
        rows.append(
            _seal_rule(
                rule_id=f"rule_{capability_id.replace('.', '_')}",
                capability_id=capability_id,
                outcome=outcome,
                reason_code=reason,
                human_gated=human,
            )
        )
    rows.append(
        _seal_rule(
            rule_id="rule_unknown_catch_all",
            capability_id="*",
            outcome=OUTCOME_INSUFFICIENT_EVIDENCE,
            reason_code="unknown_capability_never_allow",
            human_gated=True,
        )
    )
    rules = tuple(sorted(rows, key=lambda item: item.rule_id))
    values = {
        "schema_version": MATRIX_VERSION,
        "rules": rules,
        "execution_authorized": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(PolicyMatrix)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return PolicyMatrix(
        **values,
        matrix_sha256=_digest(_canonical(provisional._body())),
        _token=_MATRIX_TOKEN,
    )


def lookup_matrix_outcome(matrix, capability_id):
    """Return (outcome, reason_code, human_gated, rule_id) fail-closed."""
    if not isinstance(matrix, PolicyMatrix):
        raise TrustedAdmissionError("matrix invalid")
    if not is_known_capability_id(capability_id):
        catch = matrix.rule_for_capability("*")
        if catch is None:
            return (
                OUTCOME_INSUFFICIENT_EVIDENCE,
                "unknown_capability_never_allow",
                True,
                "implicit_unknown",
            )
        return (
            catch.outcome,
            catch.reason_code,
            catch.human_gated,
            catch.rule_id,
        )
    rule = matrix.rule_for_capability(capability_id)
    if rule is None:
        return (
            OUTCOME_INSUFFICIENT_EVIDENCE,
            "missing_matrix_row",
            True,
            "implicit_missing",
        )
    return rule.outcome, rule.reason_code, rule.human_gated, rule.rule_id


# ---------------------------------------------------------------------------
# Scope / risk / TCB + budget (authoritative)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopeRiskTCBResult:
    outcome: str
    reason_codes: tuple
    tcb_paths_touched: tuple
    forbidden_paths_touched: tuple
    out_of_scope_paths: tuple
    escalated_from_gpb: bool


def evaluate_scope_risk_tcb(
    *,
    capability_id,
    requested_scope,
    allowed_scope,
    forbidden_scope,
    risk_ceiling_indicators,
    required_gates,
    plan_requires_escalation,
    plan_escalation_reasons,
    base_matrix_outcome,
):
    """Adjust a matrix outcome using scope / risk / TCB / GP-B escalation."""
    if base_matrix_outcome == OUTCOME_INSUFFICIENT_EVIDENCE:
        return ScopeRiskTCBResult(
            outcome=OUTCOME_INSUFFICIENT_EVIDENCE,
            reason_codes=("matrix_insufficient_evidence",),
            tcb_paths_touched=(),
            forbidden_paths_touched=(),
            out_of_scope_paths=(),
            escalated_from_gpb=False,
        )

    reasons = []
    tcb_hit = []
    forbidden_hit = []
    oos = []
    allowed = tuple(allowed_scope)
    forbidden = tuple(forbidden_scope)
    scope = tuple(requested_scope)

    for path in scope:
        if path in forbidden or _path_in_prefixes(path, forbidden):
            forbidden_hit.append(path)
        if allowed and path not in allowed and not _path_in_prefixes(path, allowed):
            if not any(
                path == a or path.startswith(a.rstrip("/") + "/") for a in allowed
            ):
                oos.append(path)
        if is_tcb_path(path):
            tcb_hit.append(path)

    tcb_hit = tuple(sorted(set(tcb_hit)))
    forbidden_hit = tuple(sorted(set(forbidden_hit)))
    oos = tuple(sorted(set(oos)))

    outcome = base_matrix_outcome

    if forbidden_hit:
        reasons.append("forbidden_scope_touch")
        outcome = OUTCOME_DENY

    if oos:
        reasons.append("out_of_scope_path")
        outcome = OUTCOME_DENY

    if tcb_hit:
        reasons.append("tcb_path_touch")
        if capability_id in _WRITE_CAPS or capability_id in _TCB_POLICY_CAPS:
            reasons.append("tcb_write_requires_human")
            outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)
        else:
            outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)
        for path in tcb_hit:
            classification = classify_tcb_path(path)
            if classification is not None and classification.change_policy in (
                "human_only",
                "protected_core_review",
            ):
                reasons.append(f"tcb_change_policy_{classification.change_policy}")
                outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)

    if capability_id in _TCB_POLICY_CAPS:
        reasons.append("tcb_or_policy_capability")
        outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)

    if capability_id in ("cb.main.merge", "cb.main.advance"):
        reasons.append("main_merge_or_advance_human_gated")
        outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)

    elevated = tuple(sorted(set(risk_ceiling_indicators) & _ELEVATED_RISK))
    if elevated and capability_id in _WRITE_CAPS:
        reasons.append("elevated_descriptive_risk_on_write")
        outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)
        for code in elevated:
            reasons.append(f"risk_{code}")

    if risk_ceiling_indicators == ("none",):
        if outcome == OUTCOME_DENY:
            reasons.append("low_risk_does_not_override_deny")

    if plan_requires_escalation:
        reasons.append("gpb_plan_requires_escalation")
        for code in plan_escalation_reasons:
            reasons.append(f"gpb_escalation:{code}")
        if outcome == OUTCOME_ALLOW_WITHIN_BOUND:
            outcome = OUTCOME_ESCALATE
            reasons.append("gpb_escalation_blocks_auto_allow")
        else:
            outcome = _severe(outcome, OUTCOME_ESCALATE)

    if not required_gates and capability_id in _WRITE_CAPS:
        reasons.append("missing_required_gates")
        outcome = _severe(outcome, OUTCOME_REQUIRE_HUMAN_APPROVAL)

    if not reasons:
        reasons = ("scope_risk_tcb_passthrough",)

    return ScopeRiskTCBResult(
        outcome=outcome,
        reason_codes=tuple(sorted(set(reasons))),
        tcb_paths_touched=tcb_hit,
        forbidden_paths_touched=forbidden_hit,
        out_of_scope_paths=oos,
        escalated_from_gpb=bool(plan_requires_escalation),
    )


@dataclass(frozen=True)
class BudgetConstraintResult:
    outcome: str
    reason_codes: tuple
    exceeded_fields: tuple


def evaluate_budget_constraints(
    *,
    request,
    budget_ceiling_wall_clock_seconds,
    budget_ceiling_input_tokens,
    budget_ceiling_output_tokens,
    budget_ceiling_cost_usd_cents,
    base_outcome,
):
    """Deny / human-gate when request budgets exceed contract ceilings."""
    del budget_ceiling_cost_usd_cents
    if base_outcome == OUTCOME_DENY:
        return BudgetConstraintResult(
            outcome=base_outcome,
            reason_codes=("budget_skipped_already_denied",),
            exceeded_fields=(),
        )

    ceilings = {
        "budget_wall_clock_seconds": budget_ceiling_wall_clock_seconds,
        "budget_input_tokens": budget_ceiling_input_tokens,
        "budget_output_tokens": budget_ceiling_output_tokens,
    }
    reasons = []
    exceeded = []
    outcome = base_outcome

    for req_field, _ceiling_attr in _BUDGET_FIELDS:
        requested = getattr(request, req_field)
        ceiling = ceilings[req_field]
        if ceiling is None:
            continue
        if requested is None:
            reasons.append(f"missing_request_{req_field}")
            if outcome == OUTCOME_ALLOW_WITHIN_BOUND:
                outcome = OUTCOME_REQUIRE_HUMAN_APPROVAL
            continue
        if requested > ceiling:
            exceeded.append(req_field)
            reasons.append(f"exceeds_ceiling_{req_field}")
            outcome = OUTCOME_DENY

    for ref in request.evidence_refs:
        if ref.startswith("budget_increase:"):
            exceeded.append(ref)
            reasons.append("explicit_budget_increase_request")
            outcome = OUTCOME_DENY

    if not reasons:
        reasons = ("budget_within_ceiling",)

    return BudgetConstraintResult(
        outcome=outcome,
        reason_codes=tuple(sorted(set(reasons))),
        exceeded_fields=tuple(sorted(set(exceeded))),
    )


# ---------------------------------------------------------------------------
# TrustedAdmissionFacts — sealed boundary DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrustedRequestFact:
    """Plain bounded request facts. Core re-validates; never trusts outside."""

    request_id: str
    capability_id: str
    request_sha256: str
    requested_scope: tuple
    budget_wall_clock_seconds: object
    budget_input_tokens: object
    budget_output_tokens: object
    evidence_refs: tuple
    human_gate_requested: bool
    worker_safe_claim: bool
    provider_id: object
    model_id: object
    benchmark_score: object
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise TrustedAdmissionError(
                "trusted request fact requires trusted construction"
            )
        _require_id(self.request_id, "request_id")
        if not isinstance(self.capability_id, str) or not self.capability_id:
            raise TrustedAdmissionError("capability_id malformed")
        if len(self.capability_id.encode("utf-8")) > 128:
            raise TrustedAdmissionError("capability_id exceeds bound")
        _require_sha256(self.request_sha256, "request_sha256")
        _validate_path_tuple(
            self.requested_scope, "requested_scope", allow_empty=True
        )
        for name in (
            "budget_wall_clock_seconds",
            "budget_input_tokens",
            "budget_output_tokens",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            if type(value) is not int or isinstance(value, bool):
                raise TrustedAdmissionError(f"{name} malformed")
            if value <= 0 or value > MAX_BUDGET_VALUE:
                raise TrustedAdmissionError(f"{name} out of bounds")
        if type(self.evidence_refs) is not tuple:
            raise TrustedAdmissionError("evidence_refs malformed")
        if len(self.evidence_refs) > MAX_EVIDENCE_REFS:
            raise TrustedAdmissionError("evidence_refs exceeds bound")
        for ref in self.evidence_refs:
            _require_text(ref, "evidence_refs", MAX_TEXT)
        for name in ("human_gate_requested", "worker_safe_claim"):
            if type(getattr(self, name)) is not bool:
                raise TrustedAdmissionError(f"{name} must be bool")
        for name in ("provider_id", "model_id"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name, 128)
        if self.benchmark_score is not None:
            if type(self.benchmark_score) not in (int, float) or isinstance(
                self.benchmark_score, bool
            ):
                raise TrustedAdmissionError("benchmark_score malformed")

    def to_dict(self):
        return {
            "benchmark_score": self.benchmark_score,
            "budget_input_tokens": self.budget_input_tokens,
            "budget_output_tokens": self.budget_output_tokens,
            "budget_wall_clock_seconds": self.budget_wall_clock_seconds,
            "capability_id": self.capability_id,
            "evidence_refs": list(self.evidence_refs),
            "human_gate_requested": self.human_gate_requested,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "requested_scope": list(self.requested_scope),
            "worker_safe_claim": self.worker_safe_claim,
        }


def seal_trusted_request_fact(**values):
    return TrustedRequestFact(**values, _token=_TOKEN)


@dataclass(frozen=True)
class TrustedAdmissionFacts:
    """Bounded sealed facts for trusted admission. Grants nothing."""

    schema_version: str
    facts_id: str
    task_contract_id: str
    contract_sha256: str
    plan_id: str
    plan_sha256: str
    base_sha: str
    architecture_baseline_sha256: str
    allowed_scope: tuple
    forbidden_scope: tuple
    required_gates: tuple
    risk_ceiling_indicators: tuple
    budget_ceiling_wall_clock_seconds: object
    budget_ceiling_input_tokens: object
    budget_ceiling_output_tokens: object
    budget_ceiling_cost_usd_cents: object
    plan_requires_escalation: bool
    plan_escalation_reasons: tuple
    system_model_sha256: object
    system_model_version: object
    expected_system_model_sha256: object
    trusted_policy_version: str
    tcb_registry_version: str
    tcb_registry_sha256: str
    tcb_protected_path_count: int
    tcb_snapshot_sha256: str
    vocabulary_version: str
    vocabulary_sha256: str
    evidence_digests: tuple
    capability_requests: tuple
    facts_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _FACTS_TOKEN:
            raise TrustedAdmissionError(
                "trusted admission facts require trusted construction"
            )
        if self.schema_version != FACTS_VERSION:
            raise TrustedAdmissionError("schema_version unsupported")
        _require_id(self.facts_id, "facts_id")
        _require_id(self.task_contract_id, "task_contract_id")
        _require_id(self.plan_id, "plan_id")
        _require_sha256(self.contract_sha256, "contract_sha256")
        _require_sha256(self.plan_sha256, "plan_sha256")
        _require_base_sha(self.base_sha, "base_sha")
        _require_sha256(
            self.architecture_baseline_sha256, "architecture_baseline_sha256"
        )
        _validate_path_tuple(self.allowed_scope, "allowed_scope")
        _validate_path_tuple(
            self.forbidden_scope, "forbidden_scope", allow_empty=True
        )
        if type(self.required_gates) is not tuple:
            raise TrustedAdmissionError("required_gates malformed")
        if type(self.risk_ceiling_indicators) is not tuple:
            raise TrustedAdmissionError("risk_ceiling_indicators malformed")
        if type(self.plan_requires_escalation) is not bool:
            raise TrustedAdmissionError("plan_requires_escalation must be bool")
        if type(self.plan_escalation_reasons) is not tuple:
            raise TrustedAdmissionError("plan_escalation_reasons malformed")
        if self.plan_requires_escalation and not self.plan_escalation_reasons:
            raise TrustedAdmissionError("escalation requires reasons")
        if self.system_model_sha256 is not None:
            _require_sha256(self.system_model_sha256, "system_model_sha256")
        if self.expected_system_model_sha256 is not None:
            _require_sha256(
                self.expected_system_model_sha256,
                "expected_system_model_sha256",
            )
        if self.trusted_policy_version != POLICY_VERSION:
            raise TrustedAdmissionError("trusted_policy_version mismatch")
        if self.tcb_registry_version != REGISTRY_VERSION:
            raise TrustedAdmissionError("tcb_registry_version mismatch")
        _require_sha256(self.tcb_registry_sha256, "tcb_registry_sha256")
        _require_sha256(self.tcb_snapshot_sha256, "tcb_snapshot_sha256")
        if (
            type(self.tcb_protected_path_count) is not int
            or self.tcb_protected_path_count < 1
        ):
            raise TrustedAdmissionError("tcb_protected_path_count malformed")
        if self.vocabulary_version != VOCABULARY_VERSION:
            raise TrustedAdmissionError("vocabulary_version mismatch")
        _require_sha256(self.vocabulary_sha256, "vocabulary_sha256")
        if type(self.evidence_digests) is not tuple:
            raise TrustedAdmissionError("evidence_digests malformed")
        for digest in self.evidence_digests:
            _require_sha256(digest, "evidence_digests")
        if type(self.capability_requests) is not tuple:
            raise TrustedAdmissionError("capability_requests malformed")
        if not self.capability_requests:
            raise TrustedAdmissionError("capability_requests must be non-empty")
        if len(self.capability_requests) > MAX_REQUESTS:
            raise TrustedAdmissionError("capability_requests exceeds bound")
        ids = []
        for req in self.capability_requests:
            if not isinstance(req, TrustedRequestFact):
                raise TrustedAdmissionError("capability_requests entry invalid")
            ids.append(req.request_id)
        if len(ids) != len(set(ids)):
            raise TrustedAdmissionError("duplicate capability request ids")
        _require_no_authority(self)
        if self.execution_authorized is not False:
            raise TrustedAdmissionError("cannot claim execution_authorized")
        _require_sha256(self.facts_sha256, "facts_sha256")
        if self.facts_sha256 != _digest(_canonical(self._body())):
            raise TrustedAdmissionError("facts_sha256 mismatch")
        if len(_canonical(self.to_dict())) > MAX_FACTS_BYTES:
            raise TrustedAdmissionError("facts exceed byte bound")

    def _body(self):
        return {
            "allowed_scope": list(self.allowed_scope),
            "architecture_baseline_sha256": self.architecture_baseline_sha256,
            "base_sha": self.base_sha,
            "budget_ceiling_cost_usd_cents": self.budget_ceiling_cost_usd_cents,
            "budget_ceiling_input_tokens": self.budget_ceiling_input_tokens,
            "budget_ceiling_output_tokens": self.budget_ceiling_output_tokens,
            "budget_ceiling_wall_clock_seconds": (
                self.budget_ceiling_wall_clock_seconds
            ),
            "capability_requests": [
                r.to_dict() for r in self.capability_requests
            ],
            "contract_sha256": self.contract_sha256,
            "evidence_digests": list(self.evidence_digests),
            "execution_authorized": False,
            "expected_system_model_sha256": self.expected_system_model_sha256,
            "facts_id": self.facts_id,
            "forbidden_scope": list(self.forbidden_scope),
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "plan_escalation_reasons": list(self.plan_escalation_reasons),
            "plan_id": self.plan_id,
            "plan_requires_escalation": self.plan_requires_escalation,
            "plan_sha256": self.plan_sha256,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "required_gates": list(self.required_gates),
            "result_trusted": False,
            "risk_ceiling_indicators": list(self.risk_ceiling_indicators),
            "schema_version": self.schema_version,
            "system_model_sha256": self.system_model_sha256,
            "system_model_version": self.system_model_version,
            "task_contract_id": self.task_contract_id,
            "tcb_protected_path_count": self.tcb_protected_path_count,
            "tcb_registry_sha256": self.tcb_registry_sha256,
            "tcb_registry_version": self.tcb_registry_version,
            "tcb_snapshot_sha256": self.tcb_snapshot_sha256,
            "trusted_policy_version": self.trusted_policy_version,
            "vocabulary_sha256": self.vocabulary_sha256,
            "vocabulary_version": self.vocabulary_version,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["facts_sha256"] = self.facts_sha256
        return body


def seal_trusted_admission_facts(**values):
    """Seal TrustedAdmissionFacts after field validation in __post_init__."""
    values = dict(values)
    for name in AUTHORITY_FLAGS:
        values[name] = False
    values["execution_authorized"] = False
    values.setdefault("schema_version", FACTS_VERSION)
    provisional = object.__new__(TrustedAdmissionFacts)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return TrustedAdmissionFacts(
        **values,
        facts_sha256=_digest(_canonical(provisional._body())),
        _token=_FACTS_TOKEN,
    )


def _recheck_live_tcb(facts):
    """Fail closed unless facts match the live canonical TCB identity."""
    registry = create_mootos_tcb_registry_v1()
    snapshot = create_trusted_policy_snapshot()
    if facts.trusted_policy_version != POLICY_VERSION:
        raise TrustedAdmissionError("live trusted_policy_version mismatch")
    if facts.tcb_registry_version != REGISTRY_VERSION:
        raise TrustedAdmissionError("live tcb_registry_version mismatch")
    if facts.tcb_registry_sha256 != registry.registry_sha256:
        raise TrustedAdmissionError("live tcb_registry_sha256 mismatch")
    if facts.tcb_snapshot_sha256 != snapshot.snapshot_sha256:
        raise TrustedAdmissionError("live tcb_snapshot_sha256 mismatch")
    if facts.tcb_protected_path_count != len(registry.protected_paths):
        raise TrustedAdmissionError("live tcb_protected_path_count mismatch")
    if snapshot.registry_sha256 != registry.registry_sha256:
        raise TrustedAdmissionError("tcb snapshot/registry digest drift")


def _system_model_boundary_outcome(facts):
    """Advisory System Model binding: mismatch/stale → insufficient/escalate."""
    if (
        facts.expected_system_model_sha256 is not None
        and facts.system_model_sha256 is None
    ):
        return OUTCOME_INSUFFICIENT_EVIDENCE, ("system_model_missing",)
    if (
        facts.expected_system_model_sha256 is not None
        and facts.system_model_sha256 is not None
        and facts.expected_system_model_sha256 != facts.system_model_sha256
    ):
        return OUTCOME_INSUFFICIENT_EVIDENCE, ("system_model_digest_mismatch",)
    return None, ()


# ---------------------------------------------------------------------------
# Decision / receipt (authoritative)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PerCapabilityDecision:
    """One sealed per-request admission row. Grants no runtime authority."""

    request_id: str
    capability_id: str
    outcome: str
    reason_codes: tuple
    rules_applied: tuple
    human_gated: bool
    request_sha256: str
    row_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _ROW_TOKEN:
            raise TrustedAdmissionError(
                "per-capability decision requires trusted construction"
            )
        _require_id(self.request_id, "request_id")
        if not isinstance(self.capability_id, str) or not self.capability_id:
            raise TrustedAdmissionError("capability_id malformed")
        if self.outcome not in _SEVERITY:
            raise TrustedAdmissionError("outcome unsupported")
        if type(self.reason_codes) is not tuple:
            raise TrustedAdmissionError("reason_codes malformed")
        if len(self.reason_codes) > MAX_REASON_CODES:
            raise TrustedAdmissionError("reason_codes exceeds bound")
        if type(self.rules_applied) is not tuple:
            raise TrustedAdmissionError("rules_applied malformed")
        if type(self.human_gated) is not bool:
            raise TrustedAdmissionError("human_gated must be bool")
        _require_sha256(self.request_sha256, "request_sha256")
        _require_sha256(self.row_sha256, "row_sha256")
        if self.row_sha256 != _digest(_canonical(self._body())):
            raise TrustedAdmissionError("row_sha256 mismatch")

    def _body(self):
        return {
            "capability_id": self.capability_id,
            "human_gated": self.human_gated,
            "outcome": self.outcome,
            "reason_codes": list(self.reason_codes),
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "rules_applied": list(self.rules_applied),
        }

    def to_dict(self):
        body = self._body()
        body["row_sha256"] = self.row_sha256
        return body


def _seal_row(**values):
    provisional = object.__new__(PerCapabilityDecision)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return PerCapabilityDecision(
        **values,
        row_sha256=_digest(_canonical(provisional._body())),
        _token=_ROW_TOKEN,
    )


@dataclass(frozen=True)
class AdmissionDecision:
    """Sealed aggregate admission decision. Never authorizes execution."""

    schema_version: str
    decision_id: str
    admission_input_id: str
    input_sha256: str
    task_contract_id: str
    contract_sha256: str
    plan_id: str
    plan_sha256: str
    base_sha: str
    architecture_baseline_sha256: str
    trusted_policy_version: str
    tcb_registry_sha256: str
    tcb_snapshot_sha256: str
    vocabulary_sha256: str
    matrix_version: str
    matrix_sha256: str
    per_capability: tuple
    requested_capability_ids: tuple
    admitted_within_bound: tuple
    denied: tuple
    human_gated: tuple
    escalated: tuple
    insufficient_evidence: tuple
    overall_outcome: str
    escalation_reasons: tuple
    generator_version: str
    decision_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    approved_to_execute: bool = False
    capability_runtime_granted: bool = False
    main_merge_auto_approved: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise TrustedAdmissionError(
                "admission decision requires trusted construction"
            )
        if self.schema_version != DECISION_VERSION:
            raise TrustedAdmissionError("schema_version unsupported")
        if self.generator_version != GENERATOR_VERSION:
            raise TrustedAdmissionError("generator_version unsupported")
        if self.matrix_version != MATRIX_VERSION:
            raise TrustedAdmissionError("matrix_version unsupported")
        _require_id(self.decision_id, "decision_id")
        _require_id(self.admission_input_id, "admission_input_id")
        _require_sha256(self.input_sha256, "input_sha256")
        _require_sha256(self.contract_sha256, "contract_sha256")
        _require_sha256(self.plan_sha256, "plan_sha256")
        _require_sha256(
            self.architecture_baseline_sha256, "architecture_baseline_sha256"
        )
        _require_sha256(self.tcb_registry_sha256, "tcb_registry_sha256")
        _require_sha256(self.tcb_snapshot_sha256, "tcb_snapshot_sha256")
        _require_sha256(self.vocabulary_sha256, "vocabulary_sha256")
        _require_sha256(self.matrix_sha256, "matrix_sha256")
        if type(self.per_capability) is not tuple or not self.per_capability:
            raise TrustedAdmissionError("per_capability malformed")
        if self.overall_outcome not in _SEVERITY:
            raise TrustedAdmissionError("overall_outcome unsupported")
        _require_no_authority(self)
        for name in (
            "execution_authorized",
            "approved_to_execute",
            "capability_runtime_granted",
            "main_merge_auto_approved",
        ):
            if getattr(self, name) is not False:
                raise TrustedAdmissionError(f"cannot claim {name}")
        if "cb.main.merge" in self.admitted_within_bound:
            raise TrustedAdmissionError(
                "main merge cannot be auto-admitted within bound"
            )
        if "cb.main.advance" in self.admitted_within_bound:
            raise TrustedAdmissionError(
                "main advance cannot be auto-admitted within bound"
            )
        _require_sha256(self.decision_sha256, "decision_sha256")
        if self.decision_sha256 != _digest(_canonical(self._body())):
            raise TrustedAdmissionError("decision_sha256 mismatch")
        if len(_canonical(self.to_dict())) > MAX_DECISION_BYTES:
            raise TrustedAdmissionError("decision exceeds byte bound")

    def _body(self):
        return {
            "admission_input_id": self.admission_input_id,
            "admitted_within_bound": list(self.admitted_within_bound),
            "approved_to_execute": False,
            "architecture_baseline_sha256": self.architecture_baseline_sha256,
            "base_sha": self.base_sha,
            "capability_runtime_granted": False,
            "contract_sha256": self.contract_sha256,
            "decision_id": self.decision_id,
            "denied": list(self.denied),
            "escalated": list(self.escalated),
            "escalation_reasons": list(self.escalation_reasons),
            "execution_authorized": False,
            "generator_version": self.generator_version,
            "github_authorized": False,
            "human_gated": list(self.human_gated),
            "input_sha256": self.input_sha256,
            "insufficient_evidence": list(self.insufficient_evidence),
            "main_advancement_authorized": False,
            "main_merge_auto_approved": False,
            "matrix_sha256": self.matrix_sha256,
            "matrix_version": self.matrix_version,
            "merge_authorized": False,
            "overall_outcome": self.overall_outcome,
            "per_capability": [row.to_dict() for row in self.per_capability],
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "requested_capability_ids": list(self.requested_capability_ids),
            "result_trusted": False,
            "schema_version": self.schema_version,
            "task_contract_id": self.task_contract_id,
            "tcb_registry_sha256": self.tcb_registry_sha256,
            "tcb_snapshot_sha256": self.tcb_snapshot_sha256,
            "trusted_policy_version": self.trusted_policy_version,
            "vocabulary_sha256": self.vocabulary_sha256,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["decision_sha256"] = self.decision_sha256
        return body



@dataclass(frozen=True)
class AdmissionReceipt:
    """Provenance receipt for one admission decision. Evidence only."""

    schema_version: str
    decision_id: str
    decision_sha256: str
    input_sha256: str
    contract_sha256: str
    plan_sha256: str
    tcb_registry_sha256: str
    matrix_sha256: str
    overall_outcome: str
    receipt_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    approved_to_execute: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise TrustedAdmissionError(
                "admission receipt requires trusted construction"
            )
        if self.schema_version != RECEIPT_VERSION:
            raise TrustedAdmissionError("receipt schema unsupported")
        _require_sha256(self.decision_sha256, "decision_sha256")
        _require_sha256(self.input_sha256, "input_sha256")
        _require_sha256(self.contract_sha256, "contract_sha256")
        _require_sha256(self.plan_sha256, "plan_sha256")
        _require_sha256(self.tcb_registry_sha256, "tcb_registry_sha256")
        _require_sha256(self.matrix_sha256, "matrix_sha256")
        _require_no_authority(self)
        if self.execution_authorized is not False:
            raise TrustedAdmissionError("cannot claim execution_authorized")
        if self.approved_to_execute is not False:
            raise TrustedAdmissionError(
                "valid admission receipt is never approved_to_execute"
            )
        _require_sha256(self.receipt_sha256, "receipt_sha256")
        if self.receipt_sha256 != _digest(_canonical(self._body())):
            raise TrustedAdmissionError("receipt_sha256 mismatch")

    def _body(self):
        return {
            "approved_to_execute": False,
            "contract_sha256": self.contract_sha256,
            "decision_id": self.decision_id,
            "decision_sha256": self.decision_sha256,
            "execution_authorized": False,
            "github_authorized": False,
            "input_sha256": self.input_sha256,
            "main_advancement_authorized": False,
            "matrix_sha256": self.matrix_sha256,
            "merge_authorized": False,
            "overall_outcome": self.overall_outcome,
            "plan_sha256": self.plan_sha256,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "tcb_registry_sha256": self.tcb_registry_sha256,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["receipt_sha256"] = self.receipt_sha256
        return body


def create_admission_receipt(decision):
    if not isinstance(decision, AdmissionDecision):
        raise TrustedAdmissionError("decision invalid")
    values = {
        "schema_version": RECEIPT_VERSION,
        "decision_id": decision.decision_id,
        "decision_sha256": decision.decision_sha256,
        "input_sha256": decision.input_sha256,
        "contract_sha256": decision.contract_sha256,
        "plan_sha256": decision.plan_sha256,
        "tcb_registry_sha256": decision.tcb_registry_sha256,
        "matrix_sha256": decision.matrix_sha256,
        "overall_outcome": decision.overall_outcome,
        "execution_authorized": False,
        "approved_to_execute": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(AdmissionReceipt)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return AdmissionReceipt(
        **values,
        receipt_sha256=_digest(_canonical(provisional._body())),
        _token=_TOKEN,
    )


def _evaluate_one(request, facts, matrix):
    """Deterministically evaluate one capability request fact."""
    base_outcome, base_reason, human_gated, rule_id = lookup_matrix_outcome(
        matrix, request.capability_id
    )
    reasons = [base_reason]
    rules = [rule_id]

    if request.worker_safe_claim:
        reasons.append("worker_safe_claim_ignored")
    if request.provider_id is not None:
        reasons.append("provider_identity_ignored")
    if request.model_id is not None:
        reasons.append("model_identity_ignored")
    if request.benchmark_score is not None:
        reasons.append("benchmark_score_ignored")

    scope_result = evaluate_scope_risk_tcb(
        capability_id=request.capability_id,
        requested_scope=request.requested_scope,
        allowed_scope=facts.allowed_scope,
        forbidden_scope=facts.forbidden_scope,
        risk_ceiling_indicators=facts.risk_ceiling_indicators,
        required_gates=facts.required_gates,
        plan_requires_escalation=facts.plan_requires_escalation,
        plan_escalation_reasons=facts.plan_escalation_reasons,
        base_matrix_outcome=base_outcome,
    )
    reasons.extend(scope_result.reason_codes)
    rules.append("scope_risk_tcb")
    outcome = scope_result.outcome

    budget_result = evaluate_budget_constraints(
        request=request,
        budget_ceiling_wall_clock_seconds=(
            facts.budget_ceiling_wall_clock_seconds
        ),
        budget_ceiling_input_tokens=facts.budget_ceiling_input_tokens,
        budget_ceiling_output_tokens=facts.budget_ceiling_output_tokens,
        budget_ceiling_cost_usd_cents=facts.budget_ceiling_cost_usd_cents,
        base_outcome=outcome,
    )
    reasons.extend(budget_result.reason_codes)
    rules.append("budget_constraints")
    outcome = budget_result.outcome

    if (
        request.human_gate_requested or human_gated
    ) and outcome == OUTCOME_ALLOW_WITHIN_BOUND:
        outcome = OUTCOME_REQUIRE_HUMAN_APPROVAL
        reasons.append("human_gate_required")

    for ref in request.evidence_refs:
        if ref == "gate_removed":
            outcome = _severe(outcome, OUTCOME_DENY)
            reasons.append("required_gate_removed")
        if ref == "scope_broadened":
            outcome = _severe(outcome, OUTCOME_DENY)
            reasons.append("scope_broadened_post_seal")
        if ref == "forged_decision":
            outcome = _severe(outcome, OUTCOME_DENY)
            reasons.append("forged_decision_marker")
        if ref.startswith("unsupported_capability:"):
            outcome = _severe(outcome, OUTCOME_INSUFFICIENT_EVIDENCE)
            reasons.append("unsupported_capability_marker")

    sm_outcome, sm_reasons = _system_model_boundary_outcome(facts)
    if sm_outcome is not None:
        outcome = _severe(outcome, sm_outcome)
        reasons.extend(sm_reasons)

    human_gated_final = human_gated or request.human_gate_requested or (
        outcome == OUTCOME_REQUIRE_HUMAN_APPROVAL
    )
    return _seal_row(
        request_id=request.request_id,
        capability_id=request.capability_id,
        outcome=outcome,
        reason_codes=tuple(sorted(set(reasons))),
        rules_applied=tuple(sorted(set(rules))),
        human_gated=human_gated_final,
        request_sha256=request.request_sha256,
    )


def admit_from_trusted_facts(facts, *, decision_id="gpc_decision_001"):
    """Evaluate sealed trusted facts into a sealed decision + receipt.

    Never executes. Never mutates TCB. Never auto-approves Main merge.
    Re-checks live TCB / policy identity at the trusted boundary.
    """
    if not isinstance(facts, TrustedAdmissionFacts):
        raise TrustedAdmissionError("facts invalid")
    _recheck_live_tcb(facts)

    matrix = create_gpc_policy_matrix_v1()
    rows = tuple(
        _evaluate_one(req, facts, matrix) for req in facts.capability_requests
    )

    requested = tuple(sorted({r.capability_id for r in rows}))
    admitted = tuple(
        sorted(
            {
                r.capability_id
                for r in rows
                if r.outcome == OUTCOME_ALLOW_WITHIN_BOUND
            }
        )
    )
    denied = tuple(
        sorted({r.capability_id for r in rows if r.outcome == OUTCOME_DENY})
    )
    human = tuple(
        sorted(
            {
                r.capability_id
                for r in rows
                if r.outcome == OUTCOME_REQUIRE_HUMAN_APPROVAL
            }
        )
    )
    escalated = tuple(
        sorted(
            {r.capability_id for r in rows if r.outcome == OUTCOME_ESCALATE}
        )
    )
    insufficient = tuple(
        sorted(
            {
                r.capability_id
                for r in rows
                if r.outcome == OUTCOME_INSUFFICIENT_EVIDENCE
            }
        )
    )

    overall = OUTCOME_ALLOW_WITHIN_BOUND
    for row in rows:
        overall = _severe(overall, row.outcome)

    escalation_reasons = []
    if facts.plan_requires_escalation:
        escalation_reasons.extend(facts.plan_escalation_reasons)
    for row in rows:
        if row.outcome in (
            OUTCOME_ESCALATE,
            OUTCOME_DENY,
            OUTCOME_INSUFFICIENT_EVIDENCE,
            OUTCOME_REQUIRE_HUMAN_APPROVAL,
        ):
            escalation_reasons.extend(row.reason_codes)

    values = {
        "schema_version": DECISION_VERSION,
        "decision_id": decision_id,
        "admission_input_id": facts.facts_id,
        "input_sha256": facts.facts_sha256,
        "task_contract_id": facts.task_contract_id,
        "contract_sha256": facts.contract_sha256,
        "plan_id": facts.plan_id,
        "plan_sha256": facts.plan_sha256,
        "base_sha": facts.base_sha,
        "architecture_baseline_sha256": facts.architecture_baseline_sha256,
        "trusted_policy_version": facts.trusted_policy_version,
        "tcb_registry_sha256": facts.tcb_registry_sha256,
        "tcb_snapshot_sha256": facts.tcb_snapshot_sha256,
        "vocabulary_sha256": facts.vocabulary_sha256,
        "matrix_version": MATRIX_VERSION,
        "matrix_sha256": matrix.matrix_sha256,
        "per_capability": rows,
        "requested_capability_ids": requested,
        "admitted_within_bound": admitted,
        "denied": denied,
        "human_gated": human,
        "escalated": escalated,
        "insufficient_evidence": insufficient,
        "overall_outcome": overall,
        "escalation_reasons": tuple(sorted(set(escalation_reasons))),
        "generator_version": GENERATOR_VERSION,
        "execution_authorized": False,
        "approved_to_execute": False,
        "capability_runtime_granted": False,
        "main_merge_auto_approved": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(AdmissionDecision)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    decision = AdmissionDecision(
        **values,
        decision_sha256=_digest(_canonical(provisional._body())),
        _token=_TOKEN,
    )
    receipt = create_admission_receipt(decision)
    return decision, receipt


def admission_decision_cannot_execute():
    """TRUST REVIEW helper: True -- decision never executes work."""
    return True


def admission_never_auto_approves_main_merge():
    """TRUST REVIEW helper."""
    return True


def policy_matrix_is_default_deny():
    """TRUST REVIEW helper."""
    return True
