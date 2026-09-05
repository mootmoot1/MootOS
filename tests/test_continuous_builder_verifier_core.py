import base64
import dataclasses
import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

import backend.continuous_builder.artifact_output as artifact_output
import backend.continuous_builder.worker_artifact as worker_artifact
from backend.continuous_builder.artifact_output import (
    bridge_execution_stdout_to_artifact_intake,
)
from backend.continuous_builder.verifier_core import (
    STATUS_FAILED,
    STATUS_PASSED,
    VerifierCoreError,
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


def _contract(foundation, receipt, **overrides):
    values = {
        "contract_id": "cb026a-test-contract",
        "slice_digest": _digest(b"slice-026a"),
        "pinned_base_sha": receipt.materialization_receipt.pinned_base_sha,
        "worker_request_digest": receipt.request_digest,
        "base_files": {
            "app.py": b"VALUE = 1\n",
            "tests/test_app.py": b"def test_value():\n    assert True\n",
        },
        "allowed_paths": ("app.py",),
        "required_changed_paths": ("app.py",),
        "protected_paths": (
            "backend/continuous_builder/verifier_core.py",
            "tests/test_continuous_builder_verifier_core.py",
        ),
    }
    values.update(overrides)
    return create_trusted_candidate_contract(**values)


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def test_allowed_required_change_passes_structural_verification(
    tmp_path, monkeypatch,
):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    result = verify_candidate_structure(
        _contract(foundation, receipt), receipt, intake
    )

    assert result.status == STATUS_PASSED
    assert result.failure_codes == ()
    assert result.changed_paths == ("app.py",)
    assert result.verification_performed is True
    assert result.trusted_base_reconstructed is True
    assert result.artifact_payloads_rehashed is True
    assert result.path_boundary_enforced is True
    assert result.behavioral_checks_executed is False
    assert result.worker_workspace_reused is False
    assert result.worker_claim_considered is False
    assert result.worker_output_trusted is False
    assert result.result_trusted is False
    assert result.publication_authorized is False
    assert result.queue_transition_authorized is False
    assert result.github_authorized is False
    assert result.merge_authorized is False
    assert result.main_advancement_authorized is False


def test_unapproved_extra_file_fails_even_when_required_change_is_present(
    tmp_path, monkeypatch,
):
    foundation, receipt, intake = _candidate(
        tmp_path,
        monkeypatch,
        {
            "app.py": b"VALUE = 2\n",
            "surprise.py": b"print('extra')\n",
        },
    )
    result = verify_candidate_structure(
        _contract(foundation, receipt), receipt, intake
    )

    assert result.status == STATUS_FAILED
    assert "artifact_path_not_allowed" in result.failure_codes
    assert result.changed_paths == ("app.py", "surprise.py")


def test_protected_path_modification_fails_closed(tmp_path, monkeypatch):
    protected = "backend/continuous_builder/verifier_core.py"
    foundation, receipt, intake = _candidate(
        tmp_path,
        monkeypatch,
        {
            "app.py": b"VALUE = 2\n",
            protected: b"worker tries to rewrite referee\n",
        },
    )
    result = verify_candidate_structure(
        _contract(foundation, receipt), receipt, intake
    )

    assert result.status == STATUS_FAILED
    assert "protected_path_modified" in result.failure_codes
    assert "artifact_path_not_allowed" in result.failure_codes


def test_required_path_must_actually_change(tmp_path, monkeypatch):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 1\n"}
    )
    result = verify_candidate_structure(
        _contract(foundation, receipt), receipt, intake
    )

    assert result.status == STATUS_FAILED
    assert result.failure_codes == ("required_change_missing",)
    assert result.changed_paths == ()


def test_worker_stdout_claims_are_not_a_verifier_input(tmp_path, monkeypatch):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    # The trusted runtime receipt contains worker-authored stdout, but the
    # structural verifier accepts no stdout/claim argument and records that
    # worker claims were not considered.
    assert receipt.stdout_size > 0
    result = verify_candidate_structure(
        _contract(foundation, receipt), receipt, intake
    )
    assert result.status == STATUS_PASSED
    assert result.worker_claim_considered is False
    assert result.worker_output_trusted is False


