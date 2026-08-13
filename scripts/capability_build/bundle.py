"""Pure, deterministic human-review bundles for V0.4A Slice 5.

The bundle is a sanitized summary of already-produced Slice 1-4 records. It
does not contain returned file content, worker prose, command output, or job
history notes. It grants no runtime authority and cannot execute, install,
register, deploy, read files, write files, or inspect repository state.
"""

import json
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

from scripts.capability_build.evidence import (
    EvidenceBundle,
    VerificationPlan,
)
from scripts.capability_build.intake import FileIntakeDecision, IntakeResult
from scripts.capability_build.job import BuildJob
from scripts.capability_build.scope import FrozenScope


class BundleError(ValueError):
    """Raised when review-bundle inputs are absent, unsafe, or mismatched."""


SCHEMA_VERSION = 1
READINESS_READY = "ready_for_human_review"
READINESS_BLOCKED = "blocked"
READINESS_INCOMPLETE = "incomplete"
MAX_BUNDLE_TEXT_BYTES = 4_096
MAX_BUNDLE_SUMMARY_BYTES = 64 * 1024

_ALLOWED_EVIDENCE_STATUSES = ("passed", "failed", "blocked", "not_run")


def _bounded_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BundleError(f"{field_name} must be nonblank text")
    normalized = value.strip()
    if any(
        unicodedata.category(character) == "Cc"
        for character in normalized
    ):
        raise BundleError(f"{field_name} contains control characters")
    if len(normalized.encode("utf-8")) > MAX_BUNDLE_TEXT_BYTES:
        raise BundleError(
            f"{field_name} exceeds {MAX_BUNDLE_TEXT_BYTES} bytes"
        )
    return normalized


def _ordered_text(values: Any, field_name: str) -> tuple:
    if isinstance(values, (str, bytes)):
        raise BundleError(f"{field_name} must be a sequence")
    try:
        items = tuple(values)
    except TypeError as error:
        raise BundleError(f"{field_name} must be a sequence") from error

    normalized = []
    identities = set()
    for item in items:
        value = _bounded_text(item, field_name)
        identity = unicodedata.normalize("NFC", value).casefold()
        if identity in identities:
            raise BundleError(f"duplicate {field_name}: {value}")
        identities.add(identity)
        normalized.append(value)
    return tuple(
        sorted(
            normalized,
            key=lambda value: (
                unicodedata.normalize("NFC", value).casefold(),
                value,
            ),
        )
    )


@dataclass(frozen=True)
class BuildMetadata:
    """Bounded BuildJob identity without history notes or worker prose."""

    job_id: str
    capability_id: str
    state: str
    fix_round: int
    base_sha: str
    spec_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "job_id",
            "capability_id",
            "state",
            "base_sha",
            "spec_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded_text(getattr(self, field_name), field_name),
            )
        if isinstance(self.fix_round, bool) or not isinstance(
            self.fix_round, int
        ):
            raise BundleError("fix_round must be an integer")
        if self.fix_round < 0:
            raise BundleError("fix_round cannot be negative")

    def to_dict(self) -> dict:
        return {
            "base_sha": self.base_sha,
            "capability_id": self.capability_id,
            "fix_round": self.fix_round,
            "job_id": self.job_id,
            "spec_sha256": self.spec_sha256,
            "state": self.state,
        }


@dataclass(frozen=True)
class FrozenScopeSummary:
    """Review-safe scope data with justification prose deliberately omitted."""

    allowed_new_files: tuple
    allowed_existing_files: tuple
    protected_files: tuple
    forbidden_paths: tuple
    justified_paths: tuple

    def __post_init__(self) -> None:
        for field_name in (
            "allowed_new_files",
            "allowed_existing_files",
            "protected_files",
            "forbidden_paths",
            "justified_paths",
        ):
            object.__setattr__(
                self,
                field_name,
                _ordered_text(getattr(self, field_name), field_name),
            )
        allowed = set(
            self.allowed_new_files + self.allowed_existing_files
        )
        if set(self.justified_paths) != allowed:
            raise BundleError(
                "justified_paths must match every allowed scope path"
            )

    def to_dict(self) -> dict:
        return {
            "allowed_existing_files": list(self.allowed_existing_files),
            "allowed_new_files": list(self.allowed_new_files),
            "forbidden_paths": list(self.forbidden_paths),
            "justified_paths": list(self.justified_paths),
            "protected_files": list(self.protected_files),
        }


