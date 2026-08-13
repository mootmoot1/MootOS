"""Pure verification planning and evidence records for V0.4A Slice 4.

This module describes verification commands and evaluates already-produced
records. It never executes commands, reads or writes files, invokes Git, or
inspects a checkout. A plan is inert data, not execution authority.
"""

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from scripts.capability_build.intake import IntakeResult


class VerificationError(ValueError):
    """Raised when a verification plan or evidence record is unsafe."""


ALLOWED_COMMAND_KINDS = ("static", "lint", "test", "manual")
ALLOWED_EVIDENCE_STATUSES = ("passed", "failed", "blocked", "not_run")
MAX_TIMEOUT_SECONDS = 300
MAX_SUMMARY_BYTES = 2_000
MAX_OUTPUT_EXCERPT_BYTES = 8_000

_ALLOWED_TEXT_CONTROLS = {"\t", "\n", "\r"}
_SHELL_METACHARACTERS = frozenset("|;&<>`$")
_DANGEROUS_COMMAND_TOKENS = frozenset(
    {
        "bash",
        "cp",
        "curl",
        "fish",
        "git",
        "mv",
        "rm",
        "scp",
        "sh",
        "ssh",
        "wget",
        "zsh",
    }
)
_KIND_ORDER = {
    "static": 0,
    "lint": 1,
    "test": 2,
    "manual": 3,
}


def _has_disallowed_control(value: str, *, allow_output: bool) -> bool:
    for character in value:
        if unicodedata.category(character) != "Cc":
            continue
        if allow_output and character in _ALLOWED_TEXT_CONTROLS:
            continue
        return True
    return False


def _required_text(
    value: Any,
    field_name: str,
    *,
    max_bytes: int = MAX_SUMMARY_BYTES,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerificationError(f"{field_name} must be nonblank text")
    normalized = value.strip()
    if _has_disallowed_control(normalized, allow_output=True):
        raise VerificationError(f"{field_name} contains control characters")
    if len(normalized.encode("utf-8")) > max_bytes:
        raise VerificationError(f"{field_name} exceeds {max_bytes} bytes")
    return normalized


def _sequence(values: Any, field_name: str) -> tuple:
    if isinstance(values, (str, bytes)):
        raise VerificationError(f"{field_name} must be a sequence")
    try:
        return tuple(values)
    except TypeError as error:
        raise VerificationError(f"{field_name} must be a sequence") from error


def _command_token(value: str) -> str:
    forward_slash_value = "/".join(value.split("\\"))
    return forward_slash_value.rstrip("/").rsplit("/", 1)[-1].casefold()


def _is_python_executable(value: str) -> bool:
    token = _command_token(value)
    if token == "python":
        return True
    if not token.startswith("python"):
        return False
    suffix = token[len("python"):]
    return bool(suffix) and all(
        character.isdigit() or character == "." for character in suffix
    )


@dataclass(frozen=True)
class VerificationCommand:
    """One inert, argv-based verification command specification."""

    name: str
    argv: tuple
    kind: str
    expected: Optional[str] = None
    timeout_seconds: int = 120
    allow_network: bool = False
    writes_allowed: bool = False

    def __post_init__(self) -> None:
        name = _required_text(self.name, "command name")
        if not isinstance(self.argv, (tuple, list)):
            raise VerificationError("argv must be a tuple or list")
        argv = tuple(self.argv)
        if not argv:
            raise VerificationError("argv cannot be empty")
        if any(not isinstance(argument, str) for argument in argv):
            raise VerificationError("argv arguments must all be strings")
        if any(not argument for argument in argv):
            raise VerificationError("argv arguments cannot be empty")
        if len(argv) == 1 and any(
            character.isspace() for character in argv[0]
        ):
            raise VerificationError(
                "a shell command string cannot replace an argv list"
            )
        for argument in argv:
            if _has_disallowed_control(argument, allow_output=False):
                raise VerificationError("argv contains control characters")
            if any(mark in argument for mark in _SHELL_METACHARACTERS):
                raise VerificationError("argv contains shell metacharacters")

        dangerous = sorted(
            {
                _command_token(argument)
                for argument in argv
                if _command_token(argument) in _DANGEROUS_COMMAND_TOKENS
            }
        )
        if dangerous:
            raise VerificationError(
                f"dangerous command token is forbidden: {dangerous[0]}"
            )
        if _is_python_executable(argv[0]) and any(
            argument == "-c"
            or (
                argument.startswith("-")
                and not argument.startswith("--")
                and "c" in argument[1:]
            )
            for argument in argv[1:]
        ):
            raise VerificationError("python -c execution is forbidden")
        if self.kind not in ALLOWED_COMMAND_KINDS:
            raise VerificationError(f"unsupported command kind: {self.kind!r}")
        if self.expected is not None:
            expected = _required_text(self.expected, "expected outcome")
        else:
            expected = None
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int)
            or not 1 <= self.timeout_seconds <= MAX_TIMEOUT_SECONDS
        ):
            raise VerificationError(
                f"timeout_seconds must be between 1 and {MAX_TIMEOUT_SECONDS}"
            )
        if self.allow_network is not False:
            raise VerificationError("network-enabled commands are forbidden")
        if self.writes_allowed is not False:
            raise VerificationError("write-enabled commands are forbidden")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "expected", expected)


