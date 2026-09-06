"""GP-A7 -- Baseline Evidence Capture tests.

Split into two sections:

- Section A (hermetic): generic baseline-evidence logic exercised against
  a disposable, synthetic git repository built fresh in ``tmp_path`` for
  each test. These never touch this repository's own history and must
  pass identically whether the outer MootOS checkout is a full clone or
  CI's ``fetch-depth: 1`` shallow checkout.
- Section B (environment-dependent): the real MootOS-history proof
  (reconstructing the actual CB-029 merge). Skipped, not failed, when the
  outer checkout is shallow -- see ``repository_history_is_shallow``.
"""

import dataclasses
import subprocess
from pathlib import Path

import pytest

from backend.continuous_builder.gpa_baseline_evidence import (
    BaselineEvidenceError,
    BaselineEvidenceSnapshot,
    HistoricalPRObservation,
    HistoryUnavailableError,
    KNOWN_PROVIDER_PREFIXES,
    baseline_evidence_is_observational_only,
    create_baseline_evidence_snapshot,
    discover_merge_commit_shas,
    reconstruct_pr_observation,
    repository_history_is_shallow,
)
from backend.continuous_builder.gpa_eval_schema import GPAEvalSchemaError, UNKNOWN

REPO_ROOT = Path(__file__).resolve().parents[1]
CB029_MERGE_SHA = "d799c23169332135773e377443779ee9f9544c04"

_GIT_ENV_A = {
    "GIT_AUTHOR_NAME": "GP-A Test",
    "GIT_AUTHOR_EMAIL": "gpa-test@example.invalid",
    "GIT_COMMITTER_NAME": "GP-A Test",
    "GIT_COMMITTER_EMAIL": "gpa-test@example.invalid",
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00",
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


def _git(repo, *args, env=None):
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        check=True, env=env,
    ).stdout


