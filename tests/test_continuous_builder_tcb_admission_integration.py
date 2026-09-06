"""CB-027D integration: TCB admission inside verifier_core path gate."""

import base64
import hashlib
import json

import backend.continuous_builder.artifact_output as artifact_output
import backend.continuous_builder.worker_artifact as worker_artifact
from backend.continuous_builder.artifact_output import (
    bridge_execution_stdout_to_artifact_intake,
)
from backend.continuous_builder.trusted_policy_enforcement import (
    ADMISSION_REVIEW,
    admit_changed_paths_against_tcb,
)
from backend.continuous_builder.verifier_core import (
    STATUS_FAILED,
    STATUS_PASSED,
    create_trusted_candidate_contract,
    verify_candidate_structure,
)
from tests.test_continuous_builder_worker_runtime import (
    FakeDocker,
    _execute,
    _foundation,
)


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _stdout(foundation, artifacts):
    body = {
        "artifacts": [
            {
                "content_base64": base64.b64encode(content).decode("ascii"),
                "content_sha256": _digest(content),
                "path": path,
            }
            for path, content in sorted(artifacts.items())
        ],
        "attempt_id": foundation.attempt_id,
        "protocol": "mootos-artifact-output-v1",
        "request_digest": foundation.request_digest,
        "result_verified": False,
    }
    return json.dumps(
        body, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"


def _candidate(tmp_path, monkeypatch, artifacts):
    foundation = _foundation()
    receipt, _ = _execute(
        tmp_path,
        monkeypatch,
        foundation=foundation,
        fake=FakeDocker(logs=_stdout(foundation, artifacts)),
    )
    intake_root = tmp_path / "artifact-intake"
    intake_root.mkdir(mode=0o700)
    monkeypatch.setattr(artifact_output, "ARTIFACT_INTAKE_ROOT", intake_root)
    monkeypatch.setattr(worker_artifact, "ARTIFACT_INTAKE_ROOT", intake_root)
    bridge = bridge_execution_stdout_to_artifact_intake(receipt)
    return foundation, receipt, bridge.intake_result


def test_ordinary_candidate_still_passes_structural(tmp_path, monkeypatch):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    contract = create_trusted_candidate_contract(
        contract_id="ordinary-tcb",
        slice_digest=_digest(b"slice-ordinary"),
        pinned_base_sha=receipt.materialization_receipt.pinned_base_sha,
        worker_request_digest=receipt.request_digest,
        base_files={
            "app.py": b"VALUE = 1\n",
            "tests/test_app.py": b"def test_value():\n    assert True\n",
        },
        allowed_paths=("app.py",),
        required_changed_paths=("app.py",),
        protected_paths=(),
    )
    result = verify_candidate_structure(contract, receipt, intake)
    assert result.status == STATUS_PASSED
    assert result.failure_codes == ()


def test_touching_verifier_core_intercepted_even_if_allowed(
    tmp_path, monkeypatch,
):
    path = "backend/continuous_builder/verifier_core.py"
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {path: b"worker-modified\n"}
    )
    contract = create_trusted_candidate_contract(
        contract_id="tcb-bypass-attempt",
        slice_digest=_digest(b"slice-bypass"),
        pinned_base_sha=receipt.materialization_receipt.pinned_base_sha,
        worker_request_digest=receipt.request_digest,
        base_files={path: b"trusted-original\n"},
        allowed_paths=(path,),
        required_changed_paths=(path,),
        protected_paths=(),
    )
    result = verify_candidate_structure(contract, receipt, intake)
    assert result.status == STATUS_FAILED
    assert "tcb_protected_change_requires_review" in result.failure_codes


def test_touching_adversarial_verifier_intercepted(tmp_path, monkeypatch):
    path = "backend/continuous_builder/adversarial_verifier.py"
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {path: b"mutated\n"}
    )
    contract = create_trusted_candidate_contract(
        contract_id="adv-tcb",
        slice_digest=_digest(b"slice-adv"),
        pinned_base_sha=receipt.materialization_receipt.pinned_base_sha,
        worker_request_digest=receipt.request_digest,
        base_files={path: b"original\n"},
        allowed_paths=(path,),
        required_changed_paths=(path,),
        protected_paths=(),
    )
    result = verify_candidate_structure(contract, receipt, intake)
    assert result.status == STATUS_FAILED
    assert "tcb_protected_change_requires_review" in result.failure_codes


def test_touching_trusted_policy_forbidden(tmp_path, monkeypatch):
    path = "backend/continuous_builder/trusted_policy.py"
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {path: b"mutated\n"}
    )
    contract = create_trusted_candidate_contract(
        contract_id="policy-tcb",
        slice_digest=_digest(b"slice-policy"),
        pinned_base_sha=receipt.materialization_receipt.pinned_base_sha,
        worker_request_digest=receipt.request_digest,
        base_files={path: b"original\n"},
        allowed_paths=(path,),
        required_changed_paths=(path,),
        protected_paths=(),
    )
    result = verify_candidate_structure(contract, receipt, intake)
    assert result.status == STATUS_FAILED
    assert "tcb_protected_change_forbidden" in result.failure_codes


def test_mixed_ordinary_and_tcb_intercepted(tmp_path, monkeypatch):
    tcb = "backend/continuous_builder/verifier_core.py"
    foundation, receipt, intake = _candidate(
        tmp_path,
        monkeypatch,
        {"app.py": b"VALUE = 2\n", tcb: b"mutated\n"},
    )
    contract = create_trusted_candidate_contract(
        contract_id="mixed-tcb",
        slice_digest=_digest(b"slice-mixed"),
        pinned_base_sha=receipt.materialization_receipt.pinned_base_sha,
        worker_request_digest=receipt.request_digest,
        base_files={
            "app.py": b"VALUE = 1\n",
            tcb: b"orig\n",
        },
        allowed_paths=("app.py", tcb),
        required_changed_paths=("app.py",),
        protected_paths=(),
    )
    result = verify_candidate_structure(contract, receipt, intake)
    assert result.status == STATUS_FAILED
    assert "tcb_protected_change_requires_review" in result.failure_codes


def test_admission_helper_matches_verifier_outcome():
    admission = admit_changed_paths_against_tcb(
        ("backend/continuous_builder/verifier_core.py",),
        candidate_digest="99" * 32,
    )
    assert admission.status == ADMISSION_REVIEW
    assert admission.authorized is False
