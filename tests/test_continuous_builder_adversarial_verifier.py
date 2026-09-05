"""CB-026C policy tests; transport observations are simulated in this file."""

from dataclasses import replace
import os
import time

import pytest

from backend.continuous_builder import adversarial_verifier as av
from backend.continuous_builder import check_runner as checks
from backend.continuous_builder import check_runtime as runtime
from backend.continuous_builder.verifier_core import verify_candidate_structure
from tests.test_continuous_builder_check_runner import _image, _observed
from tests.test_continuous_builder_verifier_core import _candidate, _forge


def _inputs(tmp_path, monkeypatch, artifacts=None):
    foundation, execution, intake = _candidate(
        tmp_path, monkeypatch, artifacts or {"value.txt": b"2\n"},
    )
    contract = av.create_public_value_contract(
        slice_digest="a" * 64,
        pinned_base_sha=execution.materialization_receipt.pinned_base_sha,
        worker_request_digest=execution.request_digest,
    )
    structural = verify_candidate_structure(contract, execution, intake)
    monkeypatch.setattr(checks, "CHECK_ROOT", tmp_path / "checks")
    return contract, structural, execution, intake


def _execute(tmp_path, monkeypatch, outcomes=(0, 0, 0), artifacts=None):
    contract, structural, execution, intake = _inputs(
        tmp_path, monkeypatch, artifacts,
    )
    pending = iter(outcomes)
    roots = []

    def transport(plan, root):
        assert checks._observe_tree(root) == plan.candidate_tree_sha256
        roots.append(root)
        value = next(pending)
        if isinstance(value, dict):
            yield value
        else:
            yield _observed(exit_code=value, failures=(
                ("check_nonzero_exit",) if value else ()))

    monkeypatch.setattr(runtime, "execute_checks", transport)
    plan = av.create_public_value_plan(contract, structural, image=_image())
    public = checks.run_trusted_checks(plan, contract, execution, intake)
    scenario = av.select_held_out_scenario(public)
    result = av.run_adversarial_verification(scenario, execution, intake)
    assert all(not root.parent.exists() for root in roots)
    return result, scenario, execution, intake


@pytest.mark.parametrize("outcomes,status,code", [
    ((0, 0, 0), "passed", None),
    ((1, 1, 1), "failed", "public_check_failed"),
    ((0, 1, 1), "failed", "public_private_outcome_diverged"),
    ((0, 0, 1), "failed", "nondeterministic_outcome"),
    ((0, 1, 0), "failed", "repeat_verification_failed"),
])
def test_outcome_matrix(tmp_path, monkeypatch, outcomes, status, code):
    result, _, _, _ = _execute(tmp_path, monkeypatch, outcomes)
    assert result.final_classification == "adversarial_verification_" + status
    if code:
        assert code in result.failure_codes
    assert result.cleanup_confirmed


@pytest.mark.parametrize("path,content", [
    (av.PUBLIC_PATH, b"def test_weak():\n    assert True\n"),
    (av.PUBLIC_PATH, b""),
    ("surprise.py", b"print('ALL TESTS PASSED')\n"),
    ("pytest.ini", b"[pytest]\naddopts = --ignore=held_out\n"),
    ("pyproject.toml", b"[tool.pytest.ini_options]\n"),
    ("setup.cfg", b"[tool:pytest]\n"),
    ("conftest.py", b"import os\nos._exit(0)\n"),
    ("tests/__init__.py", b"import os\nos._exit(0)\n"),
    ("pytest.py", b"raise SystemExit(0)\n"),
    ("sitecustomize.py", b"raise SystemExit(0)\n"),
    ("environment.py", b"import os\nos.environ.clear()\n"),
    *((path, b"# replace referee\n") for path in av.PROTECTED_PATHS
      if path != av.PUBLIC_PATH),
])
def test_adversarial_paths_rejected(tmp_path, monkeypatch, path, content):
    contract, structural, _, _ = _inputs(
        tmp_path, monkeypatch, {"value.txt": b"3\n", path: content},
    )
    assert structural.status == "structural_verification_failed"
    assert "artifact_path_not_allowed" in structural.failure_codes
    with pytest.raises(checks.CheckRunnerError):
        av.create_public_value_plan(contract, structural, image=_image())


def test_omission_does_not_delete_base_test(tmp_path, monkeypatch):
    result, _, _, _ = _execute(tmp_path, monkeypatch)
    base = result._plan._contract.base_content()
    assert base[av.PUBLIC_PATH] == av.PUBLIC_CONTENT


def test_worker_claim_cannot_choose_result(tmp_path, monkeypatch):
    result, _, _, _ = _execute(
        tmp_path, monkeypatch, (1, 1, 1),
        {"value.txt": b"ALL TESTS PASSED\n"},
    )
    assert result.final_classification == "adversarial_verification_failed"


def test_information_and_reconstruction_separation(tmp_path, monkeypatch):
    result, scenario, execution, _ = _execute(tmp_path, monkeypatch)
    public = scenario._public._plan._contract
    assert av.HELD_OUT_PATH not in public.base_content()
    assert av._HELD_OUT_CONTENT not in execution.stdout_sample.encode()
    assert av._HELD_OUT_CONTENT not in public._payload()
    assert (result.candidate_tree_sha256 !=
            result.augmented_candidate_tree_sha256)
    assert (result.structural_receipt_sha256 !=
            result.augmented_structural_receipt_sha256)
    assert len({r.workspace_identity_sha256 for r in result._runs}) == 2
    assert len({r.plan_sha256 for r in result._runs}) == 1
    assert av.HELD_OUT_PATH in result._plan._contract.protected_paths


