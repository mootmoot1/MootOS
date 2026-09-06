"""GP-C1 -- Trusted Capability Vocabulary & Request Contract.

Admission-only vocabulary for Continuous Builder capability requests.
Reuses naming patterns from:
- ``trusted_policy.AUTHORITY_FLAGS`` (merge / main / github / publication)
- ``worker_authorization`` (credentials / network / github grants = False)
- ``scripts/capability_build/pr_publication_authorization`` (PR create)
- chat ``capability_catalog`` style (dotted capability ids) -- without
  creating a competing executable registry

A capability id here is NEVER an executor key. Default-deny: UNKNOWN and
unregistered ids never grant. Descriptive risk never grants. Worker /
model / provider / benchmark claims never grant.

Zero authority. No execution. No network. No TCB mutation.
"""

from dataclasses import dataclass, field

from .gpa_eval_schema import (
    AUTHORITY_FLAGS,
    GPAEvalSchemaError,
    canonical_json,
    require_id,
    require_no_authority,
    require_sha256,
    require_sorted_unique_paths,
    require_text,
    sha256_hex,
)

VOCABULARY_VERSION = "gpc-capability-vocabulary-v1"
REQUEST_SCHEMA_VERSION = "gpc-capability-request-v1"
GENERATOR_VERSION = "gpc-capability-request-generator-v1"

MAX_REQUESTS = 32
MAX_SCOPE_PATHS = 64
MAX_EVIDENCE_REFS = 16
MAX_TEXT = 512
MAX_BUDGET_VALUE = 10**9
MAX_REQUEST_BYTES = 16 * 1024
MAX_VOCAB_BYTES = 32 * 1024

# Decision / admission outcomes used by the policy matrix (GP-C3).
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

# Resource classes for requests -- descriptive grouping, not authority.
RESOURCE_CLASSES = frozenset(
    {
        "repo",
        "file",
        "test",
        "verifier",
        "subprocess",
        "sandbox",
        "git",
        "pr",
        "github",
        "network",
        "credentials",
        "database",
        "production",
        "deploy",
        "trusted_policy",
        "tcb",
        "approval_rules",
        "main",
        "unknown",
    }
)

OPERATIONS = frozenset(
    {
        "read",
        "write",
        "exec",
        "create",
        "metadata",
        "connect",
        "use",
        "migrate",
        "deploy",
        "change",
        "merge",
        "advance",
        "unknown",
    }
)

# Canonical CB capability ids. Map mission classes onto existing authority /
# authorization vocabulary where possible; never invent a parallel system.
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

# Human-gated classes may be packaged for review but never auto-approved.
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

