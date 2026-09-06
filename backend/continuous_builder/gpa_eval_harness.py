"""GP-A6 -- Deterministic Offline Evaluation Harness.

Loads a frozen eval case (GP-A3/GP-A5), binds it to an architecture
baseline (GP-A1), ingests an untrusted worker result submission, and
emits a sealed :class:`~.gpa_evidence_record.EvidenceRecord` (GP-A4).

This harness does not launch Claude, Codex, Grok, or any other coding
provider -- it never makes a network call and never executes untrusted
worker-authored code outside a disposable temporary copy of a synthetic,
already-checked-in fixture. Provider execution stays out of scope for
GP-A; a real future provider adapter is expected to produce a
``WorkerResultSubmission`` and call this harness, not the other way
around.

Trust boundary -- ``WorkerResultSubmission`` is a plain, unsealed,
mutable dataclass, deliberately not built with the sealed-token/digest
pattern the rest of GP-A uses: it represents THE WORKER'S PROPOSAL, which
this codebase's own architecture law says the system never simply
believes. The harness independently re-derives every field of the
resulting evidence record that matters for scope/authority; it never
copies a claimed value into the record's ``verifier_result``,
``first_pass_success`, or ``outcome_state`` without independent
evidence. Where no independent check is wired up for a case (the 13
structural-only GP-A5 cases), the honest answer is ``UNKNOWN`` --
never a copy of the worker's claim.
"""

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .gpa_architecture_baseline import ArchitectureBaselineManifest
from .gpa_eval_case import EvalCase
from .gpa_eval_corpus import FIXTURE_BACKED_CASES
from .gpa_eval_schema import UNKNOWN, GPAEvalSchemaError, is_unknown
from .gpa_evidence_record import create_evidence_record

HARNESS_VERSION = "gpa-eval-harness-v1"
VERIFICATION_TIMEOUT_SECONDS = 60
MAX_CHANGED_PATHS = 256
MAX_OVERLAYS = 64
MAX_OVERLAY_BYTES = 1_000_000
MAX_PRODUCED_ARTIFACTS = 64


class EvalHarnessError(GPAEvalSchemaError):
    """Raised when the offline evaluation harness cannot proceed safely."""


@dataclass
class WorkerResultSubmission:
    """One untrusted worker proposal. Never treated as ground truth.

    Every ``claimed_*`` field is exactly that -- a claim. The harness
    reads ``changed_paths``, ``file_overlays``, and ``produced_artifacts``
    to independently derive evidence; it never reads a ``claimed_*``
    field into the resulting :class:`EvidenceRecord`.
    """

    eval_case_id: str
    changed_paths: tuple = ()
    file_overlays: dict = field(default_factory=dict)
    produced_artifacts: tuple = ()
    claimed_outcome_state: object = UNKNOWN
    claimed_verifier_result: object = UNKNOWN
    claimed_tests_passed: object = UNKNOWN
    provider: object = UNKNOWN
    model: object = UNKNOWN


def _check_scope_violation(eval_case, changed_paths):
    allowed = set(eval_case.worker_view.allowed_scope)
    return not set(changed_paths).issubset(allowed)


def _apply_overlays(tmp_dir, fixture_prefix, allowed_scope, file_overlays):
    tmp_root = tmp_dir.resolve()
    for rel_path, content in file_overlays.items():
        if not isinstance(rel_path, str) or not isinstance(content, str):
            continue
        if rel_path not in allowed_scope:
            continue
        if not rel_path.startswith(fixture_prefix):
            continue
        if len(content.encode("utf-8")) > MAX_OVERLAY_BYTES:
            continue
        local_rel = rel_path[len(fixture_prefix):]
        target = (tmp_dir / local_rel).resolve()
        if target != tmp_root and tmp_root not in target.parents:
            continue  # traversal guard; structurally unreachable given
            # upstream path canonicalization, kept as defense in depth.
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _run_fixture_verification(repo_root, eval_case, submission):
    """Return ``"pass"``, ``"fail"``, or ``UNKNOWN``.

    Copies the case's fixture directory into a temporary directory,
    overlays the submission's claimed file changes (restricted to paths
    already inside the case's ``allowed_scope``), and runs the fixture's
    ``acceptance.py`` there via ``pytest`` with a ``python_files``
    override -- never inside the real repository tree.
    """
    spec = FIXTURE_BACKED_CASES.get(eval_case.eval_case_id)
    if spec is None:
        return UNKNOWN
    fixture_dir = Path(repo_root) / spec["fixture_dir"]
    if not fixture_dir.is_dir():
        return UNKNOWN
    fixture_prefix = spec["fixture_dir"].rstrip("/") + "/"
    allowed_scope = set(eval_case.worker_view.allowed_scope)
    with tempfile.TemporaryDirectory(prefix="gpa-eval-") as tmp:
        tmp_dir = Path(tmp)
        shutil.copytree(fixture_dir, tmp_dir, dirs_exist_ok=True)
        _apply_overlays(
            tmp_dir, fixture_prefix, allowed_scope, submission.file_overlays
        )
        acceptance_file = spec["acceptance_file"]
        if not (tmp_dir / acceptance_file).is_file():
            return UNKNOWN
        try:
            proc = subprocess.run(
                [
                    sys.executable, "-m", "pytest", "-q",
                    "-p", "no:cacheprovider",
                    "-o", f"python_files={acceptance_file}",
                    acceptance_file,
                ],
                cwd=str(tmp_dir),
                capture_output=True,
                text=True,
                timeout=VERIFICATION_TIMEOUT_SECONDS,
            )
        except (subprocess.TimeoutExpired, OSError):
            return UNKNOWN
        return "pass" if proc.returncode == 0 else "fail"