def _ordered_text(values: Any, field_name: str) -> tuple:
    items = _sequence(values, field_name)
    normalized = []
    identities = set()
    for item in items:
        value = _required_text(item, field_name)
        identity = unicodedata.normalize("NFC", value).casefold()
        if identity in identities:
            raise VerificationError(f"duplicate {field_name}: {value}")
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
class VerificationPlan:
    """Deterministic verification plan derived from accepted intake."""

    commands: tuple
    touched_files: tuple
    blocking_findings: tuple = ()
    intake_accepted: bool = True

    def __post_init__(self) -> None:
        if self.intake_accepted is not True:
            raise VerificationError(
                "cannot plan verification for failed intake"
            )
        findings = _ordered_text(
            self.blocking_findings, "blocking finding"
        )
        if findings:
            raise VerificationError(
                "cannot plan verification with blocking intake findings"
            )
        touched_files = _ordered_text(self.touched_files, "touched file")
        if not touched_files:
            raise VerificationError("verification requires touched files")

        commands = _sequence(self.commands, "commands")
        if not commands:
            raise VerificationError("verification plan requires commands")
        if any(
            not isinstance(command, VerificationCommand)
            for command in commands
        ):
            raise VerificationError(
                "commands may contain only VerificationCommand values"
            )
        names = set()
        for command in commands:
            identity = command.name.casefold()
            if identity in names:
                raise VerificationError(
                    f"duplicate verification command name: {command.name}"
                )
            names.add(identity)
        stable_commands = tuple(
            sorted(
                commands,
                key=lambda command: (
                    _KIND_ORDER[command.kind],
                    command.name.casefold(),
                    command.name,
                    command.argv,
                ),
            )
        )

        object.__setattr__(self, "commands", stable_commands)
        object.__setattr__(self, "touched_files", touched_files)
        object.__setattr__(self, "blocking_findings", findings)


@dataclass(frozen=True)
class EvidenceRecord:
    """One bounded record of an externally produced verification result."""

    command_name: str
    status: str
    summary: str
    exit_code: Optional[int] = None
    output_excerpt: Optional[str] = None

    def __post_init__(self) -> None:
        command_name = _required_text(self.command_name, "command name")
        if self.status not in ALLOWED_EVIDENCE_STATUSES:
            raise VerificationError(
                f"unknown evidence status: {self.status!r}"
            )
        summary = _required_text(self.summary, "evidence summary")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool)
            or not isinstance(self.exit_code, int)
        ):
            raise VerificationError("exit_code must be an integer or None")
        if self.status == "passed" and self.exit_code not in (None, 0):
            raise VerificationError(
                "passed evidence cannot have a nonzero exit code"
            )

        excerpt = self.output_excerpt
        if excerpt is not None:
            if not isinstance(excerpt, str):
                raise VerificationError("output_excerpt must be text or None")
            if _has_disallowed_control(excerpt, allow_output=True):
                raise VerificationError(
                    "output_excerpt contains control characters"
                )
            if len(excerpt.encode("utf-8")) > MAX_OUTPUT_EXCERPT_BYTES:
                raise VerificationError(
                    "output_excerpt exceeds "
                    f"{MAX_OUTPUT_EXCERPT_BYTES} bytes"
                )

        object.__setattr__(self, "command_name", command_name)
        object.__setattr__(self, "summary", summary)


