"""Exact-bound, execution-inert worker requests from frozen artifacts."""

import hashlib
import json
import re
from dataclasses import dataclass

from scripts.capability_build.handoff import HumanHandoffPackage
from scripts.capability_build.job import BuildJob
from scripts.capability_build.scope import FrozenScope

from .blueprint import SliceBlueprint
from .blueprint_parser import ParsedBlueprint
from .text_safety import utf8_length


class WorkerRequestError(ValueError):
    """Raised when a worker request cannot prove exact frozen binding."""


MAX_REQUEST_BYTES = 256 * 1024
MAX_BRIEF_BYTES = 256 * 1024
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


def _identity(value, name):
    if (
        not isinstance(value, str) or _IDENTITY.fullmatch(value) is None
        or utf8_length(value) > 256
    ):
        raise WorkerRequestError(f"{name} is malformed")
    return value


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _slice_digest(slice_blueprint):
    return hashlib.sha256(_canonical(slice_blueprint.to_dict())).hexdigest()


def _scope_digest(scope):
    return hashlib.sha256(_canonical(scope.to_dict())).hexdigest()


def _handoff_digest(handoff):
    return hashlib.sha256(_canonical(handoff.to_dict())).hexdigest()


def _job_matches_handoff(job, handoff):
    metadata = handoff.job
    return (
        metadata.job_id == job.job_id
        and metadata.capability_id == job.capability_id
        and metadata.state == job.state
        and metadata.fix_round == job.fix_round
        and metadata.base_sha == job.base_sha
        and metadata.spec_sha256 == job.spec_sha256
    )


@dataclass(frozen=True)
class FrozenWorkerRequest:
    parsed_blueprint: ParsedBlueprint
    slice_blueprint: SliceBlueprint
    job: BuildJob
    frozen_scope: FrozenScope
    handoff: HumanHandoffPackage
    worker_brief: str
    attempt_id: str
    requested_capability: str
    blueprint_digest: str
    slice_digest: str
    job_digest: str
    scope_digest: str
    handoff_digest: str
    brief_digest: str
    request_digest: str
    execution_authorized: bool = False
    launch_authorized: bool = False
    network_authorized: bool = False
    credentials_present: bool = False
    shell_authorized: bool = False

    def __post_init__(self):
        if not isinstance(self.parsed_blueprint, ParsedBlueprint):
            raise WorkerRequestError("parsed blueprint is invalid")
        if not isinstance(self.slice_blueprint, SliceBlueprint):
            raise WorkerRequestError("slice blueprint is invalid")
        if not isinstance(self.job, BuildJob):
            raise WorkerRequestError("BuildJob is invalid")
        if not isinstance(self.frozen_scope, FrozenScope):
            raise WorkerRequestError("frozen scope is invalid")
        if not isinstance(self.handoff, HumanHandoffPackage):
            raise WorkerRequestError("handoff is invalid")
        _identity(self.attempt_id, "attempt ID")
        _identity(self.requested_capability, "requested capability")
        blueprint = self.parsed_blueprint.blueprint
        matches = tuple(
            item for item in blueprint.slices
            if item.slice_id == self.slice_blueprint.slice_id
        )
        if len(matches) != 1 or matches[0] != self.slice_blueprint:
            raise WorkerRequestError("slice does not bind parsed blueprint")
        if self.blueprint_digest != self.parsed_blueprint.content_sha256:
            raise WorkerRequestError("blueprint digest mismatch")
        if self.slice_digest != _slice_digest(self.slice_blueprint):
            raise WorkerRequestError("slice digest mismatch")
        if self.job_digest != self.job.content_sha256:
            raise WorkerRequestError("job digest mismatch")
        if self.scope_digest != _scope_digest(self.frozen_scope):
            raise WorkerRequestError("scope digest mismatch")
        if self.handoff_digest != _handoff_digest(self.handoff):
            raise WorkerRequestError("handoff digest mismatch")
        if (
            not isinstance(self.worker_brief, str) or not self.worker_brief
            or utf8_length(self.worker_brief) > MAX_BRIEF_BYTES
        ):
            raise WorkerRequestError("worker brief is malformed or excessive")
        if self.brief_digest != hashlib.sha256(
            self.worker_brief.encode("utf-8")
        ).hexdigest():
            raise WorkerRequestError("brief digest mismatch")
        if not _job_matches_handoff(self.job, self.handoff):
            raise WorkerRequestError("job and handoff identity mismatch")
        if not self.handoff.approvable or self.handoff.runtime_authority:
            raise WorkerRequestError(
                "handoff is not an approved frozen source"
            )
        if self.job.base_sha != blueprint.source_commit:
            raise WorkerRequestError("pinned base does not bind blueprint")
        if self.job.spec_sha256 != self.slice_digest:
            raise WorkerRequestError("BuildJob spec does not bind slice")
        if self.job.capability_id != self.requested_capability or (
            self.requested_capability
            not in self.slice_blueprint.requested_capabilities
        ):
            raise WorkerRequestError("requested capability binding mismatch")
        allowed_scope = set(self.frozen_scope.allowed_new_files) | set(
            self.frozen_scope.allowed_existing_files
        )
        if not allowed_scope or not allowed_scope.issubset(
            self.slice_blueprint.allowed_paths
        ):
            raise WorkerRequestError("frozen scope grows beyond slice scope")
        if self.job.job_id not in self.worker_brief or (
            self.job.base_sha not in self.worker_brief
        ):
            raise WorkerRequestError("worker brief does not bind job and base")
        if any(
            value is not False for value in (
                self.execution_authorized, self.launch_authorized,
                self.network_authorized, self.credentials_present,
                self.shell_authorized,
            )
        ):
            raise WorkerRequestError("worker request cannot grant authority")
        expected = hashlib.sha256(self._payload()).hexdigest()
        if self.request_digest != expected:
            raise WorkerRequestError("request digest mismatch")
        if len(self.canonical_bytes()) > MAX_REQUEST_BYTES:
            raise WorkerRequestError("worker request exceeds byte bound")

    def _body(self):
        return {
            "acceptance_criteria": list(
                self.slice_blueprint.acceptance_criteria
            ),
            "attempt_id": self.attempt_id,
            "blueprint_digest": self.blueprint_digest,
            "blueprint_id": self.parsed_blueprint.blueprint.blueprint_id,
            "blueprint_version": (
                self.parsed_blueprint.blueprint.blueprint_version
            ),
            "brief_digest": self.brief_digest,
            "credentials_present": False,
            "execution_authorized": False,
            "handoff_digest": self.handoff_digest,
            "job_digest": self.job_digest,
            "job_id": self.job.job_id,
            "launch_authorized": False,
            "network_authorized": False,
            "pinned_base": self.job.base_sha,
            "requested_capability": self.requested_capability,
            "required_gates": list(self.slice_blueprint.required_gates),
            "required_tests": list(self.slice_blueprint.required_tests),
            "scope": self.frozen_scope.to_dict(),
            "scope_digest": self.scope_digest,
            "shell_authorized": False,
            "slice_digest": self.slice_digest,
            "slice_id": self.slice_blueprint.slice_id,
            "slice_version": self.slice_blueprint.version,
            "slice_budget": self.slice_blueprint.budget.to_dict(),
            "v04a_budget": self.job.budgets.to_dict(),
        }

    def _payload(self):
        return _canonical(self._body())

    def canonical_bytes(self):
        value = self._body()
        value["request_digest"] = self.request_digest
        return _canonical(value)


