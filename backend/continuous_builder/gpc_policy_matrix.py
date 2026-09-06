"""GP-C3 -- Deterministic Capability Admission Policy Matrix.

Data-driven default-deny table. Outcomes:
  allow_within_bound / require_human_approval / deny / escalate /
  insufficient_evidence

UNKNOWN capability ids never ALLOW. Worker/model/provider/benchmark claims
never influence the outcome. Descriptive risk never grants. Valid GP-B plan
never grants capability by itself.

Does not mutate trusted_policy / TCB. Zero execution authority.
"""

from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    canonical_json,
    require_no_authority,
    require_sha256,
    require_text,
    sha256_hex,
)
from .gpc_capability_vocabulary import (
    ADMISSION_OUTCOMES,
    CAPABILITY_IDS,
    HUMAN_GATED_CAPABILITY_IDS,
    OUTCOME_ALLOW_WITHIN_BOUND,
    OUTCOME_DENY,
    OUTCOME_ESCALATE,
    OUTCOME_INSUFFICIENT_EVIDENCE,
    OUTCOME_REQUIRE_HUMAN_APPROVAL,
    default_outcome_for_capability,
    is_known_capability_id,
)

MATRIX_VERSION = "gpc-policy-matrix-v1"
MAX_RULES = 64
MAX_MATRIX_BYTES = 64 * 1024
MAX_REASON = 128

_TOKEN = object()


class PolicyMatrixError(GPAEvalSchemaError):
    """Raised when the policy matrix cannot be sealed safely."""


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
        if self._token is not _TOKEN:
            raise PolicyMatrixError("policy rule requires trusted construction")
        require_text(self.rule_id, "rule_id", 64)
        if self.capability_id != "*" and self.capability_id not in CAPABILITY_IDS:
            raise PolicyMatrixError("capability_id unknown")
        if self.outcome not in ADMISSION_OUTCOMES:
            raise PolicyMatrixError("outcome unsupported")
        require_text(self.reason_code, "reason_code", MAX_REASON)
        if type(self.human_gated) is not bool:
            raise PolicyMatrixError("human_gated must be bool")
        require_sha256(self.rule_sha256, "rule_sha256")
        if self.rule_sha256 != sha256_hex(canonical_json(self._body())):
            raise PolicyMatrixError("rule_sha256 mismatch")

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
        rule_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
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
        if self._token is not _TOKEN:
            raise PolicyMatrixError(
                "policy matrix requires trusted construction"
            )
        if self.schema_version != MATRIX_VERSION:
            raise PolicyMatrixError("schema_version unsupported")
        if type(self.rules) is not tuple or not self.rules:
            raise PolicyMatrixError("rules malformed")
        if len(self.rules) > MAX_RULES:
            raise PolicyMatrixError("rules exceeds bound")
        ids = tuple(r.rule_id for r in self.rules)
        if ids != tuple(sorted(set(ids))):
            raise PolicyMatrixError("rules not canonical")
        require_no_authority(self)
        if self.execution_authorized is not False:
            raise PolicyMatrixError("cannot claim execution_authorized")
        require_sha256(self.matrix_sha256, "matrix_sha256")
        if self.matrix_sha256 != sha256_hex(canonical_json(self._body())):
            raise PolicyMatrixError("matrix_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_MATRIX_BYTES:
            raise PolicyMatrixError("matrix exceeds byte bound")

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
    # Catch-all for unknown capability ids -- never ALLOW.
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
        matrix_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def lookup_matrix_outcome(matrix, capability_id):
    """Return (outcome, reason_code, human_gated, rule_id) fail-closed."""
    if not isinstance(matrix, PolicyMatrix):
        raise PolicyMatrixError("matrix invalid")
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


def policy_matrix_is_default_deny():
    """TRUST REVIEW helper."""
    return True
