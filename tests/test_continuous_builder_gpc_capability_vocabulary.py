"""Focused tests for GP-C1 capability vocabulary / request contract."""

import pytest

from backend.continuous_builder.gpa_eval_schema import AUTHORITY_FLAGS
from backend.continuous_builder.gpc_capability_vocabulary import (
    CAPABILITY_IDS,
    HUMAN_GATED_CAPABILITY_IDS,
    OUTCOME_INSUFFICIENT_EVIDENCE,
    CapabilityVocabularyError,
    capability_request_has_zero_authority,
    create_capability_request,
    create_gpc_capability_vocabulary_v1,
    default_outcome_for_capability,
    is_known_capability_id,
)


def test_vocabulary_sealed_complete_and_zero_authority():
    vocab = create_gpc_capability_vocabulary_v1()
    assert set(c.capability_id for c in vocab.capabilities) == CAPABILITY_IDS
    for name in AUTHORITY_FLAGS:
        assert getattr(vocab, name) is False
    assert vocab.execution_authorized is False
    assert create_gpc_capability_vocabulary_v1().vocabulary_sha256 == (
        vocab.vocabulary_sha256
    )


def test_unknown_capability_never_grants_default():
    assert not is_known_capability_id("cb.invented.power")
    assert (
        default_outcome_for_capability("cb.invented.power")
        == OUTCOME_INSUFFICIENT_EVIDENCE
    )


def test_request_zero_authority_and_human_gate_autoflag():
    req = create_capability_request(
        request_id="req_main_merge_001",
        capability_id="cb.main.merge",
        task_contract_id="tc_demo_001",
        contract_sha256="a" * 64,
        plan_id="plan_demo_001",
        plan_sha256="b" * 64,
        requested_scope=("backend/continuous_builder/gpb_task_contract.py",),
        human_gate_requested=False,
    )
    assert req.human_gate_requested is True
    assert req.capability_granted is False
    assert req.execution_authorized is False
    for name in AUTHORITY_FLAGS:
        assert getattr(req, name) is False
    assert capability_request_has_zero_authority() is True
    assert "cb.main.merge" in HUMAN_GATED_CAPABILITY_IDS


def test_request_rejects_forged_digest():
    import dataclasses
    req = create_capability_request(
        request_id="req_read_001",
        capability_id="cb.repo.read",
        task_contract_id="tc_demo_001",
        contract_sha256="a" * 64,
        plan_id="plan_demo_001",
        plan_sha256="b" * 64,
    )
    forged = object.__new__(type(req))
    for item in dataclasses.fields(req):
        value = "c" * 64 if item.name == "request_sha256" else getattr(req, item.name)
        object.__setattr__(forged, item.name, value)
    with pytest.raises(CapabilityVocabularyError, match="request_sha256"):
        type(req)(
            **{
                f.name: getattr(forged, f.name)
                for f in dataclasses.fields(req)
                if f.name != "_token"
            },
            _token=req._token,
        )


def test_provider_model_benchmark_fields_never_authority():
    req = create_capability_request(
        request_id="req_write_001",
        capability_id="cb.file.write_bounded",
        task_contract_id="tc_demo_001",
        contract_sha256="a" * 64,
        plan_id="plan_demo_001",
        plan_sha256="b" * 64,
        requested_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        worker_safe_claim=True,
        provider_id="claude",
        model_id="opus",
        benchmark_score=99.9,
    )
    assert req.capability_granted is False
    assert req.worker_safe_claim is True