def create_frozen_worker_request(
    parsed_blueprint, slice_blueprint, job, frozen_scope, handoff,
    worker_brief, attempt_id, requested_capability,
):
    if (
        not isinstance(worker_brief, str) or not worker_brief
        or utf8_length(worker_brief) > MAX_BRIEF_BYTES
    ):
        raise WorkerRequestError("worker brief is malformed or excessive")
    values = {
        "blueprint_digest": parsed_blueprint.content_sha256,
        "slice_digest": _slice_digest(slice_blueprint),
        "job_digest": job.content_sha256,
        "scope_digest": _scope_digest(frozen_scope),
        "handoff_digest": _handoff_digest(handoff),
        "brief_digest": hashlib.sha256(
            worker_brief.encode("utf-8")
        ).hexdigest(),
    }
    provisional = object.__new__(FrozenWorkerRequest)
    for name, value in {
        "parsed_blueprint": parsed_blueprint,
        "slice_blueprint": slice_blueprint,
        "job": job,
        "frozen_scope": frozen_scope,
        "handoff": handoff,
        "worker_brief": worker_brief,
        "attempt_id": attempt_id,
        "requested_capability": requested_capability,
        **values,
        "execution_authorized": False,
        "launch_authorized": False,
        "network_authorized": False,
        "credentials_present": False,
        "shell_authorized": False,
    }.items():
        object.__setattr__(provisional, name, value)
    digest = hashlib.sha256(provisional._payload()).hexdigest()
    return FrozenWorkerRequest(
        parsed_blueprint, slice_blueprint, job, frozen_scope, handoff,
        worker_brief, attempt_id, requested_capability,
        values["blueprint_digest"], values["slice_digest"],
        values["job_digest"], values["scope_digest"],
        values["handoff_digest"], values["brief_digest"], digest,
    )
