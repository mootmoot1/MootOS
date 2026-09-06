"""GP-A1 -- Architecture Baseline Manifest tests."""

import dataclasses
from pathlib import Path

import pytest

from backend.continuous_builder.gpa_architecture_baseline import (
    ArchitectureBaselineError,
    ArchitectureBaselineManifest,
    BASELINE_VERSION,
    architecture_baseline_is_descriptive_only,
    create_architecture_baseline_manifest,
)
from backend.continuous_builder.gpa_eval_schema import (
    GPA_SCHEMA_SUITE_VERSION,
    GPAEvalSchemaError,
)
from backend.continuous_builder.trusted_policy import create_trusted_policy_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
VALID_SHA = "d799c23169332135773e377443779ee9f9544c04"


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


def test_manifest_is_deterministic_for_same_base_sha():
    first = create_architecture_baseline_manifest(REPO_ROOT, base_sha=VALID_SHA)
    second = create_architecture_baseline_manifest(REPO_ROOT, base_sha=VALID_SHA)
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.to_dict() == second.to_dict()


def test_manifest_binds_live_tcb_registry_digest():
    manifest = create_architecture_baseline_manifest(REPO_ROOT, base_sha=VALID_SHA)
    snapshot = create_trusted_policy_snapshot()
    assert manifest.tcb_registry_sha256 == snapshot.registry_sha256
    assert manifest.tcb_protected_path_count == snapshot.protected_path_count
    assert manifest.tcb_component_count == snapshot.component_count


def test_manifest_zero_authority():
    manifest = create_architecture_baseline_manifest(REPO_ROOT, base_sha=VALID_SHA)
    for name in (
        "publication_authorized",
        "queue_transition_authorized",
        "github_authorized",
        "merge_authorized",
        "main_advancement_authorized",
        "result_trusted",
        "worker_output_trusted",
    ):
        assert getattr(manifest, name) is False


def test_manifest_schema_versions():
    manifest = create_architecture_baseline_manifest(REPO_ROOT, base_sha=VALID_SHA)
    assert manifest.schema_version == BASELINE_VERSION
    assert manifest.eval_schema_suite_version == GPA_SCHEMA_SUITE_VERSION


def test_descriptive_only_helper():
    assert architecture_baseline_is_descriptive_only() is True


@pytest.mark.parametrize(
    "bad_sha",
    ["", "not-a-sha", "a" * 39, "A" * 40, "g" * 40, None, 12345],
)
def test_rejects_malformed_base_sha(bad_sha):
    with pytest.raises(GPAEvalSchemaError):
        create_architecture_baseline_manifest(REPO_ROOT, base_sha=bad_sha)


def test_manifest_cannot_be_constructed_without_trusted_token():
    manifest = create_architecture_baseline_manifest(REPO_ROOT, base_sha=VALID_SHA)
    forged = _forge(manifest, _token=object())
    with pytest.raises(ArchitectureBaselineError):
        ArchitectureBaselineManifest(**_fields(forged))


def test_forged_field_with_stale_digest_is_rejected():
    manifest = create_architecture_baseline_manifest(REPO_ROOT, base_sha=VALID_SHA)
    forged = _forge(manifest, cb_file_count=manifest.cb_file_count + 1)
    with pytest.raises(ArchitectureBaselineError, match="manifest_sha256 mismatch"):
        ArchitectureBaselineManifest(**_fields(forged))


def test_unreadable_context_engine_source_reports_baseline_error(tmp_path):
    fake_root = tmp_path / "repo"
    fake_root.mkdir()
    with pytest.raises(ArchitectureBaselineError):
        create_architecture_baseline_manifest(fake_root, base_sha=VALID_SHA)
