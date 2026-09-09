"""Focused tests for GP-C trusted admission core: closure + fail-closed."""

import ast
import importlib
import sys
from pathlib import Path

import pytest

from backend.continuous_builder.gpc_trusted_admission_core import (
    OUTCOME_ALLOW_WITHIN_BOUND,
    OUTCOME_DENY,
    OUTCOME_ESCALATE,
    OUTCOME_INSUFFICIENT_EVIDENCE,
    OUTCOME_REQUIRE_HUMAN_APPROVAL,
    TrustedAdmissionError,
    admit_from_trusted_facts,
    admission_decision_cannot_execute,
    admission_never_auto_approves_main_merge,
    create_gpc_policy_matrix_v1,
    seal_trusted_admission_facts,
    seal_trusted_request_fact,
)
from backend.continuous_builder.trusted_policy import (
    POLICY_VERSION,
    REGISTRY_VERSION,
    create_mootos_tcb_registry_v1,
    create_trusted_policy_snapshot,
)

REPO = Path(__file__).resolve().parents[1]
CORE_MOD = "backend.continuous_builder.gpc_trusted_admission_core"
FORBIDDEN_ROOTS = (
    "backend.continuous_builder.gpb_decomposer",
    "backend.continuous_builder.gpb_task_contract",
    "backend.continuous_builder.gpb_decomposition_node",
    "backend.continuous_builder.gpb_scope_rules",
    "backend.continuous_builder.gpb_impact_evidence",
    "backend.continuous_builder.system_model",
    "backend.continuous_builder.context_engine",
    "backend.continuous_builder.gpa_architecture_baseline",
    "backend.continuous_builder.gpc_eval_corpus",
    "backend.continuous_builder.gpc_admission_input",
    "backend.continuous_builder.gpa_eval_schema",
)


def _live_tcb():
    registry = create_mootos_tcb_registry_v1()
    snapshot = create_trusted_policy_snapshot()
    return registry, snapshot


def _request(**overrides):
    values = dict(
        request_id="req_core_001",
        capability_id="cb.repo.read",
        request_sha256="a" * 64,
        requested_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        budget_wall_clock_seconds=100,
        budget_input_tokens=100,
        budget_output_tokens=100,
        evidence_refs=(),
        human_gate_requested=False,
        worker_safe_claim=False,
        provider_id=None,
        model_id=None,
        benchmark_score=None,
    )
    values.update(overrides)
    return seal_trusted_request_fact(**values)


def _facts(**overrides):
    registry, snapshot = _live_tcb()
    values = dict(
        facts_id="facts_core_001",
        task_contract_id="tc_core_001",
        contract_sha256="b" * 64,
        plan_id="plan_core_001",
        plan_sha256="c" * 64,
        base_sha="33f7fe0cf24f1e5871d4b2950086730a6112b99b",
        architecture_baseline_sha256="d" * 64,
        allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
        forbidden_scope=("backend/continuous_builder/trusted_policy.py",),
        required_gates=("unit_tests", "human_review"),
        risk_ceiling_indicators=("none",),
        budget_ceiling_wall_clock_seconds=600,
        budget_ceiling_input_tokens=10000,
        budget_ceiling_output_tokens=10000,
        budget_ceiling_cost_usd_cents=None,
        plan_requires_escalation=False,
        plan_escalation_reasons=(),
        system_model_sha256=None,
        system_model_version=None,
        expected_system_model_sha256=None,
        trusted_policy_version=POLICY_VERSION,
        tcb_registry_version=REGISTRY_VERSION,
        tcb_registry_sha256=registry.registry_sha256,
        tcb_protected_path_count=len(registry.protected_paths),
        tcb_snapshot_sha256=snapshot.snapshot_sha256,
        vocabulary_version="gpc-capability-vocabulary-v1",
        vocabulary_sha256="e" * 64,
        evidence_digests=(),
        capability_requests=(_request(),),
    )
    values.update(overrides)
    return seal_trusted_admission_facts(**values)


def _module_deps(module_name):
    """Return transitive imported module names reachable from module_name."""
    seen = set()
    stack = [module_name]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        mod = sys.modules.get(name)
        if mod is None:
            try:
                mod = importlib.import_module(name)
            except Exception:
                continue
        for value in vars(mod).values():
            other = getattr(value, "__module__", None)
            if isinstance(other, str) and other.startswith("backend."):
                if other not in seen:
                    stack.append(other)
        # also walk sys.modules children imported while loading
        prefix = name + "."
        for loaded in list(sys.modules):
            if loaded.startswith(prefix) and loaded not in seen:
                stack.append(loaded)
    return seen


