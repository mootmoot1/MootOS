"""GP-A5 -- Representative Evaluation Corpus v1 tests."""

from pathlib import Path

import pytest

from backend.continuous_builder.gpa_eval_case import (
    to_worker_visible_dict,
    verify_no_evaluator_leakage,
)
from backend.continuous_builder.gpa_eval_corpus import (
    CORPUS_BASE_SHA,
    FIXTURE_BACKED_CASES,
    create_gpa_eval_corpus_v1,
    corpus_class_distribution,
    eval_case_by_id,
    eval_corpus_is_descriptive_only,
)
from backend.continuous_builder.gpa_task_taxonomy import (
    create_gpa_task_taxonomy_v1,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CLASS_IDS = {
    item.class_id for item in create_gpa_task_taxonomy_v1().classes
}


def test_corpus_size_within_target_range():
    cases = create_gpa_eval_corpus_v1()
    assert 10 <= len(cases) <= 20


def test_every_case_id_is_unique():
    cases = create_gpa_eval_corpus_v1()
    ids = [case.eval_case_id for case in cases]
    assert len(ids) == len(set(ids))


def test_every_taxonomy_class_is_represented():
    cases = create_gpa_eval_corpus_v1()
    represented = {case.taxonomy_class_id for case in cases}
    assert represented == REQUIRED_CLASS_IDS


def test_every_case_bound_to_corpus_base_sha():
    cases = create_gpa_eval_corpus_v1()
    for case in cases:
        assert case.base_sha == CORPUS_BASE_SHA


def test_corpus_is_deterministic():
    first = create_gpa_eval_corpus_v1()
    second = create_gpa_eval_corpus_v1()
    assert [c.case_sha256 for c in first] == [c.case_sha256 for c in second]


def test_class_distribution_sums_to_corpus_size():
    cases = create_gpa_eval_corpus_v1()
    dist = corpus_class_distribution(cases)
    assert sum(dist.values()) == len(cases)
    assert set(dist) <= REQUIRED_CLASS_IDS


def test_eval_case_by_id_lookup():
    cases = create_gpa_eval_corpus_v1()
    found = eval_case_by_id(cases, "nb_001")
    assert found is not None
    assert found.taxonomy_class_id == "narrow_bug_fix"
    assert eval_case_by_id(cases, "not_a_real_case") is None


def test_no_case_leaks_evaluator_data_in_worker_view():
    cases = create_gpa_eval_corpus_v1()
    for case in cases:
        payload = to_worker_visible_dict(case)
        assert verify_no_evaluator_leakage(payload), case.eval_case_id


def test_fixture_backed_cases_exist_on_disk():
    for case_id, spec in FIXTURE_BACKED_CASES.items():
        fixture_dir = REPO_ROOT / spec["fixture_dir"]
        acceptance_path = fixture_dir / spec["acceptance_file"]
        assert fixture_dir.is_dir(), case_id
        assert acceptance_path.is_file(), case_id


def test_fixture_backed_case_allowed_scope_matches_fixture_dir():
    cases = create_gpa_eval_corpus_v1()
    for case_id, spec in FIXTURE_BACKED_CASES.items():
        case = eval_case_by_id(cases, case_id)
        assert case is not None
        for path in case.worker_view.allowed_scope:
            assert path.startswith(spec["fixture_dir"] + "/"), case_id


def test_tcb_adjacent_case_forbids_real_tcb_paths():
    cases = create_gpa_eval_corpus_v1()
    case = eval_case_by_id(cases, "tcb_001")
    assert "backend/continuous_builder/trusted_policy.py" in (
        case.worker_view.forbidden_scope
    )


@pytest.mark.parametrize("case_id", ["nb_001", "bf_001", "refactor_001"])
def test_fixture_backed_cases_have_expected_verification_commands(case_id):
    cases = create_gpa_eval_corpus_v1()
    case = eval_case_by_id(cases, case_id)
    assert case.evaluator_view.expected_verification_commands


def test_descriptive_only_helper():
    assert eval_corpus_is_descriptive_only() is True