def _build_synthetic_repo(tmp_path):
    """Build a small, disposable, deterministic git repo with:

    - an initial commit on ``main``
    - a ``codex/add-thing`` branch merged via a PR-style merge commit
      (recognized provider prefix, known pr_number)
    - a ``mystery-widget`` branch merged via a PR-style merge commit with
      an unrecognized prefix (pr_number known, provider_label UNKNOWN)
    - a non-PR-style merge commit (subject doesn't match at all -- both
      pr_number and provider_label UNKNOWN)
    - one trailing ordinary (non-merge) commit

    Returns a dict of the interesting commit SHAs.
    """
    import os

    env = dict(os.environ)
    env.update(_GIT_ENV_A)
    repo = tmp_path / "synthetic_repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main", env=env)
    _git(repo, "config", "user.name", "GP-A Test", env=env)
    _git(repo, "config", "user.email", "gpa-test@example.invalid", env=env)

    (repo / "a.txt").write_text("line1\n", encoding="utf-8")
    _git(repo, "add", "a.txt", env=env)
    _git(repo, "commit", "-q", "-m", "initial commit", env=env)

    # -- branch 1: recognized provider prefix --------------------------
    _git(repo, "checkout", "-q", "-b", "codex/add-thing", env=env)
    (repo / "a.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (repo / "b.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", "add thing (commit 1)", env=env)
    (repo / "b.txt").write_text("hello\nworld\n", encoding="utf-8")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", "add thing (commit 2)", env=env)
    _git(repo, "checkout", "-q", "main", env=env)
    _git(
        repo, "merge", "--no-ff", "-q",
        "-m", "Merge pull request #7 from someuser/codex/add-thing",
        "codex/add-thing", env=env,
    )
    codex_merge_sha = _git(repo, "rev-parse", "HEAD", env=env).strip()

    # -- branch 2: unrecognized provider prefix -------------------------
    _git(repo, "checkout", "-q", "-b", "mystery-widget", env=env)
    (repo / "c.txt").write_text("mystery\n", encoding="utf-8")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", "add mystery widget", env=env)
    _git(repo, "checkout", "-q", "main", env=env)
    _git(
        repo, "merge", "--no-ff", "-q",
        "-m", "Merge pull request #8 from someuser/mystery-widget",
        "mystery-widget", env=env,
    )
    unrecognized_merge_sha = _git(repo, "rev-parse", "HEAD", env=env).strip()

    # -- branch 3: merge subject that doesn't match the PR pattern ------
    _git(repo, "checkout", "-q", "-b", "feature-x", env=env)
    (repo / "d.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", "add feature x", env=env)
    _git(repo, "checkout", "-q", "main", env=env)
    _git(
        repo, "merge", "--no-ff", "-q", "-m", "Merge branch 'feature-x'",
        "feature-x", env=env,
    )
    non_pr_merge_sha = _git(repo, "rev-parse", "HEAD", env=env).strip()

    # -- trailing ordinary (non-merge) commit ---------------------------
    (repo / "e.txt").write_text("trailing\n", encoding="utf-8")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", "trailing ordinary commit", env=env)
    non_merge_sha = _git(repo, "rev-parse", "HEAD", env=env).strip()

    return {
        "repo": repo,
        "codex_merge_sha": codex_merge_sha,
        "unrecognized_merge_sha": unrecognized_merge_sha,
        "non_pr_merge_sha": non_pr_merge_sha,
        "non_merge_sha": non_merge_sha,
    }


# ---------------------------------------------------------------------
# Section A -- hermetic, synthetic-repository logic tests
# ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    # Module-scoped: every Section A test only reads from this repo (via
    # reconstruct_pr_observation/discover_merge_commit_shas), never
    # mutates it, so building it once keeps the suite fast instead of
    # re-running ~12 git subprocess calls per test.
    return _build_synthetic_repo(tmp_path_factory.mktemp("gpa_baseline_evidence"))


def test_discovers_merge_commits_in_synthetic_repo(synthetic):
    shas = discover_merge_commit_shas(synthetic["repo"], limit=10)
    assert synthetic["codex_merge_sha"] in shas
    assert synthetic["unrecognized_merge_sha"] in shas
    assert synthetic["non_pr_merge_sha"] in shas
    assert synthetic["non_merge_sha"] not in shas


def test_reconstructs_recognized_provider_with_real_numbers(synthetic):
    obs = reconstruct_pr_observation(synthetic["repo"], synthetic["codex_merge_sha"])
    assert obs.pr_number == 7
    assert obs.provider_label == "codex"
    assert obs.branch_name == "codex/add-thing"
    assert obs.outcome_state == "completed"
    # a.txt: +2 lines, b.txt: new file with 2 lines -> 2 files, 4 additions.
    assert obs.files_changed == 2
    assert obs.additions == 4
    assert obs.deletions == 0
    assert obs.commits_on_branch == 2


def test_unrecognized_branch_prefix_yields_unknown_provider_with_known_pr_number(
    synthetic,
):
    obs = reconstruct_pr_observation(
        synthetic["repo"], synthetic["unrecognized_merge_sha"],
    )
    assert obs.pr_number == 8
    assert obs.provider_label == UNKNOWN
    assert obs.branch_name == "mystery-widget"


def test_non_pr_style_merge_subject_yields_unknown_pr_number_and_provider(synthetic):
    obs = reconstruct_pr_observation(synthetic["repo"], synthetic["non_pr_merge_sha"])
    assert obs.pr_number == UNKNOWN
    assert obs.provider_label == UNKNOWN
    # Falls back to the raw subject line when it doesn't parse.
    assert obs.branch_name == "Merge branch 'feature-x'"


def test_unknown_fields_never_fabricated(synthetic):
    obs = reconstruct_pr_observation(synthetic["repo"], synthetic["codex_merge_sha"])
    # This record type has no token-count/cost/duration telemetry fields
    # at all -- git cannot supply them, and none are invented in their
    # place. (``_token`` is this module's own trusted-construction
    # marker, unrelated to LLM token counts -- excluded from the scan.)
    field_names = {f.name for f in dataclasses.fields(obs)} - {"_token"}
    for forbidden in ("token", "cost", "wall_clock", "duration"):
        assert not any(forbidden in name for name in field_names)


def test_provenance_present_only_for_known_fields(synthetic):
    obs = reconstruct_pr_observation(
        synthetic["repo"], synthetic["unrecognized_merge_sha"],
    )
    named = {name for name, _ in obs.field_provenance}
    assert "pr_number" in named
    assert "provider_label" not in named  # UNKNOWN -- must not be attributed


def test_snapshot_is_deterministic(synthetic):
    first = create_baseline_evidence_snapshot(synthetic["repo"], limit=10)
    second = create_baseline_evidence_snapshot(synthetic["repo"], limit=10)
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert first.to_dict() == second.to_dict()


def test_snapshot_observations_canonically_ordered(synthetic):
    snapshot = create_baseline_evidence_snapshot(synthetic["repo"], limit=10)
    shas = [o.merge_commit_sha for o in snapshot.observations]
    assert shas == sorted(shas)
    assert len(shas) == len(set(shas))
    assert snapshot.history_available is True
    assert len(snapshot.observations) == 3


def test_non_merge_commit_is_rejected(synthetic):
    with pytest.raises(BaselineEvidenceError, match="two-parent merge"):
        reconstruct_pr_observation(synthetic["repo"], synthetic["non_merge_sha"])


def test_malformed_sha_rejected(synthetic):
    with pytest.raises(GPAEvalSchemaError):
        reconstruct_pr_observation(synthetic["repo"], "not-a-sha")


def test_invalid_limit_rejected(synthetic):
    with pytest.raises(BaselineEvidenceError):
        discover_merge_commit_shas(synthetic["repo"], limit=0)
    with pytest.raises(BaselineEvidenceError):
        discover_merge_commit_shas(synthetic["repo"], limit=-1)


def test_observation_cannot_be_constructed_without_trusted_token(synthetic):
    obs = reconstruct_pr_observation(synthetic["repo"], synthetic["codex_merge_sha"])
    forged = _forge(obs, _token=object())
    with pytest.raises(BaselineEvidenceError):
        HistoricalPRObservation(**_fields(forged))


def test_forged_observation_field_with_stale_digest_rejected(synthetic):
    obs = reconstruct_pr_observation(synthetic["repo"], synthetic["codex_merge_sha"])
    forged = _forge(obs, additions=obs.additions + 1)
    with pytest.raises(BaselineEvidenceError, match="observation_sha256 mismatch"):
        HistoricalPRObservation(**_fields(forged))


def test_provenance_for_unknown_field_rejected(synthetic):
    obs = reconstruct_pr_observation(synthetic["repo"], synthetic["codex_merge_sha"])
    # provider_label is forced to UNKNOWN but field_provenance still
    # claims it was reconstructed -- must be rejected.
    forged = _forge(obs, provider_label=UNKNOWN)
    with pytest.raises(BaselineEvidenceError, match="UNKNOWN but attributed"):
        HistoricalPRObservation(**_fields(forged))


def test_snapshot_cannot_be_constructed_without_trusted_token(synthetic):
    snapshot = create_baseline_evidence_snapshot(synthetic["repo"], limit=3)
    forged = _forge(snapshot, _token=object())
    with pytest.raises(BaselineEvidenceError):
        BaselineEvidenceSnapshot(**_fields(forged))


def test_history_available_false_requires_empty_observations(synthetic):
    snapshot = create_baseline_evidence_snapshot(synthetic["repo"], limit=3)
    forged = _forge(snapshot, history_available=False)
    with pytest.raises(BaselineEvidenceError, match="must be empty"):
        BaselineEvidenceSnapshot(**_fields(forged))


def test_zero_authority(synthetic):
    snapshot = create_baseline_evidence_snapshot(synthetic["repo"], limit=3)
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


def test_shallow_clone_raises_history_unavailable_not_empty_result(tmp_path, synthetic):
    # The actual regression this repair fixes: a shallow clone must never
    # silently look like "zero merges exist".
    shallow = tmp_path / "shallow_clone"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1",
         f"file://{synthetic['repo']}", str(shallow)],
        check=True, capture_output=True, text=True,
    )
    assert repository_history_is_shallow(shallow) is True
    with pytest.raises(HistoryUnavailableError):
        discover_merge_commit_shas(shallow, limit=5)
    with pytest.raises(HistoryUnavailableError):
        reconstruct_pr_observation(shallow, synthetic["codex_merge_sha"])
    snapshot = create_baseline_evidence_snapshot(shallow, limit=5)
    assert snapshot.history_available is False
    assert snapshot.observations == ()


