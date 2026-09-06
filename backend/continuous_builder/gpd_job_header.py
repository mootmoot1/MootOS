"""GP-D1 -- Durable Job Header (immutable control-plane envelope).

SYSTEM OWNS TRUTH. WORKER ONLY PROPOSES.

A DurableJobHeader is the sealed, never-silently-mutated identity of one
Golden Plan job. It binds repository identity, base SHA, FrozenTaskContract,
ExecutionPlan, and GP-C AdmissionDecision digests plus scope/capability/
budget ceilings captured at creation/admission. Recovery must never widen
those ceilings.

This module is control-plane only: no worker launch, no provider call,
no GitHub mutation, no schema/DB migration, no TCB edit. Persistence of
headers is owned by ``gpd_job_store`` (file-backed append-only ledger)
so GP-D does not require a SQLite migration in this phase.

Conflict note (reported, not rewritten): existing ``builder_*`` queue /
attempt / lease tables model blueprint-slice product lifecycle
(idea->done). GP-D models job execution lifecycle bound to GP-B/GP-C
contracts. The two vocabularies stay separate; GP-D does not overload
``queue_store`` / ``leases`` tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    canonical_json,
    require_base_sha,
    require_id,
    require_sha256,
    require_sorted_unique_paths,
    require_text,
    sha256_hex,
)
from .timestamps import parse_timestamp

JOB_HEADER_SCHEMA_VERSION = "gpd-job-header-v1"
MAX_HEADER_BYTES = 64 * 1024
MAX_CEILING_INT = 10 ** 12
MAX_GATES = 32
MAX_CAPABILITIES = 64
_TOKEN = object()


class JobHeaderError(GPAEvalSchemaError):
    """Raised when a durable job header cannot be sealed safely."""


def _require_nonneg_int_or_none(value, label):
    if value is None:
        return None
    if type(value) is not int or value < 0 or value > MAX_CEILING_INT:
        raise JobHeaderError(f"{label} is malformed")
    return value


def _require_text_tuple(values, label, maximum):
    if type(values) is not tuple:
        raise JobHeaderError(f"{label} must be a tuple")
    if len(values) > maximum:
        raise JobHeaderError(f"{label} exceeds bound")
    out = []
    for item in values:
        out.append(require_text(item, label, 512))
    return tuple(out)


@dataclass(frozen=True)
class DurableJobHeader:
    """Immutable job envelope. Authority flags are structurally False."""

    schema_version: str
    job_id: str
    repository_identity: str
    base_sha: str
    task_contract_id: str
    task_contract_sha256: str
    execution_plan_id: str
    execution_plan_sha256: str
    admission_decision_id: str
    admission_decision_sha256: str
    architecture_baseline_sha256: str
    trusted_policy_version: str
    tcb_registry_sha256: str
    tcb_snapshot_sha256: str
    approved_scope_ceiling: tuple
    forbidden_scope: tuple
    admitted_capability_ids: tuple
    budget_ceiling_wall_clock_seconds: object
    budget_ceiling_input_tokens: object
    budget_ceiling_output_tokens: object
    budget_ceiling_cost_usd_cents: object
    required_gates: tuple
    logical_order: int
    created_at: str
    header_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    provider_launch_authorized: bool = False
    scope_expansion_authorized: bool = False
    recovery_may_widen_scope: bool = False
    recovery_may_widen_budget: bool = False
    recovery_may_widen_capability: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise JobHeaderError("DurableJobHeader requires trusted factory")
        if self.schema_version != JOB_HEADER_SCHEMA_VERSION:
            raise JobHeaderError("schema_version is unsupported")
        require_id(self.job_id, "job_id")
        require_text(self.repository_identity, "repository_identity", 256)
        require_base_sha(self.base_sha, "base_sha")
        require_id(self.task_contract_id, "task_contract_id")
        require_sha256(self.task_contract_sha256, "task_contract_sha256")
        require_id(self.execution_plan_id, "execution_plan_id")
        require_sha256(self.execution_plan_sha256, "execution_plan_sha256")
        require_id(self.admission_decision_id, "admission_decision_id")
        require_sha256(
            self.admission_decision_sha256, "admission_decision_sha256"
        )
        require_sha256(
            self.architecture_baseline_sha256,
            "architecture_baseline_sha256",
        )
        require_text(
            self.trusted_policy_version, "trusted_policy_version", 128
        )
        require_sha256(self.tcb_registry_sha256, "tcb_registry_sha256")
        require_sha256(self.tcb_snapshot_sha256, "tcb_snapshot_sha256")
        if type(self.approved_scope_ceiling) is not tuple:
            raise JobHeaderError("approved_scope_ceiling malformed")
        require_sorted_unique_paths(
            self.approved_scope_ceiling, "approved_scope_ceiling", 256
        )
        if type(self.forbidden_scope) is not tuple:
            raise JobHeaderError("forbidden_scope malformed")
        require_sorted_unique_paths(
            self.forbidden_scope, "forbidden_scope", 256
        )
        if type(self.admitted_capability_ids) is not tuple:
            raise JobHeaderError("admitted_capability_ids malformed")
        if len(self.admitted_capability_ids) > MAX_CAPABILITIES:
            raise JobHeaderError("admitted_capability_ids exceeds bound")
        _CAP_ID = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
        for cap in self.admitted_capability_ids:
            if not isinstance(cap, str) or _CAP_ID.fullmatch(cap) is None:
                raise JobHeaderError("admitted_capability_ids malformed")
        if self.admitted_capability_ids != tuple(
            sorted(set(self.admitted_capability_ids))
        ):
            raise JobHeaderError(
                "admitted_capability_ids must be sorted unique"
            )
        _require_nonneg_int_or_none(
            self.budget_ceiling_wall_clock_seconds,
            "budget_ceiling_wall_clock_seconds",
        )
        _require_nonneg_int_or_none(
            self.budget_ceiling_input_tokens, "budget_ceiling_input_tokens"
        )
        _require_nonneg_int_or_none(
            self.budget_ceiling_output_tokens, "budget_ceiling_output_tokens"
        )
        _require_nonneg_int_or_none(
            self.budget_ceiling_cost_usd_cents,
            "budget_ceiling_cost_usd_cents",
        )
        if type(self.required_gates) is not tuple:
            raise JobHeaderError("required_gates malformed")
        gates = _require_text_tuple(
            self.required_gates, "required_gates", MAX_GATES
        )
        if gates != tuple(sorted(set(gates))):
            raise JobHeaderError("required_gates must be sorted unique")
        if type(self.logical_order) is not int or self.logical_order < 0:
            raise JobHeaderError("logical_order is malformed")
        parse_timestamp(self.created_at, "created_at", JobHeaderError)
        for name in AUTHORITY_FLAGS:
            if getattr(self, name, False) is not False:
                raise JobHeaderError("job header cannot claim authority")
        for name in (
            "execution_authorized",
            "provider_launch_authorized",
            "scope_expansion_authorized",
            "recovery_may_widen_scope",
            "recovery_may_widen_budget",
            "recovery_may_widen_capability",
        ):
            if getattr(self, name) is not False:
                raise JobHeaderError(f"{name} must be False")
        require_sha256(self.header_sha256, "header_sha256")
        if self.header_sha256 != sha256_hex(canonical_json(self._body())):
            raise JobHeaderError("header_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_HEADER_BYTES:
            raise JobHeaderError("header exceeds byte bound")

    def _body(self):
        return {
            "admission_decision_id": self.admission_decision_id,
            "admission_decision_sha256": self.admission_decision_sha256,
            "admitted_capability_ids": list(self.admitted_capability_ids),
            "approved_scope_ceiling": list(self.approved_scope_ceiling),
            "architecture_baseline_sha256": self.architecture_baseline_sha256,
            "base_sha": self.base_sha,
            "budget_ceiling_cost_usd_cents": self.budget_ceiling_cost_usd_cents,
            "budget_ceiling_input_tokens": self.budget_ceiling_input_tokens,
            "budget_ceiling_output_tokens": self.budget_ceiling_output_tokens,
            "budget_ceiling_wall_clock_seconds": (
                self.budget_ceiling_wall_clock_seconds
            ),
            "created_at": self.created_at,
            "execution_authorized": False,
            "execution_plan_id": self.execution_plan_id,
            "execution_plan_sha256": self.execution_plan_sha256,
            "forbidden_scope": list(self.forbidden_scope),
            "github_authorized": False,
            "job_id": self.job_id,
            "logical_order": self.logical_order,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "provider_launch_authorized": False,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "recovery_may_widen_budget": False,
            "recovery_may_widen_capability": False,
            "recovery_may_widen_scope": False,
            "repository_identity": self.repository_identity,
            "required_gates": list(self.required_gates),
            "result_trusted": False,
            "schema_version": self.schema_version,
            "scope_expansion_authorized": False,
            "task_contract_id": self.task_contract_id,
            "task_contract_sha256": self.task_contract_sha256,
            "tcb_registry_sha256": self.tcb_registry_sha256,
            "tcb_snapshot_sha256": self.tcb_snapshot_sha256,
            "trusted_policy_version": self.trusted_policy_version,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = dict(self._body())
        body["header_sha256"] = self.header_sha256
        return body


def create_durable_job_header(**values):
    """Seal an immutable DurableJobHeader. Digests re-derived."""
    for name in AUTHORITY_FLAGS:
        values[name] = False
    values["execution_authorized"] = False
    values["provider_launch_authorized"] = False
    values["scope_expansion_authorized"] = False
    values["recovery_may_widen_scope"] = False
    values["recovery_may_widen_budget"] = False
    values["recovery_may_widen_capability"] = False
    values.setdefault("schema_version", JOB_HEADER_SCHEMA_VERSION)
    values.setdefault("budget_ceiling_wall_clock_seconds", None)
    values.setdefault("budget_ceiling_input_tokens", None)
    values.setdefault("budget_ceiling_output_tokens", None)
    values.setdefault("budget_ceiling_cost_usd_cents", None)
    if "approved_scope_ceiling" in values and not isinstance(
        values["approved_scope_ceiling"], tuple
    ):
        values["approved_scope_ceiling"] = tuple(
            values["approved_scope_ceiling"]
        )
    if "forbidden_scope" in values and not isinstance(
        values["forbidden_scope"], tuple
    ):
        values["forbidden_scope"] = tuple(values["forbidden_scope"])
    caps = values.get("admitted_capability_ids", ())
    if not isinstance(caps, tuple):
        caps = tuple(caps)
    values["admitted_capability_ids"] = tuple(sorted(set(caps)))
    gates = values.get("required_gates", ())
    if not isinstance(gates, tuple):
        gates = tuple(gates)
    values["required_gates"] = tuple(sorted(set(gates)))
    body = {
        "admission_decision_id": values["admission_decision_id"],
        "admission_decision_sha256": values["admission_decision_sha256"],
        "admitted_capability_ids": list(values["admitted_capability_ids"]),
        "approved_scope_ceiling": list(values["approved_scope_ceiling"]),
        "architecture_baseline_sha256": values[
            "architecture_baseline_sha256"
        ],
        "base_sha": values["base_sha"],
        "budget_ceiling_cost_usd_cents": values.get(
            "budget_ceiling_cost_usd_cents"
        ),
        "budget_ceiling_input_tokens": values.get(
            "budget_ceiling_input_tokens"
        ),
        "budget_ceiling_output_tokens": values.get(
            "budget_ceiling_output_tokens"
        ),
        "budget_ceiling_wall_clock_seconds": values.get(
            "budget_ceiling_wall_clock_seconds"
        ),
        "created_at": values["created_at"],
        "execution_authorized": False,
        "execution_plan_id": values["execution_plan_id"],
        "execution_plan_sha256": values["execution_plan_sha256"],
        "forbidden_scope": list(values["forbidden_scope"]),
        "github_authorized": False,
        "job_id": values["job_id"],
        "logical_order": values["logical_order"],
        "main_advancement_authorized": False,
        "merge_authorized": False,
        "provider_launch_authorized": False,
        "publication_authorized": False,
        "queue_transition_authorized": False,
        "recovery_may_widen_budget": False,
        "recovery_may_widen_capability": False,
        "recovery_may_widen_scope": False,
        "repository_identity": values["repository_identity"],
        "required_gates": list(values["required_gates"]),
        "result_trusted": False,
        "schema_version": values["schema_version"],
        "scope_expansion_authorized": False,
        "task_contract_id": values["task_contract_id"],
        "task_contract_sha256": values["task_contract_sha256"],
        "tcb_registry_sha256": values["tcb_registry_sha256"],
        "tcb_snapshot_sha256": values["tcb_snapshot_sha256"],
        "trusted_policy_version": values["trusted_policy_version"],
        "worker_output_trusted": False,
    }
    digest = sha256_hex(canonical_json(body))
    return DurableJobHeader(
        **{**values, "header_sha256": digest, "_token": _TOKEN}
    )


def header_ceilings_cannot_widen(existing, candidate):
    """Return True iff candidate is identical (no silent rewrite/widen)."""
    if not isinstance(existing, DurableJobHeader):
        raise JobHeaderError("existing header invalid")
    if not isinstance(candidate, DurableJobHeader):
        raise JobHeaderError("candidate header invalid")
    if existing.job_id != candidate.job_id:
        return False
    return existing.header_sha256 == candidate.header_sha256


def job_header_is_control_plane_only():
    return True