def test_candidate_contract_binds_exact_request(tmp_path, monkeypatch):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    contract = _contract(
        foundation,
        receipt,
        worker_request_digest="0" * 64,
    )
    with pytest.raises(VerifierCoreError, match="request binding mismatch"):
        verify_candidate_structure(contract, receipt, intake)


def test_candidate_contract_binds_exact_base_sha(tmp_path, monkeypatch):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    contract = _contract(
        foundation,
        receipt,
        pinned_base_sha="0" * 40,
    )
    with pytest.raises(VerifierCoreError, match="base binding mismatch"):
        verify_candidate_structure(contract, receipt, intake)


def test_quarantine_payload_is_rehashed_not_believed(tmp_path, monkeypatch):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    forged = _forge(
        intake,
        _artifact_payloads=(("app.py", b"VALUE = 999\n"),),
    )
    result = verify_candidate_structure(
        _contract(foundation, receipt), receipt, forged
    )

    assert result.status == STATUS_FAILED
    assert "quarantine_payload_digest_mismatch" in result.failure_codes


def test_missing_quarantine_package_fails_before_verification(tmp_path, monkeypatch):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    forged = _forge(intake, quarantine_package=None)
    with pytest.raises(VerifierCoreError, match="quarantine package"):
        verify_candidate_structure(
            _contract(foundation, receipt), receipt, forged
        )


def test_contract_refuses_required_path_outside_allowlist():
    foundation = _foundation()
    with pytest.raises(VerifierCoreError, match="required paths must be allowed"):
        create_trusted_candidate_contract(
            contract_id="bad-contract",
            slice_digest=_digest(b"slice"),
            pinned_base_sha="a" * 40,
            worker_request_digest=foundation.request_digest,
            base_files={"app.py": b"VALUE = 1\n"},
            allowed_paths=("app.py",),
            required_changed_paths=("not-allowed.py",),
        )


def test_contract_refuses_protected_path_in_allowlist():
    foundation = _foundation()
    with pytest.raises(VerifierCoreError, match="protected paths cannot be allowed"):
        create_trusted_candidate_contract(
            contract_id="bad-contract",
            slice_digest=_digest(b"slice"),
            pinned_base_sha="a" * 40,
            worker_request_digest=foundation.request_digest,
            base_files={"app.py": b"VALUE = 1\n"},
            allowed_paths=("verifier.py",),
            protected_paths=("verifier.py",),
        )


def test_contract_is_immutable_and_content_addressed(tmp_path, monkeypatch):
    foundation, receipt, _ = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    contract = _contract(foundation, receipt)
    with pytest.raises(FrozenInstanceError):
        contract.allowed_paths = ()
    with pytest.raises(VerifierCoreError, match="contract digest mismatch"):
        dataclasses.replace(contract, contract_sha256="0" * 64)


def test_receipt_is_immutable_and_rejects_authority_promotion(
    tmp_path, monkeypatch,
):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    result = verify_candidate_structure(
        _contract(foundation, receipt), receipt, intake
    )
    with pytest.raises(FrozenInstanceError):
        result.merge_authorized = True
    with pytest.raises(VerifierCoreError, match="promotes authority"):
        dataclasses.replace(
            result,
            merge_authorized=True,
            receipt_sha256=result.receipt_sha256,
        )


def test_receipt_digest_detects_forgery(tmp_path, monkeypatch):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    result = verify_candidate_structure(
        _contract(foundation, receipt), receipt, intake
    )
    with pytest.raises(VerifierCoreError, match="receipt digest mismatch"):
        dataclasses.replace(
            result,
            candidate_tree_sha256="0" * 64,
            receipt_sha256=result.receipt_sha256,
        )


def test_same_inputs_produce_same_candidate_and_receipt_identity(
    tmp_path, monkeypatch,
):
    foundation, receipt, intake = _candidate(
        tmp_path, monkeypatch, {"app.py": b"VALUE = 2\n"}
    )
    contract = _contract(foundation, receipt)
    first = verify_candidate_structure(contract, receipt, intake)
    second = verify_candidate_structure(contract, receipt, intake)

    assert first.candidate_tree_sha256 == second.candidate_tree_sha256
    assert first.receipt_sha256 == second.receipt_sha256
