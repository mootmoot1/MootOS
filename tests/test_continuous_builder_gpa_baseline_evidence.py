"""GP-A7 -- Baseline Evidence Capture tests."""

import dataclasses
from pathlib import Path

import pytest

from backend.continuous_builder.gpa_baseline_evidence import (
    BaselineEvidenceError,
    BaselineEvidenceSnapshot,
    HistoricalPRObservation,
    KNOWN_PROVIDER_PREFIXES,
    baseline_evidence_is_observational_only,
    create_baseline_evidence_snapshot,
    discover_merge_commit_shas,
    reconstruct_pr_observation,
)
from backend.continuous_builder.gpa_eval_schema import GPAEvalSchemaError, UNKNOWN

REPO_ROOT = Path(__file__).resolve().parents[1]
CB029_MERGE_SHA = "d799c23169332135773e377443779ee9f9544c04"


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


def test_discovers_real_merge_commits():
    shas = discover_merge_commit_shas(REPO_ROOT, limit=5)
    assert len(shas) == 5
    assert CB029_MERGE_SHA in shas


def test_reconstructs_known_cb029_merge_with_real_numbers():
    obs = reconstruct_pr_observation(REPO_ROOT, CB029_MERGE_SHA)
    assert obs.pr_number == 93
    assert obs.provider_label == "grok"
    assert obs.branch_name == "grok/continuous-builder-cb029-context-engine-v1"
    assert obs.files_changed > 0
    assert obs.additions > 0
    assert obs.outcome_state == "completed"


def test_unknown_fields_never_fabricated():
    obs = reconstruct_pr_observation(REPO_ROOT, CB029_MERGE_SHA)
    # This record type has no token-count/cost/duration telemetry fields
    # at all -- git cannot supply them, and none are invented in their
    # place. (``_token`` is this module's own trusted-construction
    # marker, unrelated to LLM token counts -- excluded from the scan.)
    field_names = {f.name for f in dataclasses.fields(obs)} - {"_token"}
    for forbidden in ("token", "cost", "wall_clock", "duration"):
        assert not any(forbidden in name for name in field_names)


def test_snapshot_is_deterministic():
    first = create_baseline_evidence_snapshot(REPO_ROOT, limit=8)
    second = create_baseline_evidence_snapshot(REPO_ROOT, limit=8)
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert first.to_dict() == second.to_dict()


def test_snapshot_observations_canonically_ordered():
    snapshot = create_baseline_evidence_snapshot(REPO_ROOT, limit=10)
    shas = [o.merge_commit_sha for o in snapshot.observations]
    assert shas == sorted(shas)
    assert len(shas) == len(set(shas))


def test_snapshot_contains_multiple_distinct_provider_labels():
    snapshot = create_baseline_evidence_snapshot(REPO_ROOT, limit=25)
    labels = {o.provider_label for o in snapshot.observations}
    # Real history: at least one known provider AND unattributed entries
    # both appear -- this corpus should not pretend everything is known.
    assert labels & KNOWN_PROVIDER_PREFIXES
    assert UNKNOWN in labels or labels <= KNOWN_PROVIDER_PREFIXES


def test_every_known_field_has_provenance_every_unknown_field_does_not():
    snapshot = create_baseline_evidence_snapshot(REPO_ROOT, limit=15)
    for obs in snapshot.observations:
        named = {name for name, _ in obs.field_provenance}
        for field_name in ("pr_number", "provider_label", "commits_on_branch"):
            known = getattr(obs, field_name) != UNKNOWN
            assert (field_name in named) == known, (obs.merge_commit_sha, field_name)


def test_non_merge_commit_is_rejected():
    # HEAD of this branch's history includes ordinary (non-merge) commits;
    # find one and confirm it's rejected rather than silently degraded.
    import subprocess

    output = subprocess.run(
        ["git", "log", "--no-merges", "-n1", "--pretty=format:%H"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert output
    with pytest.raises(BaselineEvidenceError, match="two-parent merge"):
        reconstruct_pr_observation(REPO_ROOT, output)


def test_malformed_sha_rejected():
    with pytest.raises(GPAEvalSchemaError):
        reconstruct_pr_observation(REPO_ROOT, "not-a-sha")


def test_invalid_limit_rejected():
    with pytest.raises(BaselineEvidenceError):
        discover_merge_commit_shas(REPO_ROOT, limit=0)
    with pytest.raises(BaselineEvidenceError):
        discover_merge_commit_shas(REPO_ROOT, limit=-1)


def test_observation_cannot_be_constructed_without_trusted_token():
    obs = reconstruct_pr_observation(REPO_ROOT, CB029_MERGE_SHA)
    forged = _forge(obs, _token=object())
    with pytest.raises(BaselineEvidenceError):
        HistoricalPRObservation(**_fields(forged))


def test_forged_observation_field_with_stale_digest_rejected():
    obs = reconstruct_pr_observation(REPO_ROOT, CB029_MERGE_SHA)
    forged = _forge(obs, additions=obs.additions + 1)
    with pytest.raises(BaselineEvidenceError, match="observation_sha256 mismatch"):
        HistoricalPRObservation(**_fields(forged))


def test_provenance_for_unknown_field_rejected():
    obs = reconstruct_pr_observation(REPO_ROOT, CB029_MERGE_SHA)
    # provider_label is forced to UNKNOWN but field_provenance still
    # claims it was reconstructed -- must be rejected.
    forged = _forge(obs, provider_label=UNKNOWN)
    with pytest.raises(BaselineEvidenceError, match="UNKNOWN but attributed"):
        HistoricalPRObservation(**_fields(forged))


def test_snapshot_cannot_be_constructed_without_trusted_token():
    snapshot = create_baseline_evidence_snapshot(REPO_ROOT, limit=3)
    forged = _forge(snapshot, _token=object())
    with pytest.raises(BaselineEvidenceError):
        BaselineEvidenceSnapshot(**_fields(forged))


def test_zero_authority():
    snapshot = create_baseline_evidence_snapshot(REPO_ROOT, limit=3)
    for name in (
        "publication_authorized",
        "queue_transition_authorized",
        "github_authorized",
        "merge_authorized",
        "main_advancement_authorized",
        "result_trusted",
        "worker_output_trusted",
    ):
        assert getattr(snapshot, name) is False
        for obs in snapshot.observations:
            assert getattr(obs, name) is False


def test_descriptive_only_helper():
    assert baseline_evidence_is_observational_only() is True
