"""CB-027F phase integration proof across Cases A–H."""

import base64
import hashlib
import json

import backend.continuous_builder.artifact_output as artifact_output
import backend.continuous_builder.worker_artifact as worker_artifact
from backend.continuous_builder.artifact_output import (
    bridge_execution_stdout_to_artifact_intake,
)
from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
)
from backend.continuous_builder.trusted_policy_enforcement import (
    ADMISSION_REVIEW,
    ADMISSION_STALE_RECEIPT,
    AUTHORITY_FLAGS,
    OUTCOME_FORBIDDEN,
    OUTCOME_MALFORMED,
    OUTCOME_ORDINARY,
    OUTCOME_REVIEW,
    admit_changed_paths_against_tcb,
    create_trusted_policy_decision_receipt,
    evaluate_changed_paths_against_tcb,
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


def _assert_zero_authority(obj):
    for flag in AUTHORITY_FLAGS:
        assert getattr(obj, flag) is False


# Case A — ordinary safe
def test_case_a_ordinary_safe(tmp_path, monkeypatch):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    contract = create_trusted_candidate_contract(
        contract_id="cb027f-a",
        slice_digest=_digest(b"cb027f-a"),
        pinned_base_sha=receipt.materialization_receipt.pinned_base_sha,
        worker_request_digest=receipt.request_digest,
        base_files={"app.py": b"VALUE = 1\n"},
        allowed_paths=("app.py",),
        required_changed_paths=("app.py",),
        protected_paths=(),
    )
    result = verify_candidate_structure(contract, receipt, intake)
    assert result.status == STATUS_PASSED
    decision = evaluate_changed_paths_against_tcb(("app.py",))
    assert decision.outcome == OUTCOME_ORDINARY
    _assert_zero_authority(decision)
    _assert_zero_authority(result)


# Case B — protected verifier_core
def test_case_b_protected_verifier_core(tmp_path, monkeypatch):
    path = "backend/continuous_builder/verifier_core.py"
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {path: b"mutated\n"}
    )
    contract = create_trusted_candidate_contract(
        contract_id="cb027f-b",
        slice_digest=_digest(b"cb027f-b"),
        pinned_base_sha=receipt.materialization_receipt.pinned_base_sha,
        worker_request_digest=receipt.request_digest,
        base_files={path: b"orig\n"},
        allowed_paths=(path,),
        required_changed_paths=(path,),
        protected_paths=(),
    )
    result = verify_candidate_structure(contract, receipt, intake)
    assert result.status == STATUS_FAILED
    assert "tcb_protected_change_requires_review" in result.failure_codes
    decision = evaluate_changed_paths_against_tcb((path,))
    assert decision.outcome == OUTCOME_REVIEW


# Case C — adversarial_verifier
def test_case_c_adversarial_verifier(tmp_path, monkeypatch):
    path = "backend/continuous_builder/adversarial_verifier.py"
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {path: b"mutated\n"}
    )
    contract = create_trusted_candidate_contract(
        contract_id="cb027f-c",
        slice_digest=_digest(b"cb027f-c"),
        pinned_base_sha=receipt.materialization_receipt.pinned_base_sha,
        worker_request_digest=receipt.request_digest,
        base_files={path: b"orig\n"},
        allowed_paths=(path,),
        required_changed_paths=(path,),
        protected_paths=(),
    )
    result = verify_candidate_structure(contract, receipt, intake)
    assert result.status == STATUS_FAILED
    assert "tcb_protected_change_requires_review" in result.failure_codes


# Case D — trusted_policy self-mod
def test_case_d_trusted_policy_self_mod(tmp_path, monkeypatch):
    path = "backend/continuous_builder/trusted_policy.py"
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {path: b"mutated\n"}
    )
    contract = create_trusted_candidate_contract(
        contract_id="cb027f-d",
        slice_digest=_digest(b"cb027f-d"),
        pinned_base_sha=receipt.materialization_receipt.pinned_base_sha,
        worker_request_digest=receipt.request_digest,
        base_files={path: b"orig\n"},
        allowed_paths=(path,),
        required_changed_paths=(path,),
        protected_paths=(),
    )
    result = verify_candidate_structure(contract, receipt, intake)
    assert result.status == STATUS_FAILED
    assert "tcb_protected_change_forbidden" in result.failure_codes
    decision = evaluate_changed_paths_against_tcb((path,))
    assert decision.outcome == OUTCOME_FORBIDDEN