def test_mechanical_import_closure_forbids_gpb_sm_ce():
    # Fresh import analysis via AST of the core file + static import graph.
    core_path = (
        REPO
        / "backend"
        / "continuous_builder"
        / "gpc_trusted_admission_core.py"
    )
    tree = ast.parse(core_path.read_text(encoding="utf-8"))
    direct = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                direct.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                if node.level:
                    # relative: .trusted_policy -> backend.continuous_builder.trusted_policy
                    pkg = "backend.continuous_builder"
                    direct.add(f"{pkg}.{node.module}" if node.module != "trusted_policy" else f"{pkg}.trusted_policy")
                    if node.module:
                        direct.add(f"backend.continuous_builder.{node.module}")
                else:
                    direct.add(node.module)
    # Normalize relative imports from the file
    direct_norm = set()
    for item in direct:
        if item.startswith("."):
            direct_norm.add("backend.continuous_builder" + item)
        else:
            direct_norm.add(item)
    # Re-parse relative imports properly
    direct = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level and node.module:
                direct.add(f"backend.continuous_builder.{node.module}")
            elif node.level and not node.module:
                direct.add("backend.continuous_builder")
            elif node.module:
                direct.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                direct.add(alias.name)
    assert "backend.continuous_builder.trusted_policy" in direct
    for forbidden in FORBIDDEN_ROOTS:
        assert forbidden not in direct

    # Do NOT reload the core module here: reload would replace exception
    # classes and break later pytest.raises identity checks in this process.
    core = sys.modules.get(CORE_MOD) or importlib.import_module(CORE_MOD)
    for value in vars(core).values():
        modname = getattr(value, "__module__", "") or ""
        assert not any(
            modname == f or modname.startswith(f + ".")
            for f in FORBIDDEN_ROOTS
        )


def test_direct_imports_are_stdlib_and_trusted_policy_only():
    core_path = (
        REPO
        / "backend"
        / "continuous_builder"
        / "gpc_trusted_admission_core.py"
    )
    tree = ast.parse(core_path.read_text(encoding="utf-8"))
    third_party = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level and node.module:
            third_party.append(node.module)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            if node.module.split(".")[0] not in {
                "hashlib",
                "json",
                "re",
                "dataclasses",
                "typing",
                "__future__",
            }:
                third_party.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in {"hashlib", "json", "re", "dataclasses", "typing"}:
                    third_party.append(alias.name)
    assert third_party == ["trusted_policy"]


def test_unknown_capability_never_allow():
    facts = _facts(
        capability_requests=(
            _request(
                request_id="req_unk",
                capability_id="cb.invented.superuser",
                requested_scope=(),
            ),
        )
    )
    decision, _ = admit_from_trusted_facts(facts)
    assert decision.overall_outcome == OUTCOME_INSUFFICIENT_EVIDENCE
    assert "cb.invented.superuser" not in decision.admitted_within_bound


def test_malformed_facts_fail_closed():
    req = _request()
    with pytest.raises(TrustedAdmissionError):
        seal_trusted_admission_facts(
            facts_id="facts_bad_001",
            task_contract_id="tc_bad_001",
            contract_sha256="not-a-digest",
            plan_id="plan_bad_001",
            plan_sha256="c" * 64,
            base_sha="33f7fe0",
            architecture_baseline_sha256="d" * 64,
            allowed_scope=("tests/fixtures/gpa_eval/nb_001/widget_counter.py",),
            forbidden_scope=(),
            required_gates=(),
            risk_ceiling_indicators=(),
            budget_ceiling_wall_clock_seconds=1,
            budget_ceiling_input_tokens=1,
            budget_ceiling_output_tokens=1,
            budget_ceiling_cost_usd_cents=None,
            plan_requires_escalation=False,
            plan_escalation_reasons=(),
            system_model_sha256=None,
            system_model_version=None,
            expected_system_model_sha256=None,
            trusted_policy_version=POLICY_VERSION,
            tcb_registry_version=REGISTRY_VERSION,
            tcb_registry_sha256="a" * 64,
            tcb_protected_path_count=1,
            tcb_snapshot_sha256="b" * 64,
            vocabulary_version="gpc-capability-vocabulary-v1",
            vocabulary_sha256="e" * 64,
            evidence_digests=(),
            capability_requests=(req,),
        )


def test_stale_tcb_digest_rejected():
    registry, snapshot = _live_tcb()
    facts = _facts(
        tcb_registry_sha256="0" * 64,
        tcb_snapshot_sha256=snapshot.snapshot_sha256,
        tcb_protected_path_count=len(registry.protected_paths),
    )
    with pytest.raises(TrustedAdmissionError, match="live tcb_registry_sha256"):
        admit_from_trusted_facts(facts)


def test_stale_policy_version_rejected_at_seal():
    with pytest.raises(TrustedAdmissionError, match="trusted_policy_version"):
        _facts(trusted_policy_version="forged-policy-v0")


