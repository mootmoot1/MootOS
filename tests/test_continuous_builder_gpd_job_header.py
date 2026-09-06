"""Focused tests for GP-D1 Durable Job Header."""

import pytest

from backend.continuous_builder.gpa_eval_schema import AUTHORITY_FLAGS
from backend.continuous_builder.gpd_job_header import (
    JobHeaderError,
    create_durable_job_header,
    header_ceilings_cannot_widen,
    job_header_is_control_plane_only,
)

DIGEST = "a" * 64
BASE = "48233394d4ccce88244adc5c7133efea92df60fb"
TS = "2026-09-06T22:00:00+00:00"


def _header(**overrides):
    values = dict(
        job_id="job_gpd_001",
        repository_identity="mootmoot1/MootOS",
        base_sha=BASE,
        task_contract_id="tc_gpd_001",
        task_contract_sha256=DIGEST,
        execution_plan_id="plan_gpd_001",
        execution_plan_sha256=DIGEST,
        admission_decision_id="gpc_decision_001",
        admission_decision_sha256=DIGEST,
        architecture_baseline_sha256=DIGEST,
        trusted_policy_version="cb-trusted-policy-tcb-v1",
        tcb_registry_sha256=DIGEST,
        tcb_snapshot_sha256=DIGEST,
        approved_scope_ceiling=(
            "tests/fixtures/gpa_eval/nb_001/widget_counter.py",
        ),
        forbidden_scope=("backend/continuous_builder/trusted_policy.py",),
        admitted_capability_ids=("cb.repo.read",),
        budget_ceiling_wall_clock_seconds=600,
        budget_ceiling_input_tokens=10000,
        budget_ceiling_output_tokens=10000,
        budget_ceiling_cost_usd_cents=100,
        required_gates=("human_review", "unit_tests"),
        logical_order=1,
        created_at=TS,
    )
    values.update(overrides)
    return create_durable_job_header(**values)


def test_deterministic_header_digest():
    assert _header().header_sha256 == _header().header_sha256


def test_zero_authority_flags():
    h = _header()
    for name in AUTHORITY_FLAGS:
        assert getattr(h, name) is False
    assert h.execution_authorized is False
    assert h.recovery_may_widen_scope is False
    assert job_header_is_control_plane_only() is True


def test_cannot_claim_execution_authority():
    # Factory forces authority false; sealed object rejects True flags.
    h = _header()
    assert h.execution_authorized is False
    assert h.provider_launch_authorized is False
    assert h.merge_authorized is False


def test_ceilings_identical_only():
    a = _header()
    b = _header()
    assert header_ceilings_cannot_widen(a, b) is True
    c = _header(job_id="job_gpd_002")
    assert header_ceilings_cannot_widen(a, c) is False


def test_malformed_job_id_rejected():
    with pytest.raises(Exception):
        _header(job_id="BAD ID")