@dataclass(frozen=True)
class IntakeSummary:
    """Sanitized intake result containing no returned file content."""

    accepted: bool
    touched_files: tuple
    blocking_findings: tuple
    warnings: tuple

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise BundleError("intake accepted must be a boolean")
        for field_name in (
            "touched_files",
            "blocking_findings",
            "warnings",
        ):
            object.__setattr__(
                self,
                field_name,
                _ordered_text(getattr(self, field_name), field_name),
            )
        if self.accepted and self.blocking_findings:
            raise BundleError(
                "accepted intake cannot contain blocking findings"
            )
        if self.accepted and not self.touched_files:
            raise BundleError("accepted intake must contain touched files")
        if not self.accepted and not self.blocking_findings:
            raise BundleError(
                "rejected intake must contain blocking findings"
            )

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "blocking_findings": list(self.blocking_findings),
            "touched_files": list(self.touched_files),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class VerificationCommandSummary:
    """Non-executable command metadata; argv is deliberately excluded."""

    name: str
    kind: str
    timeout_seconds: int
    allow_network: bool
    writes_allowed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _bounded_text(self.name, "name"))
        object.__setattr__(self, "kind", _bounded_text(self.kind, "kind"))
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int)
            or self.timeout_seconds <= 0
        ):
            raise BundleError("timeout_seconds must be a positive integer")
        if self.allow_network is not False:
            raise BundleError("review commands cannot allow network access")
        if self.writes_allowed is not False:
            raise BundleError("review commands cannot allow writes")

    def to_dict(self) -> dict:
        return {
            "allow_network": self.allow_network,
            "kind": self.kind,
            "name": self.name,
            "timeout_seconds": self.timeout_seconds,
            "writes_allowed": self.writes_allowed,
        }


@dataclass(frozen=True)
class VerificationPlanSummary:
    """Bound plan metadata with no executable argv or expected prose."""

    touched_files: tuple
    commands: tuple

    def __post_init__(self) -> None:
        touched_files = _ordered_text(self.touched_files, "touched file")
        try:
            commands = tuple(self.commands)
        except TypeError as error:
            raise BundleError("commands must be a sequence") from error
        if not commands or any(
            not isinstance(command, VerificationCommandSummary)
            for command in commands
        ):
            raise BundleError(
                "commands must contain VerificationCommandSummary values"
            )
        names = [command.name.casefold() for command in commands]
        if len(names) != len(set(names)):
            raise BundleError("verification command names must be unique")
        stable_commands = tuple(
            sorted(
                commands,
                key=lambda command: (
                    command.kind.casefold(),
                    command.name.casefold(),
                    command.name,
                ),
            )
        )
        object.__setattr__(self, "touched_files", touched_files)
        object.__setattr__(self, "commands", stable_commands)

    def to_dict(self) -> dict:
        return {
            "commands": [command.to_dict() for command in self.commands],
            "touched_files": list(self.touched_files),
        }


@dataclass(frozen=True)
class EvidenceRecordSummary:
    """Evidence status only; summaries and output excerpts are excluded."""

    command_name: str
    status: str
    exit_code: Optional[int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "command_name",
            _bounded_text(self.command_name, "command_name"),
        )
        if self.status not in _ALLOWED_EVIDENCE_STATUSES:
            raise BundleError(f"unsupported evidence status: {self.status!r}")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool)
            or not isinstance(self.exit_code, int)
        ):
            raise BundleError("exit_code must be an integer or None")

    def to_dict(self) -> dict:
        return {
            "command_name": self.command_name,
            "exit_code": self.exit_code,
            "status": self.status,
        }


@dataclass(frozen=True)
class EvidenceSummary:
    """Bounded factual status derived from a Slice 4 EvidenceBundle."""

    accepted: bool
    status: str
    missing_commands: tuple
    records: tuple

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise BundleError("evidence accepted must be a boolean")
        status = _bounded_text(self.status, "evidence status")
        if status not in ("passed", "failed", "blocked", "incomplete"):
            raise BundleError(f"unsupported evidence summary status: {status}")
        missing = _ordered_text(self.missing_commands, "missing command")
        try:
            records = tuple(self.records)
        except TypeError as error:
            raise BundleError("evidence records must be a sequence") from error
        if any(
            not isinstance(record, EvidenceRecordSummary)
            for record in records
        ):
            raise BundleError(
                "records must contain EvidenceRecordSummary values"
            )
        record_names = [record.command_name.casefold() for record in records]
        if len(record_names) != len(set(record_names)):
            raise BundleError("evidence record command names must be unique")
        stable_records = tuple(
            sorted(
                records,
                key=lambda record: (
                    record.command_name.casefold(),
                    record.command_name,
                ),
            )
        )
        if self.accepted != (status == "passed"):
            raise BundleError("evidence accepted/status mismatch")
        statuses = {record.status for record in stable_records}
        if status == "passed" and (
            missing or not stable_records or statuses != {"passed"}
        ):
            raise BundleError(
                "passed evidence must be complete and all passed"
            )
        if status == "blocked" and "blocked" not in statuses:
            raise BundleError("blocked evidence requires a blocked record")
        if status == "failed" and (
            "failed" not in statuses or "blocked" in statuses
        ):
            raise BundleError("failed evidence has inconsistent records")
        if status == "incomplete" and (
            not missing and "not_run" not in statuses
        ):
            raise BundleError(
                "incomplete evidence requires missing or not-run records"
            )
        if status == "incomplete" and (
            "failed" in statuses or "blocked" in statuses
        ):
            raise BundleError(
                "failed or blocked records cannot be merely incomplete"
            )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "missing_commands", missing)
        object.__setattr__(self, "records", stable_records)

    def to_dict(self) -> dict:
        counts = {
            status: sum(record.status == status for record in self.records)
            for status in _ALLOWED_EVIDENCE_STATUSES
        }
        return {
            "accepted": self.accepted,
            "counts": counts,
            "missing_commands": list(self.missing_commands),
            "records": [record.to_dict() for record in self.records],
            "status": self.status,
        }