def test_oos_and_forbidden_denied():
    facts = _facts(
        capability_requests=(
            _request(
                request_id="req_oos",
                capability_id="cb.file.write_bounded",
                requested_scope=(
                    "backend/continuous_builder/gpb_task_contract.py",
                ),
            ),
        )
    )
    decision, _ = admit_from_trusted_facts(facts)
    assert decision.overall_outcome == OUTCOME_DENY
    assert "cb.file.write_bounded" in decision.denied


def test_gate_removed_denied():
    facts = _facts(
        capability_requests=(
            _request(
                request_id="req_gate",
                capability_id="cb.file.write_bounded",
                evidence_refs=("gate_removed",),
            ),
        )
    )
    decision, _ = admit_from_trusted_facts(facts)
    assert "cb.file.write_bounded" in decision.denied


def test_budget_increase_denied():
    facts = _facts(
        capability_requests=(
            _request(
                request_id="req_budg",
                capability_id="cb.file.write_bounded",
                budget_wall_clock_seconds=99999,
            ),
        )
    )
    decision, _ = admit_from_trusted_facts(facts)
    assert "cb.file.write_bounded" in decision.denied


def test_plan_escalation_blocks_silent_allow():
    facts = _facts(
        plan_requires_escalation=True,
        plan_escalation_reasons=("needs_human",),
        capability_requests=(_request(request_id="req_esc"),),
    )
    decision, _ = admit_from_trusted_facts(facts)
    assert decision.overall_outcome == OUTCOME_ESCALATE
    assert "cb.repo.read" not in decision.admitted_within_bound


def test_low_risk_does_not_override_forbidden():
    facts = _facts(
        risk_ceiling_indicators=("none",),
        capability_requests=(
            _request(
                request_id="req_forb",
                capability_id="cb.file.write_bounded",
                requested_scope=(
                    "backend/continuous_builder/trusted_policy.py",
                ),
            ),
        ),
    )
    decision, _ = admit_from_trusted_facts(facts)
    assert decision.overall_outcome == OUTCOME_DENY
    row = decision.per_capability[0]
    assert "low_risk_does_not_override_deny" in row.reason_codes


def test_worker_provider_model_benchmark_ignored():
    facts = _facts(
        capability_requests=(
            _request(
                request_id="req_claim",
                capability_id="cb.credentials",
                worker_safe_claim=True,
                provider_id="claude",
                model_id="opus",
                benchmark_score=99.5,
                requested_scope=(),
            ),
        )
    )
    decision, _ = admit_from_trusted_facts(facts)
    assert "cb.credentials" not in decision.admitted_within_bound
    row = decision.per_capability[0]
    assert "worker_safe_claim_ignored" in row.reason_codes
    assert "provider_identity_ignored" in row.reason_codes
    assert "model_identity_ignored" in row.reason_codes
    assert "benchmark_score_ignored" in row.reason_codes


def test_main_merge_and_advance_never_allow_within_bound():
    for cap in ("cb.main.merge", "cb.main.advance"):
        facts = _facts(
            capability_requests=(
                _request(
                    request_id=f"req_{cap.replace('.', '_')}",
                    capability_id=cap,
                    requested_scope=(),
                    human_gate_requested=True,
                ),
            )
        )
        decision, receipt = admit_from_trusted_facts(facts)
        assert cap not in decision.admitted_within_bound
        assert decision.main_merge_auto_approved is False
        assert decision.execution_authorized is False
        assert receipt.approved_to_execute is False
    assert admission_never_auto_approves_main_merge() is True
    assert admission_decision_cannot_execute() is True


def test_system_model_mismatch_insufficient():
    facts = _facts(
        system_model_sha256="1" * 64,
        expected_system_model_sha256="2" * 64,
    )
    decision, _ = admit_from_trusted_facts(facts)
    assert decision.overall_outcome == OUTCOME_INSUFFICIENT_EVIDENCE


def test_matrix_default_deny_unknown_catch_all():
    matrix = create_gpc_policy_matrix_v1()
    from backend.continuous_builder.gpc_trusted_admission_core import (
        lookup_matrix_outcome,
    )

    outcome, reason, human, _rule = lookup_matrix_outcome(
        matrix, "cb.totally.unknown"
    )
    assert outcome == OUTCOME_INSUFFICIENT_EVIDENCE
    assert reason == "unknown_capability_never_allow"
    assert human is True


def test_core_is_tcb_protected():
    path = "backend/continuous_builder/gpc_trusted_admission_core.py"
    registry = create_mootos_tcb_registry_v1()
    assert path in registry.protected_paths
    assert len(registry.protected_paths) == 28
    assert len(registry.components) == 20
    component = registry.component_for_path(path)
    assert component.component_id == "cb_capability_admission"
    assert component.category == "capability_admission"
    assert component.change_policy == "human_only"