# Case E — malformed bypass
def test_case_e_malformed_bypass():
    for path in (
        "../secrets.txt",
        "/etc/passwd",
        "backend/continuous_builder/./verifier_core.py",
        r"backend\memory.py",
    ):
        decision = evaluate_changed_paths_against_tcb((path,))
        assert decision.outcome == OUTCOME_MALFORMED
        admission = admit_changed_paths_against_tcb((path,))
        assert admission.allows_continuation is False
        _assert_zero_authority(decision)


# Case F — replay / identity mismatch
def test_case_f_replay_identity_mismatch():
    prior = create_trusted_policy_decision_receipt(
        evaluate_changed_paths_against_tcb(("backend/memory.py",)),
        candidate_digest="aa" * 32,
        worker_request_digest="bb" * 32,
    )
    stale = admit_changed_paths_against_tcb(
        ("backend/memory.py",),
        candidate_digest="cc" * 32,
        worker_request_digest="bb" * 32,
        prior_receipt=prior,
    )
    assert stale.status == ADMISSION_STALE_RECEIPT
    mismatch = admit_changed_paths_against_tcb(
        ("backend/continuous_builder/verifier_core.py",),
        worker_declared_paths=("backend/memory.py",),
    )
    assert mismatch.allows_continuation is False


# Case G — mixed (protected wins)
def test_case_g_mixed_protected_wins(tmp_path, monkeypatch):
    tcb = "backend/continuous_builder/verifier_core.py"
    foundation, receipt, intake = _candidate(
        tmp_path,
        monkeypatch,
        {"app.py": b"VALUE = 2\n", tcb: b"mutated\n"},
    )
    contract = create_trusted_candidate_contract(
        contract_id="cb027f-g",
        slice_digest=_digest(b"cb027f-g"),
        pinned_base_sha=receipt.materialization_receipt.pinned_base_sha,
        worker_request_digest=receipt.request_digest,
        base_files={"app.py": b"VALUE = 1\n", tcb: b"orig\n"},
        allowed_paths=("app.py", tcb),
        required_changed_paths=("app.py",),
        protected_paths=(),
    )
    result = verify_candidate_structure(contract, receipt, intake)
    assert result.status == STATUS_FAILED
    assert "tcb_protected_change_requires_review" in result.failure_codes
    decision = evaluate_changed_paths_against_tcb(("app.py", tcb))
    assert decision.outcome == OUTCOME_REVIEW
    admission = admit_changed_paths_against_tcb(("app.py", tcb))
    assert admission.status == ADMISSION_REVIEW


# Case H — authority check all false across phase outputs
def test_case_h_authority_all_false_across_phase_outputs():
    registry = create_mootos_tcb_registry_v1()
    ordinary = evaluate_changed_paths_against_tcb(("backend/memory.py",))
    protected = evaluate_changed_paths_against_tcb(
        ("backend/continuous_builder/verifier_core.py",)
    )
    forbidden = evaluate_changed_paths_against_tcb(
        ("backend/continuous_builder/trusted_policy.py",)
    )
    receipt = create_trusted_policy_decision_receipt(protected)
    admission = admit_changed_paths_against_tcb(
        ("backend/continuous_builder/verifier_core.py",),
        candidate_digest="ee" * 32,
    )
    for obj in (ordinary, protected, forbidden, receipt, admission):
        _assert_zero_authority(obj)
    assert admission.authorized is False
    # Registry snapshot authority flags (from CB-027A) remain false.
    from backend.continuous_builder.trusted_policy import (
        AUTHORITY_FLAGS as SNAP_FLAGS,
        create_trusted_policy_snapshot,
    )
    snapshot = create_trusted_policy_snapshot()
    for flag in SNAP_FLAGS:
        assert getattr(snapshot, flag) is False
    assert registry.registry_sha256 == (
        "989f05d88ef634c980c2d65250cb3afcee69cdd8867f9c8a4909f00b63c9a837"
    )
    assert len(registry.protected_paths) == 19