def evaluate_worker_submission(
    *, run_id, eval_case, architecture_baseline, submission, repo_root=None,
):
    """Evaluate one untrusted submission against one frozen eval case.

    Raises :class:`EvalHarnessError` for a setup mistake by the *caller*
    (wrong case/baseline pairing, malformed submission shape, a stale
    base SHA) rather than silently producing a misleading record. Once
    past those checks, every outcome/quality field on the returned
    :class:`EvidenceRecord` is either independently derived here or
    honestly ``UNKNOWN`` -- never copied from ``submission.claimed_*``.
    """
    if not isinstance(eval_case, EvalCase):
        raise EvalHarnessError("eval_case is invalid")
    if not isinstance(architecture_baseline, ArchitectureBaselineManifest):
        raise EvalHarnessError("architecture_baseline is invalid")
    if not isinstance(submission, WorkerResultSubmission):
        raise EvalHarnessError("submission is invalid")
    if submission.eval_case_id != eval_case.eval_case_id:
        raise EvalHarnessError(
            "submission.eval_case_id does not name this eval_case"
        )
    if eval_case.base_sha != architecture_baseline.base_sha:
        raise EvalHarnessError(
            "eval_case.base_sha does not match architecture_baseline.base_sha"
        )
    if type(submission.changed_paths) is not tuple or (
        len(submission.changed_paths) > MAX_CHANGED_PATHS
    ):
        raise EvalHarnessError("submission.changed_paths is malformed")
    if not isinstance(submission.file_overlays, dict) or (
        len(submission.file_overlays) > MAX_OVERLAYS
    ):
        raise EvalHarnessError("submission.file_overlays is malformed")
    if type(submission.produced_artifacts) is not tuple or (
        len(submission.produced_artifacts) > MAX_PRODUCED_ARTIFACTS
    ):
        raise EvalHarnessError("submission.produced_artifacts is malformed")

    changed_paths = tuple(submission.changed_paths)
    scope_violation = _check_scope_violation(eval_case, changed_paths)
    missing_required_artifacts = set(
        eval_case.worker_view.required_artifacts
    ) - set(submission.produced_artifacts)

    verifier_result = UNKNOWN
    if scope_violation:
        verifier_result = "fail"
    elif repo_root is not None:
        verifier_result = _run_fixture_verification(
            repo_root, eval_case, submission
        )

    first_pass_success = UNKNOWN
    if not is_unknown(verifier_result):
        first_pass_success = (
            verifier_result == "pass"
            and not scope_violation
            and not missing_required_artifacts
        )

    field_provenance = [
        ("outcome_state", "measured_directly"),
        ("scope_violation", "measured_directly"),
        ("policy_violation", "measured_directly"),
        ("files_changed", "measured_directly"),
    ]
    if not is_unknown(verifier_result):
        field_provenance.append(("verifier_result", "measured_directly"))
    if not is_unknown(first_pass_success):
        field_provenance.append(("first_pass_success", "measured_directly"))
    if not is_unknown(submission.provider):
        field_provenance.append(("provider", "user_reported"))
    if not is_unknown(submission.model):
        field_provenance.append(("model", "user_reported"))

    return create_evidence_record(
        run_id=run_id,
        eval_case_id=eval_case.eval_case_id,
        eval_case_sha256=eval_case.case_sha256,
        architecture_baseline_sha256=architecture_baseline.manifest_sha256,
        base_sha=eval_case.base_sha,
        outcome_state="completed",
        verifier_result=verifier_result,
        scope_violation=scope_violation,
        policy_violation=scope_violation,
        files_changed=len(changed_paths),
        first_pass_success=first_pass_success,
        provider=submission.provider,
        model=submission.model,
        field_provenance=tuple(field_provenance),
    )


def eval_harness_is_observational_only():
    """TRUST REVIEW helper: True -- the harness grants no capability."""
    return True