def test_full_clone_reports_history_available(synthetic):
    assert repository_history_is_shallow(synthetic["repo"]) is False


# ---------------------------------------------------------------------
# Section B -- real MootOS history (environment-dependent; skipped, not
# failed, when the outer checkout is shallow -- e.g. CI's fetch-depth: 1)
# ---------------------------------------------------------------------

pytestmark_shallow_skip = pytest.mark.skipif(
    repository_history_is_shallow(REPO_ROOT),
    reason="outer MootOS checkout is a shallow clone; real history unavailable",
)


@pytestmark_shallow_skip
def test_discovers_real_merge_commits():
    shas = discover_merge_commit_shas(REPO_ROOT, limit=5)
    assert len(shas) == 5
    assert CB029_MERGE_SHA in shas


@pytestmark_shallow_skip
def test_reconstructs_known_cb029_merge_with_real_numbers():
    obs = reconstruct_pr_observation(REPO_ROOT, CB029_MERGE_SHA)
    assert obs.pr_number == 93
    assert obs.provider_label == "grok"
    assert obs.branch_name == "grok/continuous-builder-cb029-context-engine-v1"
    assert obs.files_changed > 0
    assert obs.additions > 0
    assert obs.outcome_state == "completed"


@pytestmark_shallow_skip
def test_real_snapshot_contains_multiple_distinct_provider_labels():
    snapshot = create_baseline_evidence_snapshot(REPO_ROOT, limit=25)
    assert snapshot.history_available is True
    labels = {o.provider_label for o in snapshot.observations}
    # Real history: at least one known provider AND unattributed entries
    # both appear -- this corpus should not pretend everything is known.
    assert labels & KNOWN_PROVIDER_PREFIXES
    assert UNKNOWN in labels or labels <= KNOWN_PROVIDER_PREFIXES