@dataclass(frozen=True)
class BuildReviewBundle:
    """Immutable, sanitized review package with no operational authority."""

    job: BuildMetadata
    frozen_scope: FrozenScopeSummary
    intake: IntakeSummary
    verification_plan: Optional[VerificationPlanSummary] = None
    evidence: Optional[EvidenceSummary] = None
    readiness_status: str = field(init=False)
    review_only: bool = field(default=True, init=False)
    runtime_authority: bool = field(default=False, init=False)
    schema_version: int = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.job, BuildMetadata):
            raise BundleError("job metadata is required")
        if not isinstance(self.frozen_scope, FrozenScopeSummary):
            raise BundleError("frozen scope summary is required")
        if not isinstance(self.intake, IntakeSummary):
            raise BundleError("intake summary is required")
        if self.verification_plan is not None and not isinstance(
            self.verification_plan, VerificationPlanSummary
        ):
            raise BundleError("verification_plan has an invalid type")
        if self.evidence is not None and not isinstance(
            self.evidence, EvidenceSummary
        ):
            raise BundleError("evidence has an invalid type")
        if self.evidence is not None and self.verification_plan is None:
            raise BundleError("evidence requires a verification plan")
        if self.verification_plan is not None and (
            self.verification_plan.touched_files != self.intake.touched_files
        ):
            raise BundleError(
                "verification plan touched files do not match intake"
            )
        if self.verification_plan is not None and self.evidence is not None:
            command_names = {
                command.name for command in self.verification_plan.commands
            }
            record_names = {
                record.command_name for record in self.evidence.records
            }
            missing_names = set(self.evidence.missing_commands)
            if record_names | missing_names != command_names:
                raise BundleError(
                    "evidence command names do not match verification plan"
                )
            if record_names & missing_names:
                raise BundleError(
                    "evidence command cannot be recorded and missing"
                )

        if not self.intake.accepted or self.intake.blocking_findings:
            readiness = READINESS_BLOCKED
        elif self.verification_plan is None or self.evidence is None:
            readiness = READINESS_INCOMPLETE
        elif not self.evidence.accepted or self.evidence.status != "passed":
            readiness = READINESS_BLOCKED
        else:
            readiness = READINESS_READY
        object.__setattr__(self, "readiness_status", readiness)

        encoded = self.summary().encode("utf-8")
        if len(encoded) > MAX_BUNDLE_SUMMARY_BYTES:
            raise BundleError(
                "bundle summary exceeds "
                f"{MAX_BUNDLE_SUMMARY_BYTES} bytes"
            )

    def to_dict(self) -> dict:
        """Return deterministic, review-safe data without raw artifacts."""
        return {
            "authority": {
                "purpose": "human_review_only",
                "runtime_authority": self.runtime_authority,
            },
            "evidence": (
                None if self.evidence is None else self.evidence.to_dict()
            ),
            "frozen_scope": self.frozen_scope.to_dict(),
            "intake": self.intake.to_dict(),
            "job": self.job.to_dict(),
            "readiness_status": self.readiness_status,
            "schema_version": self.schema_version,
            "verification_plan": (
                None
                if self.verification_plan is None
                else self.verification_plan.to_dict()
            ),
        }

    def summary(self) -> str:
        """Return stable JSON intended only for a human review package."""
        return json.dumps(
            self.to_dict(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ) + "\n"


def _build_metadata(job: BuildJob) -> BuildMetadata:
    if not isinstance(job, BuildJob):
        raise BundleError("job must be a BuildJob")
    return BuildMetadata(
        job_id=job.job_id,
        capability_id=job.capability_id,
        state=job.state,
        fix_round=job.fix_round,
        base_sha=job.base_sha,
        spec_sha256=job.spec_sha256,
    )


def _scope_summary(scope: FrozenScope) -> FrozenScopeSummary:
    if not isinstance(scope, FrozenScope):
        raise BundleError("frozen_scope must be a FrozenScope")
    return FrozenScopeSummary(
        allowed_new_files=scope.allowed_new_files,
        allowed_existing_files=scope.allowed_existing_files,
        protected_files=scope.protected_files,
        forbidden_paths=scope.forbidden_paths,
        justified_paths=tuple(scope.justifications),
    )


def _intake_summary(
    intake_result: IntakeResult,
    scope: FrozenScope,
) -> IntakeSummary:
    if not isinstance(intake_result, IntakeResult):
        raise BundleError("intake_result must be an IntakeResult")
    if intake_result.accepted:
        if not intake_result.file_decisions or any(
            not isinstance(decision, FileIntakeDecision)
            for decision in intake_result.file_decisions
        ):
            raise BundleError(
                "accepted intake requires file intake decisions"
            )
        decision_paths = tuple(
            decision.path for decision in intake_result.file_decisions
        )
        if any(
            not decision.accepted
            for decision in intake_result.file_decisions
        ):
            raise BundleError(
                "accepted intake contains a rejected file decision"
            )
        if (
            len(decision_paths) != len(intake_result.touched_files)
            or set(decision_paths) != set(intake_result.touched_files)
        ):
            raise BundleError(
                "accepted intake decisions do not match touched files"
            )
        for decision in intake_result.file_decisions:
            if decision.operation not in ("create", "modify"):
                raise BundleError(
                    "accepted intake has an unsupported file operation"
                )
            scope_decision = (
                scope.decision_for_create(decision.path)
                if decision.operation == "create"
                else scope.decision_for_modify(decision.path)
            )
            if not scope_decision.allowed:
                raise BundleError(
                    "accepted intake does not match the frozen scope"
                )
    return IntakeSummary(
        accepted=intake_result.accepted,
        touched_files=intake_result.touched_files,
        blocking_findings=intake_result.blocking_findings,
        warnings=intake_result.warnings,
    )


def _plan_summary(
    plan: Optional[VerificationPlan],
    intake: IntakeSummary,
) -> Optional[VerificationPlanSummary]:
    if plan is None:
        return None
    if not isinstance(plan, VerificationPlan):
        raise BundleError("verification_plan must be a VerificationPlan")
    if not intake.accepted:
        raise BundleError("rejected intake cannot have a verification plan")
    if tuple(plan.touched_files) != intake.touched_files:
        raise BundleError(
            "verification plan touched files do not match intake"
        )
    return VerificationPlanSummary(
        touched_files=plan.touched_files,
        commands=tuple(
            VerificationCommandSummary(
                name=command.name,
                kind=command.kind,
                timeout_seconds=command.timeout_seconds,
                allow_network=command.allow_network,
                writes_allowed=command.writes_allowed,
            )
            for command in plan.commands
        ),
    )


def _evidence_summary(
    evidence: Optional[EvidenceBundle],
    plan: Optional[VerificationPlan],
) -> Optional[EvidenceSummary]:
    if evidence is None:
        return None
    if plan is None:
        raise BundleError("evidence requires a verification plan")
    if not isinstance(evidence, EvidenceBundle):
        raise BundleError("evidence_bundle must be an EvidenceBundle")
    if evidence.plan != plan:
        raise BundleError("evidence does not belong to verification plan")
    return EvidenceSummary(
        accepted=evidence.accepted,
        status=evidence.status,
        missing_commands=evidence.missing_commands,
        records=tuple(
            EvidenceRecordSummary(
                command_name=record.command_name,
                status=record.status,
                exit_code=record.exit_code,
            )
            for record in evidence.records
        ),
    )


def build_review_bundle(
    job: BuildJob,
    frozen_scope: FrozenScope,
    intake_result: IntakeResult,
    verification_plan: Optional[VerificationPlan] = None,
    evidence_bundle: Optional[EvidenceBundle] = None,
) -> BuildReviewBundle:
    """Package Slice 1-4 data into a sanitized, non-operational bundle."""
    job_summary = _build_metadata(job)
    scope_summary = _scope_summary(frozen_scope)
    intake_summary = _intake_summary(intake_result, frozen_scope)
    plan_summary = _plan_summary(verification_plan, intake_summary)
    evidence_summary = _evidence_summary(
        evidence_bundle, verification_plan
    )
    return BuildReviewBundle(
        job=job_summary,
        frozen_scope=scope_summary,
        intake=intake_summary,
        verification_plan=plan_summary,
        evidence=evidence_summary,
    )