@pytest.mark.parametrize("changes", [
    {"scenario_id": "worker-choice"}, {"repeat_count": 1},
    {"content_sha256": "0" * 64}, {"candidate_tree_sha256": "0" * 64},
    {"scenario_sha256": "0" * 64}, {"expected_outcome": "checks_failed"},
    {"_token": None},
])
def test_scenario_forgery(tmp_path, monkeypatch, changes):
    _, scenario, execution, intake = _execute(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        av.run_adversarial_verification(
            _forge(scenario, **changes), execution, intake,
        )


@pytest.mark.parametrize("flag", checks.AUTHORITY_FLAGS)
def test_authority_promotion(tmp_path, monkeypatch, flag):
    result, _, _, _ = _execute(tmp_path, monkeypatch)
    assert getattr(result, flag) is False
    with pytest.raises(ValueError):
        replace(result, **{flag: True})


def test_receipt_forgery_and_replay(tmp_path, monkeypatch):
    result, scenario, execution, intake = _execute(tmp_path, monkeypatch)
    for change in ({"receipt_sha256": "0" * 64}, {"_runs": ()},
                   {"human_review_required": False},
                   {"_runs": (result._runs[0], result._runs[0])}):
        with pytest.raises(ValueError):
            replace(result, **change)
    forged_intake = _forge(intake, _artifact_payloads=(("value.txt", b"3\n"),))
    with pytest.raises(ValueError):
        av.run_adversarial_verification(scenario, execution, forged_intake)


@pytest.mark.parametrize("observed", [
    _observed(cleanup=False, failures=("cleanup_uncertain",)),
    _observed(terminated=False, failures=("execution_uncertain",)),
    _observed(timeout=True, complete=False, failures=("check_timeout",)),
])
def test_uncertainty_never_passes(tmp_path, monkeypatch, observed):
    result, _, _, _ = _execute(tmp_path, monkeypatch, (0, observed))
    assert result.final_classification == "adversarial_verification_uncertain"


def test_selection_has_no_worker_options(tmp_path, monkeypatch):
    _, scenario, _, _ = _execute(tmp_path, monkeypatch)
    assert av.select_held_out_scenario(scenario._public) == scenario
    for option in ({"scenario_id": "foo"}, {"repeat_count": 1},
                   {"argv": ("sh",)}, {"held_out_content": b"pass"}):
        with pytest.raises(TypeError):
            av.select_held_out_scenario(scenario._public, **option)


def test_candidate_a_scenario_cannot_verify_candidate_b(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _, scenario, _, _ = _execute(first, monkeypatch)
    _, _, execution, intake = _inputs(
        second, monkeypatch, {"value.txt": b"3\n"},
    )
    with pytest.raises(ValueError):
        av.run_adversarial_verification(scenario, execution, intake)


def test_candidate_python_is_never_imported(tmp_path, monkeypatch):
    result, _, _, _ = _execute(
        tmp_path, monkeypatch, (1, 1, 1),
        {"value.txt": b"import os; os._exit(0)\n"},
    )
    assert result.final_classification == "adversarial_verification_failed"
    assert result._plan._contract.allowed_paths == ("value.txt",)


def test_uncertain_public_does_not_launch_held_out(tmp_path, monkeypatch):
    observed = _observed(cleanup=False, failures=("cleanup_uncertain",))
    result, _, _, _ = _execute(tmp_path, monkeypatch, (observed,))
    assert result._runs == ()
    assert result.final_classification == "adversarial_verification_uncertain"


@pytest.mark.parametrize(
    "case", ["positive", "gamed-public", "repeat-timeout"],
)
def test_real_adversarial_container(tmp_path, monkeypatch, case):
    """Real Docker checks; upstream worker admission is simulated.

    The independent local harness additionally uses an actual offline worker.
    Repeat control injects a tighter deadline, never an execution observation.
    """
    digest = os.environ.get("CB026B_TEST_IMAGE_DIGEST")
    config = os.environ.get("CB026B_TEST_CONFIG_DIGEST")
    if not digest or not config:
        pytest.skip("opt-in reviewed local Docker image required")
    image = checks.create_trusted_check_image(
        image_digest=digest, config_sha256=config, architecture="amd64",
    )
    with pytest.MonkeyPatch.context() as upstream:
        contract, structural, execution, intake = _inputs(
            tmp_path, upstream,
            {"value.txt": b"3\n" if case == "gamed-public" else b"2\n"},
        )
    plan = av.create_public_value_plan(contract, structural, image=image)
    public = checks.run_trusted_checks(plan, contract, execution, intake)
    assert public.status == "checks_passed", public.canonical_bytes()
    scenario = av.select_held_out_scenario(public)
    original = runtime._collect
    calls = []

    def tighter_deadline(cli, name, check, deadline):
        calls.append(name)
        if len(calls) == 2:
            deadline = min(deadline, time.monotonic() + 0.001)
        return original(cli, name, check, deadline)

    if case == "repeat-timeout":
        monkeypatch.setattr(runtime, "_collect", tighter_deadline)
    receipt = av.run_adversarial_verification(scenario, execution, intake)
    expected = {"positive": "passed", "gamed-public": "failed",
                "repeat-timeout": "uncertain"}[case]
    assert (receipt.final_classification ==
            "adversarial_verification_" + expected)
    assert receipt.cleanup_confirmed
    assert not list(checks.CHECK_ROOT.iterdir())
    if case == "repeat-timeout":
        assert receipt.repeated_outcomes[0] == "checks_passed"
        assert receipt.repeated_outcomes[1] != "checks_passed"
        assert "nondeterministic_outcome" in receipt.failure_codes