# Default matrix hint per capability (overridden by scope/risk/TCB rules).
_DEFAULT_OUTCOMES = {
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

_RESOURCE_FOR_CAPABILITY = {
    "cb.repo.read": "repo",
    "cb.file.read_bounded": "file",
    "cb.file.write_bounded": "file",
    "cb.test.exec": "test",
    "cb.verifier.exec": "verifier",
    "cb.subprocess": "subprocess",
    "cb.sandbox.container": "sandbox",
    "cb.git.branch_worktree": "git",
    "cb.pr.create": "pr",
    "cb.github.metadata": "github",
    "cb.network": "network",
    "cb.credentials": "credentials",
    "cb.db.schema": "database",
    "cb.production.data": "production",
    "cb.deploy.staging": "deploy",
    "cb.trusted_policy.change": "trusted_policy",
    "cb.tcb.change": "tcb",
    "cb.approval_rules.change": "approval_rules",
    "cb.main.merge": "main",
    "cb.main.advance": "main",
}

_OPERATION_FOR_CAPABILITY = {
    "cb.repo.read": "read",
    "cb.file.read_bounded": "read",
    "cb.file.write_bounded": "write",
    "cb.test.exec": "exec",
    "cb.verifier.exec": "exec",
    "cb.subprocess": "exec",
    "cb.sandbox.container": "exec",
    "cb.git.branch_worktree": "create",
    "cb.pr.create": "create",
    "cb.github.metadata": "metadata",
    "cb.network": "connect",
    "cb.credentials": "use",
    "cb.db.schema": "migrate",
    "cb.production.data": "read",
    "cb.deploy.staging": "deploy",
    "cb.trusted_policy.change": "change",
    "cb.tcb.change": "change",
    "cb.approval_rules.change": "change",
    "cb.main.merge": "merge",
    "cb.main.advance": "advance",
}

_TOKEN = object()
_VOCAB_TOKEN = object()


class CapabilityVocabularyError(GPAEvalSchemaError):
    """Raised when capability vocabulary / request evidence is unsafe."""


def is_known_capability_id(capability_id):
    return (
        isinstance(capability_id, str) and capability_id in CAPABILITY_IDS
    )


def is_human_gated_capability(capability_id):
    return capability_id in HUMAN_GATED_CAPABILITY_IDS


def default_outcome_for_capability(capability_id):
    if not is_known_capability_id(capability_id):
        return OUTCOME_INSUFFICIENT_EVIDENCE
    return _DEFAULT_OUTCOMES[capability_id]


def resource_class_for_capability(capability_id):
    if not is_known_capability_id(capability_id):
        return "unknown"
    return _RESOURCE_FOR_CAPABILITY[capability_id]


def operation_for_capability(capability_id):
    if not is_known_capability_id(capability_id):
        return "unknown"
    return _OPERATION_FOR_CAPABILITY[capability_id]


@dataclass(frozen=True)
class CapabilityDescriptor:
    """One sealed vocabulary entry. Grants nothing."""

    capability_id: str
    resource_class: str
    operation: str
    human_gated: bool
    default_outcome: str
    description: str
    descriptor_sha256: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise CapabilityVocabularyError(
                "capability descriptor requires trusted construction"
            )
        if self.capability_id not in CAPABILITY_IDS:
            raise CapabilityVocabularyError("capability_id is unknown")
        if self.resource_class not in RESOURCE_CLASSES:
            raise CapabilityVocabularyError("resource_class unsupported")
        if self.operation not in OPERATIONS:
            raise CapabilityVocabularyError("operation unsupported")
        if type(self.human_gated) is not bool:
            raise CapabilityVocabularyError("human_gated must be bool")
        if self.default_outcome not in ADMISSION_OUTCOMES:
            raise CapabilityVocabularyError("default_outcome unsupported")
        require_text(self.description, "description", MAX_TEXT)
        require_sha256(self.descriptor_sha256, "descriptor_sha256")
        if self.descriptor_sha256 != sha256_hex(canonical_json(self._body())):
            raise CapabilityVocabularyError("descriptor_sha256 mismatch")

    def _body(self):
        return {
            "capability_id": self.capability_id,
            "default_outcome": self.default_outcome,
            "description": self.description,
            "human_gated": self.human_gated,
            "operation": self.operation,
            "resource_class": self.resource_class,
        }

    def to_dict(self):
        body = self._body()
        body["descriptor_sha256"] = self.descriptor_sha256
        return body


def _seal_descriptor(capability_id, description):
    values = {
        "capability_id": capability_id,
        "resource_class": resource_class_for_capability(capability_id),
        "operation": operation_for_capability(capability_id),
        "human_gated": is_human_gated_capability(capability_id),
        "default_outcome": default_outcome_for_capability(capability_id),
        "description": description,
    }
    provisional = object.__new__(CapabilityDescriptor)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return CapabilityDescriptor(
        **values,
        descriptor_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


@dataclass(frozen=True)
class CapabilityVocabulary:
    """Sealed default-deny vocabulary for GP-C admission."""

    schema_version: str
    capabilities: tuple
    vocabulary_sha256: str
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
        if self._token is not _VOCAB_TOKEN:
            raise CapabilityVocabularyError(
                "capability vocabulary requires trusted construction"
            )
        if self.schema_version != VOCABULARY_VERSION:
            raise CapabilityVocabularyError("schema_version unsupported")
        if type(self.capabilities) is not tuple or not self.capabilities:
            raise CapabilityVocabularyError("capabilities malformed")
        ids = tuple(item.capability_id for item in self.capabilities)
        if ids != tuple(sorted(set(ids))):
            raise CapabilityVocabularyError("capabilities not canonical")
        if set(ids) != CAPABILITY_IDS:
            raise CapabilityVocabularyError("vocabulary incomplete or extra")
        require_no_authority(self)
        if self.execution_authorized is not False:
            raise CapabilityVocabularyError("cannot claim execution_authorized")
        require_sha256(self.vocabulary_sha256, "vocabulary_sha256")
        if self.vocabulary_sha256 != sha256_hex(canonical_json(self._body())):
            raise CapabilityVocabularyError("vocabulary_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_VOCAB_BYTES:
            raise CapabilityVocabularyError("vocabulary exceeds byte bound")

    def _body(self):
        return {
            "capabilities": [c.to_dict() for c in self.capabilities],
            "execution_authorized": False,
            "github_authorized": False,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "worker_output_trusted": False,
        }

    def to_dict(self):
        body = self._body()
        body["vocabulary_sha256"] = self.vocabulary_sha256
        return body

    def get(self, capability_id):
        for item in self.capabilities:
            if item.capability_id == capability_id:
                return item
        return None


_DESCRIPTIONS = {
    "cb.repo.read": "Read repository metadata and tree within frozen scope",
    "cb.file.read_bounded": "Bounded file read within allowed_scope",
    "cb.file.write_bounded": "Bounded file write within allowed_scope",
    "cb.test.exec": "Execute unit/integration tests in bounded check runner",
    "cb.verifier.exec": "Invoke structural / adversarial verifier surfaces",
    "cb.subprocess": "Spawn subprocess outside declared check runner",
    "cb.sandbox.container": "Launch sandbox / container containment",
    "cb.git.branch_worktree": "Create git branch or worktree (no Main)",
    "cb.pr.create": "Create GitHub pull request (publication auth separate)",
    "cb.github.metadata": "Read GitHub PR/issue metadata (no mutate)",
    "cb.network": "Outbound network beyond declared sandbox deny-default",
    "cb.credentials": "Use or expand credentials / secrets",
    "cb.db.schema": "Database / schema migration",
    "cb.production.data": "Touch production data stores",
    "cb.deploy.staging": "Deploy to staging or similar environments",
    "cb.trusted_policy.change": "Modify trusted_policy / policy version",
    "cb.tcb.change": "Modify TCB registry / protected paths",
    "cb.approval_rules.change": "Modify approval-rule / chief-builder gates",
    "cb.main.merge": "Merge into Main",
    "cb.main.advance": "Advance Main tip / release pointer",
}


def create_gpc_capability_vocabulary_v1():
    """Return the sealed default-deny CB capability vocabulary."""
    caps = tuple(
        sorted(
            (
                _seal_descriptor(cid, _DESCRIPTIONS[cid])
                for cid in CAPABILITY_IDS
            ),
            key=lambda item: item.capability_id,
        )
    )
    values = {
        "schema_version": VOCABULARY_VERSION,
        "capabilities": caps,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    values["execution_authorized"] = False
    provisional = object.__new__(CapabilityVocabulary)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return CapabilityVocabulary(
        **values,
        vocabulary_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_VOCAB_TOKEN,
    )


def _require_budget(value, label):
    if value is None:
        return None
    if type(value) is not int or isinstance(value, bool):
        raise CapabilityVocabularyError(f"{label} must be int or None")
    if value <= 0 or value > MAX_BUDGET_VALUE:
        raise CapabilityVocabularyError(f"{label} is out of bounds")
    return value


@dataclass(frozen=True)
class CapabilityRequest:
    """Sealed worker/system proposal for one capability. Zero authority."""

    schema_version: str
    request_id: str
    capability_id: str
    task_contract_id: str
    contract_sha256: str
    plan_id: str
    plan_sha256: str
    operation: str
    resource_class: str
    requested_scope: tuple
    budget_wall_clock_seconds: object
    budget_input_tokens: object
    budget_output_tokens: object
    budget_command_count: object
    budget_path_count: object
    budget_subprocess_count: object
    budget_network_calls: object
    budget_write_path_count: object
    evidence_refs: tuple
    human_gate_requested: bool
    worker_safe_claim: bool
    provider_id: object
    model_id: object
    benchmark_score: object
    generator_version: str
    request_sha256: str
    publication_authorized: bool = False
    queue_transition_authorized: bool = False
    github_authorized: bool = False
    merge_authorized: bool = False
    main_advancement_authorized: bool = False
    result_trusted: bool = False
    worker_output_trusted: bool = False
    execution_authorized: bool = False
    capability_granted: bool = False
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise CapabilityVocabularyError(
                "capability request requires trusted construction"
            )
        if self.schema_version != REQUEST_SCHEMA_VERSION:
            raise CapabilityVocabularyError("schema_version unsupported")
        if self.generator_version != GENERATOR_VERSION:
            raise CapabilityVocabularyError("generator_version unsupported")
        require_id(self.request_id, "request_id")
        require_id(self.task_contract_id, "task_contract_id")
        require_id(self.plan_id, "plan_id")
        # Unknown capability ids are allowed on the request object so the
        # admission matrix can fail closed to INSUFFICIENT_EVIDENCE / DENY.
        if not isinstance(self.capability_id, str) or not self.capability_id:
            raise CapabilityVocabularyError("capability_id malformed")
        if len(self.capability_id.encode("utf-8")) > 128:
            raise CapabilityVocabularyError("capability_id exceeds bound")
        require_sha256(self.contract_sha256, "contract_sha256")
        require_sha256(self.plan_sha256, "plan_sha256")
        if self.operation not in OPERATIONS:
            raise CapabilityVocabularyError("operation unsupported")
        if self.resource_class not in RESOURCE_CLASSES:
            raise CapabilityVocabularyError("resource_class unsupported")
        require_sorted_unique_paths(
            self.requested_scope, "requested_scope", MAX_SCOPE_PATHS
        )
        _require_budget(
            self.budget_wall_clock_seconds, "budget_wall_clock_seconds"
        )
        _require_budget(self.budget_input_tokens, "budget_input_tokens")
        _require_budget(self.budget_output_tokens, "budget_output_tokens")
        _require_budget(self.budget_command_count, "budget_command_count")
        _require_budget(self.budget_path_count, "budget_path_count")
        _require_budget(
            self.budget_subprocess_count, "budget_subprocess_count"
        )
        _require_budget(self.budget_network_calls, "budget_network_calls")
        _require_budget(self.budget_write_path_count, "budget_write_path_count")
        if type(self.evidence_refs) is not tuple:
            raise CapabilityVocabularyError("evidence_refs malformed")
        if len(self.evidence_refs) > MAX_EVIDENCE_REFS:
            raise CapabilityVocabularyError("evidence_refs exceeds bound")
        for ref in self.evidence_refs:
            require_text(ref, "evidence_refs", MAX_TEXT)
        if type(self.human_gate_requested) is not bool:
            raise CapabilityVocabularyError("human_gate_requested must be bool")
        if type(self.worker_safe_claim) is not bool:
            raise CapabilityVocabularyError("worker_safe_claim must be bool")
        for name in ("provider_id", "model_id"):
            value = getattr(self, name)
            if value is not None:
                require_text(value, name, 128)
        if self.benchmark_score is not None:
            if type(self.benchmark_score) not in (int, float) or isinstance(
                self.benchmark_score, bool
            ):
                raise CapabilityVocabularyError("benchmark_score malformed")
        require_no_authority(self)
        if self.execution_authorized is not False:
            raise CapabilityVocabularyError("cannot claim execution_authorized")
        if self.capability_granted is not False:
            raise CapabilityVocabularyError(
                "capability request cannot claim capability_granted"
            )
        require_sha256(self.request_sha256, "request_sha256")
        if self.request_sha256 != sha256_hex(canonical_json(self._body())):
            raise CapabilityVocabularyError("request_sha256 mismatch")
        if len(canonical_json(self.to_dict())) > MAX_REQUEST_BYTES:
            raise CapabilityVocabularyError("request exceeds byte bound")

    def _body(self):
        return {
            "benchmark_score": self.benchmark_score,
            "budget_command_count": self.budget_command_count,
            "budget_input_tokens": self.budget_input_tokens,
            "budget_network_calls": self.budget_network_calls,
            "budget_output_tokens": self.budget_output_tokens,
            "budget_path_count": self.budget_path_count,
            "budget_subprocess_count": self.budget_subprocess_count,
            "budget_wall_clock_seconds": self.budget_wall_clock_seconds,
            "budget_write_path_count": self.budget_write_path_count,
            "capability_granted": False,
            "capability_id": self.capability_id,
            "contract_sha256": self.contract_sha256,
            "evidence_refs": list(self.evidence_refs),
            "execution_authorized": False,
            "generator_version": self.generator_version,
            "github_authorized": False,
            "human_gate_requested": self.human_gate_requested,
            "main_advancement_authorized": False,
            "merge_authorized": False,
            "model_id": self.model_id,
            "operation": self.operation,
            "plan_id": self.plan_id,
            "plan_sha256": self.plan_sha256,
            "provider_id": self.provider_id,
            "publication_authorized": False,
            "queue_transition_authorized": False,
            "request_id": self.request_id,
            "requested_scope": list(self.requested_scope),
            "resource_class": self.resource_class,
            "result_trusted": False,
            "schema_version": self.schema_version,
            "task_contract_id": self.task_contract_id,
            "worker_output_trusted": False,
            "worker_safe_claim": self.worker_safe_claim,
        }

    def to_dict(self):
        body = self._body()
        body["request_sha256"] = self.request_sha256
        return body


def create_capability_request(
    *,
    request_id,
    capability_id,
    task_contract_id,
    contract_sha256,
    plan_id,
    plan_sha256,
    requested_scope=(),
    operation=None,
    resource_class=None,
    budget_wall_clock_seconds=None,
    budget_input_tokens=None,
    budget_output_tokens=None,
    budget_command_count=None,
    budget_path_count=None,
    budget_subprocess_count=None,
    budget_network_calls=None,
    budget_write_path_count=None,
    evidence_refs=(),
    human_gate_requested=False,
    worker_safe_claim=False,
    provider_id=None,
    model_id=None,
    benchmark_score=None,
):
    """Seal one capability request proposal. Never grants capability."""
    if operation is None:
        operation = operation_for_capability(capability_id)
    if resource_class is None:
        resource_class = resource_class_for_capability(capability_id)
    if human_gate_requested is False and is_human_gated_capability(
        capability_id
    ):
        # Human-gated capability classes always carry the gate flag on the
        # sealed request; callers cannot silently omit it.
        human_gate_requested = True
    values = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "request_id": request_id,
        "capability_id": capability_id,
        "task_contract_id": task_contract_id,
        "contract_sha256": contract_sha256,
        "plan_id": plan_id,
        "plan_sha256": plan_sha256,
        "operation": operation,
        "resource_class": resource_class,
        "requested_scope": tuple(sorted(set(requested_scope))),
        "budget_wall_clock_seconds": budget_wall_clock_seconds,
        "budget_input_tokens": budget_input_tokens,
        "budget_output_tokens": budget_output_tokens,
        "budget_command_count": budget_command_count,
        "budget_path_count": budget_path_count,
        "budget_subprocess_count": budget_subprocess_count,
        "budget_network_calls": budget_network_calls,
        "budget_write_path_count": budget_write_path_count,
        "evidence_refs": tuple(evidence_refs),
        "human_gate_requested": human_gate_requested,
        "worker_safe_claim": worker_safe_claim,
        "provider_id": provider_id,
        "model_id": model_id,
        "benchmark_score": benchmark_score,
        "generator_version": GENERATOR_VERSION,
        "capability_granted": False,
        "execution_authorized": False,
    }
    for name in AUTHORITY_FLAGS:
        values[name] = False
    provisional = object.__new__(CapabilityRequest)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return CapabilityRequest(
        **values,
        request_sha256=sha256_hex(canonical_json(provisional._body())),
        _token=_TOKEN,
    )


def capability_request_has_zero_authority():
    """TRUST REVIEW helper: True -- request never grants capability."""
    return True
