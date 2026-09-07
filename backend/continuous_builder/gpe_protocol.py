"""GP-E: bounded, non-TCB worker messages. System owns truth.

Seals detect byte changes, not authorship or trusted verification. Consumers
must validate against system-owned GP-B/C/D objects; parsing never launches.
No persistence, network, subprocess, retry, or lifecycle mutation lives here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields
from typing import ClassVar

from .context_engine import ContextPackage, ContextSupplement
from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    canonical_json,
    require_id,
    require_text,
    require_sha256,
    require_sorted_unique_paths,
    sha256_hex,
    require_base_sha,
)
from .gpb_task_contract import FrozenTaskContract
from .gpb_decomposer import ExecutionPlan
from .gpc_admission_input import AdmissionInput
from .gpc_admission_decision import facts_from_admission_input
from .gpc_trusted_admission_core import AdmissionDecision, CAPABILITY_IDS
from .gpd_attempt_ledger import AttemptRecord
from .gpd_job_header import DurableJobHeader

_TOKEN = object()
PROTOCOL_VERSION = "gpe-worker-v1"
MAX_MESSAGE_BYTES = 128 * 1024
MAX_CONTEXT_BYTES = 2 * 1024 * 1024
RESULT_STATUSES = frozenset(
    {
        "completed",
        "partial",
        "blocked",
        "failed",
        "timed_out",
        "cancelled",
        "context_insufficient",
        "capability_denied",
        "execution_unknown",
    }
)
ERROR_CATEGORIES = frozenset(
    {
        "rate_limited",
        "provider_unavailable",
        "authentication_unavailable",
        "model_unavailable",
        "context_too_large",
        "malformed_response",
        "worker_protocol_violation",
        "timed_out",
        "cancelled",
        "sandbox_failure",
        "unknown_failure",
    }
)
ZERO_AUTHORITY = AUTHORITY_FLAGS + (
    "execution_authorized",
    "provider_launch_authorized",
    "scope_expansion_authorized",
)
BUDGET_FIELDS = (
    "budget_ceiling_wall_clock_seconds",
    "budget_ceiling_input_tokens",
    "budget_ceiling_output_tokens",
    "budget_ceiling_cost_usd_cents",
)
STOP_CONDITIONS = (
    "budget_or_timeout_exhausted",
    "capability_not_admitted",
    "context_insufficient",
    "human_gate_required",
    "scope_boundary",
    "execution_unknown",
    "cancellation_requested",
)
OUTPUT_CONTRACT = (
    "gpe-worker-result-v1; artifact references only; claims untrusted"
)


class WorkerProtocolError(ValueError):
    """Malformed or mismatched evidence; never a retry decision."""


def _check(condition, reason):
    if not condition:
        raise WorkerProtocolError(reason)


def _texts(value, label, maximum=32):
    _check(type(value) is tuple and len(value) <= maximum, label)
    for item in value:
        require_text(item, label, 2048)


def _json_value(value):
    if isinstance(value, _Sealed):
        return value.to_dict()
    if type(value) is tuple:
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class _Sealed:
    """Local message sealing idiom using existing non-TCB primitives."""

    digest: str
    protocol_version: str = PROTOCOL_VERSION
    kind: ClassVar[str]
    _token: object = field(default=None, repr=False, compare=False)

    def _body(self):
        body = {
            f.name: _json_value(getattr(self, f.name))
            for f in fields(self)
            if f.name not in ("digest", "_token")
        }
        body["kind"] = self.kind
        body.update({name: False for name in ZERO_AUTHORITY})
        return body

    def to_dict(self):
        return dict(self._body(), digest=self.digest)

    def canonical_bytes(self):
        return canonical_json(self.to_dict())

    def __getattr__(self, name):
        if name in ZERO_AUTHORITY:
            return False
        raise AttributeError(name)

    def __post_init__(self):
        _check(self._token is _TOKEN, "message requires factory construction")
        _check(self.protocol_version == PROTOCOL_VERSION, "protocol version")
        for name in ZERO_AUTHORITY:
            _check(getattr(self, name) is False, "authority forbidden")
        self._validate()
        require_sha256(self.digest, "digest")
        _check(
            self.digest == sha256_hex(canonical_json(self._body())),
            "digest mismatch",
        )
        _check(
            len(self.canonical_bytes()) <= MAX_MESSAGE_BYTES,
            "message byte bound",
        )


def _seal(cls, **values):
    # Private factories construct, then validate the full immutable object.
    provisional = object.__new__(cls)
    for f in fields(cls):
        object.__setattr__(provisional, f.name, values.get(f.name, f.default))
    digest = sha256_hex(canonical_json(provisional._body()))
    return cls(**values, digest=digest, _token=_TOKEN)


def _validated(value, cls):
    _check(type(value) is cls, "wrong contract type")
    value.__post_init__()


@dataclass(frozen=True)
class WorkerIdentity(_Sealed):
    kind: ClassVar[str] = "worker_identity"
    worker_type: str = ""
    implementation: str = ""
    implementation_version: str = ""
    provider_id: str | None = None
    model_id: str | None = None
    advertised_capability_ids: tuple = ()

    def _validate(self):
        for name in (
            "worker_type",
            "implementation",
            "implementation_version",
        ):
            require_text(getattr(self, name), name, 256)
        for name in ("provider_id", "model_id"):
            if getattr(self, name) is not None:
                require_text(getattr(self, name), name, 256)
        _texts(self.advertised_capability_ids, "advertised capabilities", 64)
        _check(
            self.advertised_capability_ids
            == tuple(sorted(set(self.advertised_capability_ids))),
            "capabilities not sorted unique",
        )
        _check(
            set(self.advertised_capability_ids) <= CAPABILITY_IDS,
            "unknown capability vocabulary",
        )


def create_worker_identity(**values):
    return _seal(WorkerIdentity, **values)


@dataclass(frozen=True)
class SliceJobCorrelation(_Sealed):
    kind: ClassVar[str] = "slice_job_correlation"
    blueprint_id: str = ""
    blueprint_sha256: str = ""
    slice_id: str = ""
    job_id: str = ""
    header_sha256: str = ""

    def _validate(self):
        require_id(self.job_id, "job_id")
        # Product IDs use the existing blueprint vocabulary, not GP-D IDs.
        for name in ("blueprint_id", "slice_id"):
            value = getattr(self, name)
            require_text(value, name, 128)
            _check(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)
                is not None,
                "product identifier",
            )
        for name in ("blueprint_sha256", "header_sha256"):
            require_sha256(getattr(self, name), name)


def create_slice_job_correlation(
    *, header, blueprint_id, blueprint_sha256, slice_id
):
    _validated(header, DurableJobHeader)
    return _seal(
        SliceJobCorrelation,
        blueprint_id=blueprint_id,
        blueprint_sha256=blueprint_sha256,
        slice_id=slice_id,
        job_id=header.job_id,
        header_sha256=header.header_sha256,
    )


def context_binding(package, supplements=()):
    """Bind actual CE bytes; IDs are content-addressed because CE has no ID.

    No selection/extraction helper is recreated. The caller uses CE assembly
    and supplement APIs, retaining and delivering those same canonical bytes.
    """
    _validated(package, ContextPackage)
    _check(
        type(supplements) is tuple and len(supplements) <= 8,
        "supplement bound",
    )
    refs = []
    payloads = [package.canonical_bytes()]
    for supplement in supplements:
        _validated(supplement, ContextSupplement)
        _check(
            supplement.package_sha256 == package.package_sha256
            and supplement.base_sha == package.base_sha
            and supplement.original_request_sha256 == package.request_sha256,
            "supplement context mismatch",
        )
        refs.append(
            (
                supplement.supplement_sha256,
                supplement.supplement_request_sha256,
            )
        )
        payloads.append(canonical_json(supplement.to_dict()))
    _check(len(set(refs)) == len(refs), "duplicate supplement")
    _check(sum(map(len, payloads)) <= MAX_CONTEXT_BYTES, "context byte bound")
    return (
        "sha256:" + package.package_sha256,
        package.package_sha256,
        package.base_sha,
        package.request_sha256,
        package.model_sha256,
        tuple(refs),
        tuple(sha256_hex(payload) for payload in payloads),
    )


@dataclass(frozen=True)
class WorkerRequest(_Sealed):
    kind: ClassVar[str] = "worker_request"
    request_id: str = ""
    job_id: str = ""
    attempt_id: str = ""
    header_sha256: str = ""
    attempt_sha256: str = ""
    # IDs/digests only for full upstream objects, not nested snapshots.
    task_contract_ref: tuple = ()
    execution_plan_ref: tuple = ()
    admission_ref: tuple = ()
    admission_input_ref: tuple = ()
    repository_identity: str = ""
    base_sha: str = ""
    allowed_scope: tuple = ()
    forbidden_scope: tuple = ()
    admitted_capability_ids: tuple = ()
    # Exact serialized GP-C request constraints, not new admission decisions.
    admitted_request_constraints: tuple = ()
    budget_ceilings: tuple = ()
    human_gates: tuple = ()
    human_gated_capability_ids: tuple = ()
    admission_outcome: str = ""
    task_goal: str = ""
    success_criteria: tuple = ()
    task_constraints: tuple = ()
    stop_conditions: tuple = STOP_CONDITIONS
    context: tuple = ()
    correlation: SliceJobCorrelation | None = None
    requested_output_contract: str = OUTPUT_CONTRACT

    def _validate(self):
        for name in ("request_id", "job_id", "attempt_id"):
            require_id(getattr(self, name), name)
        for name in ("header_sha256", "attempt_sha256"):
            require_sha256(getattr(self, name), name)
        for ref in (
            self.task_contract_ref,
            self.execution_plan_ref,
            self.admission_ref,
            self.admission_input_ref,
        ):
            _check(type(ref) is tuple and len(ref) == 2, "reference shape")
            require_id(ref[0], "reference id")
            require_sha256(ref[1], "reference digest")
        require_text(self.repository_identity, "repository", 256)
        require_base_sha(self.base_sha)
        for name in ("allowed_scope", "forbidden_scope"):
            _check(type(getattr(self, name)) is tuple, "scope shape")
            require_sorted_unique_paths(getattr(self, name), name, 256)
        for name in (
            "admitted_capability_ids",
            "human_gates",
            "human_gated_capability_ids",
            "success_criteria",
            "task_constraints",
            "stop_conditions",
        ):
            _texts(getattr(self, name), name, 64)
        _check(
            set(self.admitted_capability_ids) <= CAPABILITY_IDS,
            "unknown admitted capability",
        )
        _check(self.stop_conditions == STOP_CONDITIONS, "stop conditions")
        _check(
            self.requested_output_contract == OUTPUT_CONTRACT,
            "output contract",
        )
        require_text(self.task_goal, "goal", 4096)
        require_text(self.admission_outcome, "admission outcome", 128)
        _check(
            type(self.budget_ceilings) is tuple
            and len(self.budget_ceilings) == 4,
            "budgets",
        )
        for value in self.budget_ceilings:
            _check(
                value is None or (type(value) is int and 0 <= value <= 10**12),
                "budget bound",
            )
        _check(
            type(self.admitted_request_constraints) is tuple
            and len(self.admitted_request_constraints) <= 32,
            "capability constraint bound",
        )
        for constraint in self.admitted_request_constraints:
            require_text(constraint, "capability constraints", 16384)
            _validate_capability_constraints(
                constraint, self.admitted_capability_ids
            )
        _check(
            type(self.context) is tuple and len(self.context) == 7,
            "context shape",
        )
        _check(self.context[0] == "sha256:" + self.context[1], "context id")
        _check(self.context[2] == self.base_sha, "context base")
        for value in (self.context[1], self.context[3], self.context[4]):
            require_sha256(value, "context digest")
        _check(
            type(self.context[5]) is tuple and len(self.context[5]) <= 8,
            "supplement references",
        )
        for ref in self.context[5]:
            _check(type(ref) is tuple and len(ref) == 2, "supplement ref")
            for value in ref:
                require_sha256(value, "supplement digest")
        _check(
            type(self.context[6]) is tuple
            and len(self.context[6]) == 1 + len(self.context[5]),
            "delivery digests",
        )
        for value in self.context[6]:
            require_sha256(value, "delivery digest")
        _validated(self.correlation, SliceJobCorrelation)
        _check(
            (self.correlation.job_id, self.correlation.header_sha256)
            == (self.job_id, self.header_sha256),
            "correlation mismatch",
        )


def _validate_capability_constraints(serialized, admitted):
    budget_names = {
        "budget_wall_clock_seconds",
        "budget_input_tokens",
        "budget_output_tokens",
        "budget_command_count",
        "budget_path_count",
        "budget_subprocess_count",
        "budget_network_calls",
        "budget_write_path_count",
    }
    names = budget_names | {
        "request_id",
        "request_sha256",
        "capability_id",
        "requested_scope",
        "operation",
        "resource_class",
    }
    try:
        data = json.loads(serialized, object_pairs_hook=_unique_object)
        _check(
            type(data) is dict and set(data) == names,
            "capability bounds shape",
        )
        _check(
            canonical_json(data).decode("utf-8") == serialized,
            "capability bounds not canonical",
        )
        require_id(data["request_id"], "capability request id")
        require_sha256(data["request_sha256"], "capability request digest")
        _check(
            data["capability_id"] in admitted, "unadmitted capability bounds"
        )
        require_text(data["operation"], "operation", 128)
        require_text(data["resource_class"], "resource class", 128)
        _check(type(data["requested_scope"]) is list, "capability scope shape")
        require_sorted_unique_paths(
            tuple(data["requested_scope"]), "capability scope", 64
        )
        for name in budget_names:
            value = data[name]
            _check(
                value is None or (type(value) is int and 0 <= value <= 10**9),
                "capability budget bound",
            )
    except (ValueError, TypeError, KeyError) as exc:
        raise WorkerProtocolError("malformed capability constraints") from exc


def create_worker_request(
    *,
    header,
    attempt,
    contract,
    plan,
    admission,
    admission_input,
    package,
    correlation,
    supplements=(),
):
    """System-side packet assembly, never dispatch permission.

    Repeated assembly for one attempt has one deterministic request identity.
    Retrying requires a new GP-D attempt. GP-F owns durable replay prevention.
    """
    for obj, cls in (
        (header, DurableJobHeader),
        (attempt, AttemptRecord),
        (contract, FrozenTaskContract),
        (plan, ExecutionPlan),
        (admission, AdmissionDecision),
        (admission_input, AdmissionInput),
    ):
        _validated(obj, cls)
    _check(
        attempt.job_id == header.job_id
        and attempt.header_sha256 == header.header_sha256,
        "wrong job/attempt binding",
    )
    _check(attempt.status == "started", "attempt is not a new bounded try")
    expected = (
        (
            header.task_contract_id,
            header.task_contract_sha256,
            contract.task_contract_id,
            contract.contract_sha256,
        ),
        (
            header.execution_plan_id,
            header.execution_plan_sha256,
            plan.plan_id,
            plan.plan_sha256,
        ),
        (
            header.admission_decision_id,
            header.admission_decision_sha256,
            admission.decision_id,
            admission.decision_sha256,
        ),
        (
            plan.task_contract_id,
            plan.contract_sha256,
            contract.task_contract_id,
            contract.contract_sha256,
        ),
        (
            admission.task_contract_id,
            admission.contract_sha256,
            contract.task_contract_id,
            contract.contract_sha256,
        ),
        (
            admission.plan_id,
            admission.plan_sha256,
            plan.plan_id,
            plan.plan_sha256,
        ),
        (
            admission.admission_input_id,
            admission.input_sha256,
            admission_input.admission_input_id,
            facts_from_admission_input(admission_input).facts_sha256,
        ),
    )
    for a, b, c, d in expected:
        _check((a, b) == (c, d), "upstream identity/digest mismatch")
    for obj in (contract, plan, admission, admission_input):
        _check(
            obj.base_sha == header.base_sha
            and obj.architecture_baseline_sha256
            == header.architecture_baseline_sha256,
            "base/baseline mismatch",
        )
    _check(
        header.repository_identity == contract.repository_identity,
        "repository mismatch",
    )
    for name in (
        "trusted_policy_version",
        "tcb_registry_sha256",
        "tcb_snapshot_sha256",
    ):
        _check(
            getattr(header, name) == getattr(admission, name),
            "policy identity mismatch",
        )
    _check(
        set(header.approved_scope_ceiling) <= set(contract.allowed_scope),
        "scope ceiling widened",
    )
    _check(
        set(contract.forbidden_scope) <= set(header.forbidden_scope),
        "forbidden scope dropped",
    )
    _check(
        set(contract.required_gates) <= set(header.required_gates),
        "human gates dropped",
    )
    _check(
        set(header.admitted_capability_ids)
        <= set(admission.admitted_within_bound),
        "GP-C admission widened",
    )
    budgets = tuple(getattr(header, name) for name in BUDGET_FIELDS)
    for name, value in zip(BUDGET_FIELDS, budgets):
        ceiling = getattr(contract, name)
        _check(
            ceiling is None or (value is not None and value <= ceiling),
            "budget ceiling widened",
        )
    # Preserve GP-C per-request scope and all non-null budget metadata.
    requests = {
        r.request_sha256: r for r in admission_input.capability_requests
    }
    constraints = []
    for row in admission.per_capability:
        row.__post_init__()
        _check(row.request_sha256 in requests, "admission request missing")
        req = requests[row.request_sha256]
        req.__post_init__()
        _check(
            req.capability_id == row.capability_id
            and req.request_id == row.request_id,
            "admission row mismatch",
        )
        if (
            row.outcome == "allow_within_bound"
            and row.capability_id in header.admitted_capability_ids
        ):
            data = req.to_dict()
            bounds = {
                k: v
                for k, v in data.items()
                if k.startswith("budget_")
                or k
                in (
                    "request_id",
                    "request_sha256",
                    "capability_id",
                    "requested_scope",
                    "operation",
                    "resource_class",
                )
            }
            constraints.append(canonical_json(bounds).decode("utf-8"))
    _check(
        {json.loads(c)["capability_id"] for c in constraints}
        == set(header.admitted_capability_ids),
        "admitted bounds missing",
    )
    binding = context_binding(package, supplements)
    return _seal(
        WorkerRequest,
        request_id="gpe_"
        + sha256_hex(
            canonical_json(
                (PROTOCOL_VERSION, header.job_id, attempt.attempt_id)
            )
        )[:60],
        job_id=header.job_id,
        attempt_id=attempt.attempt_id,
        header_sha256=header.header_sha256,
        attempt_sha256=attempt.attempt_sha256,
        task_contract_ref=(
            contract.task_contract_id,
            contract.contract_sha256,
        ),
        execution_plan_ref=(plan.plan_id, plan.plan_sha256),
        admission_ref=(admission.decision_id, admission.decision_sha256),
        admission_input_ref=(
            admission_input.admission_input_id,
            admission_input.input_sha256,
        ),
        repository_identity=header.repository_identity,
        base_sha=header.base_sha,
        allowed_scope=header.approved_scope_ceiling,
        forbidden_scope=header.forbidden_scope,
        admitted_capability_ids=header.admitted_capability_ids,
        admitted_request_constraints=tuple(sorted(constraints)),
        budget_ceilings=budgets,
        human_gates=header.required_gates,
        human_gated_capability_ids=tuple(admission.human_gated),
        admission_outcome=admission.overall_outcome,
        task_goal=contract.goal,
        success_criteria=contract.acceptance_criteria,
        task_constraints=contract.constraints,
        context=binding,
        correlation=correlation,
    )


def validate_worker_request(request, **system_inputs):
    """Compare to system-owned inputs, not a worker-provided replacement."""
    _validated(request, WorkerRequest)
    expected = create_worker_request(**system_inputs)
    _check(
        request.canonical_bytes() == expected.canonical_bytes(),
        "request differs from system-owned bindings",
    )


def validate_context_delivery(request, package, supplements=()):
    _validated(request, WorkerRequest)
    _check(
        request.context == context_binding(package, supplements),
        "supplied context differs from sealed request",
    )


@dataclass(frozen=True)
class WorkerResult(_Sealed):
    kind: ClassVar[str] = "worker_result"
    request_id: str = ""
    request_sha256: str = ""
    job_id: str = ""
    attempt_id: str = ""
    worker: WorkerIdentity | None = None
    status: str = "failed"
    # Content-addressed evidence locators; GP-E does not fetch/open artifacts.
    artifact_refs: tuple = ()
    changed_path_claims: tuple = ()
    command_test_claims: tuple = ()
    stdout_summary: str | None = None
    stderr_summary: str | None = None
    worker_reported_completion: bool = False
    stop_reason: str | None = None
    error_category: str | None = None
    provider_detail: str | None = None
    # Integer tokens, milliseconds, micro-USD; None means unavailable.
    usage: tuple = (None, None, None, None)

    def _validate(self):
        for name in ("request_id", "job_id", "attempt_id"):
            require_id(getattr(self, name), name)
        require_sha256(self.request_sha256, "request digest")
        _validated(self.worker, WorkerIdentity)
        _check(self.status in RESULT_STATUSES, "unsupported result status")
        _check(
            type(self.worker_reported_completion) is bool, "completion claim"
        )
        _check(
            type(self.artifact_refs) is tuple
            and len(self.artifact_refs) <= 32,
            "artifact bound",
        )
        for ref in self.artifact_refs:
            _check(type(ref) is tuple and len(ref) == 2, "artifact reference")
            require_text(ref[0], "artifact locator", 512)
            require_sha256(ref[1], "artifact digest")
        _check(type(self.changed_path_claims) is tuple, "changed paths")
        require_sorted_unique_paths(
            self.changed_path_claims, "changed paths", 256
        )
        _texts(self.command_test_claims, "command/test claims", 32)
        for name in (
            "stdout_summary",
            "stderr_summary",
            "stop_reason",
            "provider_detail",
        ):
            value = getattr(self, name)
            if value is not None:
                require_text(value, name, 4096)
        _check(
            self.error_category is None
            or self.error_category in ERROR_CATEGORIES,
            "error category",
        )
        _check(
            type(self.usage) is tuple and len(self.usage) == 4, "usage shape"
        )
        for value in self.usage:
            _check(
                value is None or (type(value) is int and 0 <= value <= 10**12),
                "usage bound",
            )


def create_worker_result(*, request, worker, **claims):
    _validated(request, WorkerRequest)
    return _seal(
        WorkerResult,
        request_id=request.request_id,
        request_sha256=request.digest,
        job_id=request.job_id,
        attempt_id=request.attempt_id,
        worker=worker,
        **claims,
    )


def validate_worker_result(result, request, worker):
    _validated(result, WorkerResult)
    _validated(request, WorkerRequest)
    _validated(worker, WorkerIdentity)
    _check(
        (
            result.request_id,
            result.request_sha256,
            result.job_id,
            result.attempt_id,
            result.worker.digest,
        )
        == (
            request.request_id,
            request.digest,
            request.job_id,
            request.attempt_id,
            worker.digest,
        ),
        "result binding mismatch",
    )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _check(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _tuples(value):
    if type(value) is list:
        return tuple(_tuples(item) for item in value)
    return value


def decode_message(raw, cls):
    """Strict bounded reconstruction, not authentication or authorization."""
    _check(
        cls
        in (WorkerRequest, WorkerResult, WorkerIdentity, SliceJobCorrelation),
        "unsupported message class",
    )
    _check(type(raw) is bytes and len(raw) <= MAX_MESSAGE_BYTES, "wire bound")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
        _check(type(data) is dict, "message object required")
        expected = (
            {f.name for f in fields(cls) if f.name != "_token"}
            | {"kind"}
            | set(ZERO_AUTHORITY)
        )
        _check(set(data) == expected, "unknown or missing fields")
        _check(data.pop("kind") == cls.kind, "message kind mismatch")
        for name in ZERO_AUTHORITY:
            _check(data.pop(name) is False, "authority forbidden")
        if cls is WorkerRequest:
            data["correlation"] = decode_message(
                canonical_json(data["correlation"]), SliceJobCorrelation
            )
        if cls is WorkerResult:
            data["worker"] = decode_message(
                canonical_json(data["worker"]), WorkerIdentity
            )
        return cls(**{k: _tuples(v) for k, v in data.items()}, _token=_TOKEN)
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RecursionError,
        OverflowError,
    ) as exc:
        raise WorkerProtocolError("malformed worker message") from exc
