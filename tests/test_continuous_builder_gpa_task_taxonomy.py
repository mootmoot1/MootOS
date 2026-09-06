"""GP-A2 -- MootOS Task Taxonomy tests."""

import dataclasses

import pytest

from backend.continuous_builder.gpa_task_taxonomy import (
    TAXONOMY_VERSION,
    TaskTaxonomy,
    TaskTaxonomyError,
    TaxonomyClass,
    create_gpa_task_taxonomy_v1,
    is_known_taxonomy_class_id,
    task_taxonomy_is_descriptive_only,
    taxonomy_class_by_id,
)

REQUIRED_CLASS_IDS = {
    "narrow_bug_fix",
    "bounded_feature_addition",
    "test_addition",
    "behavior_preserving_refactor",
    "docs_spec_sync",
    "multi_file_feature",
    "security_sensitive_change",
    "tcb_adjacent_change",
    "migration_schema_change",
    "dependency_api_boundary_change",
    "context_heavy_navigation_task",
    "verifier_policy_sensitive_task",
}


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in dataclasses.fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def _fields(instance):
    return {
        item.name: getattr(instance, item.name)
        for item in dataclasses.fields(instance)
    }


def test_covers_every_required_class_exactly_once():
    taxonomy = create_gpa_task_taxonomy_v1()
    ids = [item.class_id for item in taxonomy.classes]
    assert set(ids) == REQUIRED_CLASS_IDS
    assert len(ids) == len(set(ids))


def test_deterministic_digest():
    first = create_gpa_task_taxonomy_v1()
    second = create_gpa_task_taxonomy_v1()
    assert first.taxonomy_sha256 == second.taxonomy_sha256
    assert first.to_dict() == second.to_dict()


def test_classes_are_canonically_ordered():
    taxonomy = create_gpa_task_taxonomy_v1()
    ids = tuple(item.class_id for item in taxonomy.classes)
    assert ids == tuple(sorted(ids))


def test_zero_authority():
    taxonomy = create_gpa_task_taxonomy_v1()
    for name in (
        "publication_authorized",
        "queue_transition_authorized",
        "github_authorized",
        "merge_authorized",
        "main_advancement_authorized",
        "result_trusted",
        "worker_output_trusted",
    ):
        assert getattr(taxonomy, name) is False


def test_lookup_helpers():
    taxonomy = create_gpa_task_taxonomy_v1()
    found = taxonomy_class_by_id(taxonomy, "narrow_bug_fix")
    assert found is not None
    assert found.class_id == "narrow_bug_fix"
    assert is_known_taxonomy_class_id(taxonomy, "narrow_bug_fix") is True
    assert taxonomy_class_by_id(taxonomy, "not_a_real_class") is None
    assert is_known_taxonomy_class_id(taxonomy, "not_a_real_class") is False


def test_descriptive_only_helper():
    assert task_taxonomy_is_descriptive_only() is True


def test_taxonomy_class_cannot_be_constructed_without_trusted_token():
    taxonomy = create_gpa_task_taxonomy_v1()
    original = taxonomy.classes[0]
    forged = _forge(original, _token=object())
    with pytest.raises(TaskTaxonomyError):
        TaxonomyClass(**_fields(forged))


def test_forged_class_field_with_stale_digest_is_rejected():
    taxonomy = create_gpa_task_taxonomy_v1()
    original = taxonomy.classes[0]
    forged = _forge(original, autonomy_experiment_suitable=(
        not original.autonomy_experiment_suitable
    ))
    with pytest.raises(TaskTaxonomyError, match="class_sha256 mismatch"):
        TaxonomyClass(**_fields(forged))


def test_unknown_risk_indicator_rejected():
    taxonomy = create_gpa_task_taxonomy_v1()
    original = taxonomy.classes[0]
    forged = _forge(original, risk_indicators=("not_a_real_risk_code",))
    with pytest.raises(TaskTaxonomyError, match="unknown code"):
        TaxonomyClass(**_fields(forged))


def test_container_cannot_be_constructed_without_trusted_token():
    taxonomy = create_gpa_task_taxonomy_v1()
    forged = _forge(taxonomy, _token=object())
    with pytest.raises(TaskTaxonomyError):
        TaskTaxonomy(**_fields(forged))


def test_duplicate_class_ids_rejected():
    taxonomy = create_gpa_task_taxonomy_v1()
    duplicated = (taxonomy.classes[0], taxonomy.classes[0])
    forged = _forge(taxonomy, classes=duplicated)
    with pytest.raises(TaskTaxonomyError, match="canonically ordered"):
        TaskTaxonomy(**_fields(forged))


def test_unsupported_version_rejected():
    taxonomy = create_gpa_task_taxonomy_v1()
    forged = _forge(taxonomy, version="some-other-version")
    with pytest.raises(TaskTaxonomyError, match="version is unsupported"):
        TaskTaxonomy(**_fields(forged))