@dataclass(frozen=True)
class EvidenceBundle:
    """Deterministic evaluation of records against one verification plan."""

    plan: VerificationPlan
    records: tuple
    accepted: bool = field(init=False)
    status: str = field(init=False)
    missing_commands: tuple = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.plan, VerificationPlan):
            raise VerificationError("plan must be a VerificationPlan")
        records = _sequence(self.records, "evidence records")
        if any(not isinstance(record, EvidenceRecord) for record in records):
            raise VerificationError(
                "records may contain only EvidenceRecord values"
            )

        command_names = {command.name for command in self.plan.commands}
        records_by_name = {}
        for record in records:
            if record.command_name not in command_names:
                raise VerificationError(
                    "evidence references unknown command: "
                    f"{record.command_name}"
                )
            if record.command_name in records_by_name:
                raise VerificationError(
                    "duplicate evidence record for command: "
                    f"{record.command_name}"
                )
            records_by_name[record.command_name] = record

        stable_records = tuple(
            records_by_name[command.name]
            for command in self.plan.commands
            if command.name in records_by_name
        )
        missing = tuple(
            command.name
            for command in self.plan.commands
            if command.name not in records_by_name
        )
        statuses = {record.status for record in stable_records}
        if "blocked" in statuses:
            status = "blocked"
        elif "failed" in statuses:
            status = "failed"
        elif missing or "not_run" in statuses:
            status = "incomplete"
        elif (
            self.plan.intake_accepted
            and len(stable_records) == len(self.plan.commands)
            and statuses == {"passed"}
        ):
            status = "passed"
        else:
            status = "incomplete"

        object.__setattr__(self, "records", stable_records)
        object.__setattr__(self, "missing_commands", missing)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "accepted", status == "passed")

    def summary(self) -> str:
        """Return a stable factual summary without executing anything."""
        counts = {
            status: sum(record.status == status for record in self.records)
            for status in ALLOWED_EVIDENCE_STATUSES
        }
        missing = ",".join(self.missing_commands) or "none"
        return (
            f"verification evidence: {self.status}; "
            f"passed={counts['passed']}; failed={counts['failed']}; "
            f"blocked={counts['blocked']}; not_run={counts['not_run']}; "
            f"missing={missing}"
        )


def build_default_verification_plan(
    intake_result: IntakeResult,
) -> VerificationPlan:
    """Build an inert, conservative plan from one accepted intake result."""
    if not isinstance(intake_result, IntakeResult):
        raise VerificationError("intake_result must be an IntakeResult")
    if not intake_result.accepted or intake_result.blocking_findings:
        findings = ", ".join(sorted(intake_result.blocking_findings))
        detail = f": {findings}" if findings else ""
        raise VerificationError(f"intake was not accepted{detail}")

    touched_files = tuple(intake_result.touched_files)
    python_files = tuple(
        path for path in touched_files if path.casefold().endswith(".py")
    )
    test_files = tuple(
        path
        for path in python_files
        if path.casefold().startswith("tests/")
    )
    commands = []
    if python_files:
        commands.extend(
            (
                VerificationCommand(
                    name="python-syntax",
                    argv=("python3", "-m", "py_compile", *python_files),
                    kind="static",
                    expected="Every touched Python file compiles.",
                    timeout_seconds=60,
                ),
                VerificationCommand(
                    name="blocking-python-lint",
                    argv=(
                        "python3",
                        "-m",
                        "flake8",
                        *python_files,
                        "--select=E9,F63,F7,F82",
                    ),
                    kind="lint",
                    expected="No blocking Python lint findings.",
                    timeout_seconds=120,
                ),
            )
        )
        pytest_targets = test_files or ("tests",)
        commands.append(
            VerificationCommand(
                name="targeted-tests" if test_files else "repository-tests",
                argv=("python3", "-m", "pytest", *pytest_targets, "-q"),
                kind="test",
                expected="The selected pytest suite passes.",
                timeout_seconds=MAX_TIMEOUT_SECONDS,
            )
        )
    else:
        commands.append(
            VerificationCommand(
                name="manual-non-python-review",
                argv=("manual-review", *touched_files),
                kind="manual",
                expected="Every touched non-Python file is reviewed.",
                timeout_seconds=60,
            )
        )

    return VerificationPlan(
        commands=tuple(commands),
        touched_files=touched_files,
        blocking_findings=tuple(intake_result.blocking_findings),
        intake_accepted=intake_result.accepted,
    )


def evaluate_evidence(
    plan: VerificationPlan,
    evidence_records: Iterable[EvidenceRecord],
) -> EvidenceBundle:
    """Evaluate supplied evidence records without running their commands."""
    return EvidenceBundle(plan=plan, records=tuple(evidence_records))
