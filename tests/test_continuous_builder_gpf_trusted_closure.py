"""Every security-relevant module a launch verdict derives from is protected.

A trusted launch decision must not rest on worker-modifiable executable
code. These tests pin the exact closure and prove each member is either
protected or provably unable to alter a verdict.
"""

import ast
import inspect
from pathlib import Path

import pytest

from backend.continuous_builder import gpf_launch_semantics as semantics
from backend.continuous_builder.trusted_policy import (
    create_mootos_tcb_registry_v1,
)
from backend.continuous_builder.trusted_policy_enforcement import (
    evaluate_changed_paths_against_tcb, OUTCOME_FORBIDDEN,
)

# The complete local import closure of the launch-eligibility referee.
TRUSTED_CLOSURE = frozenset({
    "gpf_launch_semantics",
    "gpf_launch_state_projection",
    "gpf_launch_facts",
    "gpf_launch_candidate_binding",
    "gpf_approval_authority",
    "gpc_trusted_admission_core",
    "gpd_job_state",
    "gpd_job_events",
    "gpd_job_header",
    "gpa_eval_schema",
    "timestamps",
    "trusted_policy",
    "paths",
    "text_safety",
})

# Modules whose executable behaviour can materially change a launch
# verdict, or change what "protected" itself means. Every one must be a
# protected TCB path that an ordinary worker may not edit.
VERDICT_RELEVANT = frozenset(TRUSTED_CLOSURE)

FORBIDDEN_MODULES = (
    "context_engine", "system_model", "gpe_protocol", "gpf_supervisor",
    "gpf_launch_preparation", "gpf_binding_resolution", "gpd_job_store",
    "gpd_recovery", "worker_runtime", "worker_provider",
)


def local_closure(entry):
    root = Path(inspect.getfile(semantics)).parent
    pending, seen = [entry], set()
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        source = root / (module + ".py")
        if not source.exists():
            continue
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                if node.module:
                    pending.append(node.module)
                else:
                    pending.extend(alias.name for alias in node.names)
    return seen


def test_closure_is_exactly_the_declared_trusted_set():
    assert local_closure("gpf_launch_semantics") == set(TRUSTED_CLOSURE)


def test_closure_is_deterministic():
    assert local_closure("gpf_launch_semantics") == local_closure(
        "gpf_launch_semantics")


@pytest.mark.parametrize("module", sorted(VERDICT_RELEVANT))
def test_every_verdict_relevant_module_is_protected(module):
    path = "backend/continuous_builder/" + module + ".py"
    registry = create_mootos_tcb_registry_v1()
    assert path in registry.protected_paths
    component = registry.component_for_path(path)
    assert component is not None
    assert component.change_policy in ("human_only", "protected_core_review")


def test_ordinary_worker_cannot_change_any_trusted_dependency():
    paths = sorted(
        "backend/continuous_builder/" + module + ".py"
        for module in VERDICT_RELEVANT
    )
    decision = evaluate_changed_paths_against_tcb(paths)
    assert decision.outcome == OUTCOME_FORBIDDEN
    for path in paths:
        single = evaluate_changed_paths_against_tcb([path])
        assert single.outcome == OUTCOME_FORBIDDEN, path


def test_newly_protected_dependencies_are_registered_human_only():
    registry = create_mootos_tcb_registry_v1()
    expected = {
        "cb_durable_state_contract": (
            "backend/continuous_builder/gpd_job_events.py",
            "backend/continuous_builder/gpd_job_header.py",
            "backend/continuous_builder/gpd_job_state.py",
        ),
        "cb_schema_digest_primitives": (
            "backend/continuous_builder/gpa_eval_schema.py",
            "backend/continuous_builder/timestamps.py",
        ),
        "cb_path_canonicalization": (
            "backend/continuous_builder/paths.py",
            "backend/continuous_builder/text_safety.py",
        ),
    }
    components = {item.component_id: item for item in registry.components}
    for component_id, paths in expected.items():
        component = components[component_id]
        assert component.paths == paths
        assert component.change_policy == "human_only"


def test_registry_shape_after_hardening():
    registry = create_mootos_tcb_registry_v1()
    assert len(registry.protected_paths) == 28
    assert len(registry.components) == 20
    assert registry.registry_sha256 == (
        "89faaa9cab36a21d33c792f8692a9f9982c4e83587ac2e9d1c1d64ff117b47eb"
    )


def test_no_execution_or_provider_stack_enters_the_closure():
    seen = local_closure("gpf_launch_semantics")
    for module in FORBIDDEN_MODULES:
        assert module not in seen


def test_protecting_a_dependency_does_not_grant_it_authority():
    registry = create_mootos_tcb_registry_v1()
    snapshot_flags = (
        "publication_authorized", "queue_transition_authorized",
        "github_authorized", "merge_authorized",
        "main_advancement_authorized", "result_trusted",
        "worker_output_trusted",
    )
    for name in snapshot_flags:
        assert getattr(registry, name, False) is False
