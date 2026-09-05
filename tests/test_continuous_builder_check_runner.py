"""Policy tests plus opt-in real, network-disabled Docker check executions."""

import dataclasses
import hashlib
import copy
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.continuous_builder.check_runner as runner
import backend.continuous_builder.check_runtime as runtime
from backend.continuous_builder.verifier_core import verify_candidate_structure
from tests.test_continuous_builder_verifier_core import _candidate, _contract, _forge


def _image():
    return runner.create_trusted_check_image(
        image_digest="a" * 64, config_sha256="b" * 64, architecture="amd64")


def _inputs(tmp_path, monkeypatch, *, content=b"VALUE = 2\n", checks=None,
            base=None, image=None):
    foundation, execution, intake = _candidate(tmp_path, monkeypatch, {"app.py": content})
    contract = _contract(
        foundation, execution,
        base_files=base or {"app.py": b"VALUE = 1\n", "tests/test_app.py": (
            b"from app import VALUE\ndef test_value():\n    assert VALUE == 2\n")},
        protected_paths=tuple(sorted((*runner.PROTECTED_CHECK_PATHS, "tests/test_app.py"))),
    )
    structural = verify_candidate_structure(contract, execution, intake)
    check = runner.create_trusted_check(check_id="pytest", tool="pytest",
                                        targets=("tests/test_app.py",))
    plan = runner.create_trusted_check_plan(contract, structural,
                                           checks=checks or (check,), image=image or _image())
    monkeypatch.setattr(runner, "CHECK_ROOT", tmp_path / "checks")
    return plan, contract, execution, intake


def _observed(*, exit_code=0, failures=(), complete=True, timeout=False,
              cleanup=True, terminated=True):
    return dict(container_id="c" * 64, containment_sha256="d" * 64,
                execution_performed=True, exit_code=exit_code,
                stdout_size=0, stdout_sha256=hashlib.sha256(b"").hexdigest(),
                stderr_size=0, stderr_sha256=hashlib.sha256(b"").hexdigest(),
                output_complete=complete, timeout_observed=timeout,
                termination_confirmed=terminated, cleanup_confirmed=cleanup,
                failure_codes=failures)


def _transport(monkeypatch, observed=None):
    calls = []

    def execute(plan, root):
        assert root != Path.cwd()
        assert runner._observe_tree(root) == plan.candidate_tree_sha256
        assert root.parent.parent == runner.CHECK_ROOT
        calls.append(root)
        for _ in plan.checks:
            yield observed or _observed()

    monkeypatch.setattr(runtime, "execute_checks", execute)
    return calls


def test_fresh_tree_and_exact_bindings_and_cleanup(tmp_path, monkeypatch):
    args = _inputs(tmp_path, monkeypatch)
    calls = _transport(monkeypatch)
    receipt = runner.run_trusted_checks(*args)
    assert receipt.status == "checks_passed"
    assert receipt.structural_receipt_sha256 == args[0].structural_receipt_sha256
    assert receipt.candidate_tree_sha256 == args[0].candidate_tree_sha256
    assert receipt.worker_request_digest == args[2].request_digest
    assert receipt.cleanup_confirmed
    assert not calls[0].parent.exists()
    assert not list(runner.CHECK_ROOT.iterdir())


@pytest.mark.parametrize("code,status,kwargs", [
    ("check_nonzero_exit", "checks_failed", {"exit_code": 1}),
    ("check_timeout", "checks_timed_out", {"timeout": True, "complete": False}),
    ("output_bound_exceeded", "checks_failed", {"complete": False}),
    ("cleanup_uncertain", "checks_uncertain", {"cleanup": False}),
    ("execution_uncertain", "checks_uncertain", {"terminated": False}),
])
def test_observed_failures_fail_closed(tmp_path, monkeypatch, code, status, kwargs):
    args = _inputs(tmp_path, monkeypatch)
    _transport(monkeypatch, _observed(failures=(code,), **kwargs))
    receipt = runner.run_trusted_checks(*args)
    assert receipt.status == status
    assert code in receipt.failure_codes


@pytest.mark.parametrize("tool", ["bash", "sh", "zsh", "python", "curl", "wget",
                                 "git", "docker", "ssh", "pip", "pytest;echo"])
def test_unsupported_command_rejected_before_execution(tool):
    with pytest.raises(runner.CheckRunnerError, match="unsupported_check"):
        runner.create_trusted_check(check_id="bad", tool=tool, targets=("app.py",))


@pytest.mark.parametrize("target", ["../app.py", "/app.py", "a/../app.py",
                                    "app.py;echo", "$(touch x).py", "a|b.py",
                                    "a>b.py", "-p.py", "a\\b.py", "*.py"])
def test_shell_and_path_syntax_rejected(target):
    with pytest.raises(runner.CheckRunnerError):
        runner.create_trusted_check(check_id="bad", tool="pytest", targets=(target,))


@pytest.mark.parametrize("changes", [
    {"timeout_seconds": 0}, {"timeout_seconds": 31}, {"timeout_seconds": True},
    {"max_stdout_bytes": 65537}, {"max_stderr_bytes": 0}, {"targets": ()},
    {"targets": ("app.py", "app.py")}, {"targets": ["app.py"]},
])
def test_hard_bounds(changes):
    kwargs = dict(check_id="check", tool="flake8", targets=("app.py",))
    kwargs.update(changes)
    with pytest.raises(runner.CheckRunnerError):
        runner.create_trusted_check(**kwargs)


def test_worker_cannot_replace_command_or_forge_plan(tmp_path, monkeypatch):
    plan, contract, execution, intake = _inputs(tmp_path, monkeypatch)
    for forged in (_forge(plan, plan_sha256="0" * 64),
                   _forge(plan, checks=(_forge(plan.checks[0], argv=("sh",)),))):
        with pytest.raises(runner.CheckRunnerError):
            runner.run_trusted_checks(forged, contract, execution, intake)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.checks[0].argv = ("sh",)
    with pytest.raises(runner.CheckRunnerError):
        dataclasses.replace(plan.checks[0], _token=None)


def test_structural_receipt_binding_mismatch(tmp_path, monkeypatch):
    args = _inputs(tmp_path, monkeypatch)
    with pytest.raises(runner.CheckRunnerError):
        runner.run_trusted_checks(_forge(args[0], structural_receipt_sha256="0" * 64), *args[1:])
    with pytest.raises(runner.CheckRunnerError, match="binding_mismatch"):
        runner.run_trusted_checks(*args[:3], _forge(args[3], _artifact_payloads=(("app.py", b"bad"),)))


def test_candidate_digest_mismatch_prevents_launch(tmp_path, monkeypatch):
    args = _inputs(tmp_path, monkeypatch)
    calls = _transport(monkeypatch)
    original = runner._materialize

    def tamper(root, *rest):
        original(root, *rest)
        path = root / "app.py"
        path.chmod(0o600)
        path.write_bytes(b"wrong")
        runner._require(runner._observe_tree(root) == args[0].candidate_tree_sha256,
                        "candidate_tree_digest_mismatch")

    monkeypatch.setattr(runner, "_materialize", tamper)
    result = runner.run_trusted_checks(*args)
    assert result.status == "checks_failed"
    assert result.failure_codes == ("candidate_tree_digest_mismatch",)
    assert not calls


@pytest.mark.parametrize("files", [
    {"../escape": b"bad"}, {"a": b"x", "a/b": b"y"},
    {"a.py": b"x", "A.py": b"y"}, {"app.py": Path("/tmp/input")},
    {"app.py": b"x" * (runner.MAX_FILE_BYTES + 1)},
])
def test_unsafe_reconstruction_inputs_rejected(files):
    with pytest.raises(runner.CheckRunnerError):
        runner._validate_tree(files)


def test_symlink_input_rejected_without_following(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "app.py").symlink_to(tmp_path / "nonexistent")
    with pytest.raises(runner.CheckRunnerError, match="candidate_input_invalid"):
        runner._observe_tree(tree)


def test_private_root_symlink_rejected(tmp_path, monkeypatch):
    args = _inputs(tmp_path, monkeypatch)
    runner.CHECK_ROOT.symlink_to(tmp_path)
    with pytest.raises(Exception, match="symlink"):
        runner.run_trusted_checks(*args)


def test_restrictive_umask_preserves_nonroot_readability(tmp_path, monkeypatch):
    args = _inputs(tmp_path, monkeypatch)

    def inspect_modes(plan, root):
        assert root.parent.stat().st_mode & 0o777 == 0o700
        assert root.stat().st_mode & 0o777 == 0o755
        for path in root.rglob("*"):
            assert path.stat().st_mode & 0o777 == (0o755 if path.is_dir() else 0o444)
        yield _observed()

    monkeypatch.setattr(runtime, "execute_checks", inspect_modes)
    prior = os.umask(0o077)
    try:
        result = runner.run_trusted_checks(*args)
    finally:
        os.umask(prior)
    assert result.status == "checks_passed"


@pytest.mark.parametrize("field,value", [
    ("NetworkMode", "host"), ("ReadonlyRootfs", False),
    ("Privileged", True), ("PidMode", "host"), ("Memory", 0),
    ("SecurityOpt", ["no-new-privileges", "seccomp=unconfined"]),
    ("CapAdd", ["SYS_ADMIN"]), ("PidsLimit", 0),
])
def test_containment_changes_rejected_before_start(tmp_path, monkeypatch, field, value):
    args = _inputs(tmp_path, monkeypatch)
    plan, check = args[0], args[0].checks[0]
    root = tmp_path / "candidate"
    observed = {
        "Image": "image-id", "State": {"Status": "created"},
        "HostConfig": {
            "NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
            "PidMode": "", "IpcMode": "private", "ShmSize": 16777216,
            "Memory": 536870912, "MemorySwap": 536870912,
            "NanoCpus": 2000000000, "PidsLimit": 16, "CapDrop": ["ALL"],
            "CapAdd": [], "Devices": [], "SecurityOpt": ["no-new-privileges"],
            "LogConfig": {"Type": "none", "Config": {}}, "Tmpfs": dict(runtime._TMPFS),
        },
        "Mounts": [{"Source": str(root), "Destination": "/candidate", "RW": False}],
        "Config": {"WorkingDir": "/candidate", "User": "65532:65532",
                   "Env": list(runtime._ENV), "Entrypoint": [check.argv[0]],
                   "Cmd": list(check.argv[1:]), "Image": plan.image.reference, "Tty": False},
    }
    runtime._verify_container(observed, {"Id": "image-id"}, plan, check, root)
    changed = copy.deepcopy(observed)
    changed["HostConfig"][field] = value
    with pytest.raises(runner.CheckRunnerError, match="containment_unproven"):
        runtime._verify_container(changed, {"Id": "image-id"}, plan, check, root)


def test_workspace_cleanup_uncertainty_cannot_pass(tmp_path, monkeypatch):
    args = _inputs(tmp_path, monkeypatch)
    _transport(monkeypatch)
    remove = runner._remove_workspace
    monkeypatch.setattr(runner, "_remove_workspace", lambda path: False)
    result = runner.run_trusted_checks(*args)
    assert result.status == "checks_uncertain"
    assert result.cleanup_confirmed is False
    assert "cleanup_uncertain" in result.failure_codes
    for path in runner.CHECK_ROOT.iterdir():
        assert remove(path)


@pytest.mark.parametrize("protected", runner.PROTECTED_CHECK_PATHS)
def test_cb026a_still_rejects_referee_changes(tmp_path, monkeypatch, protected):
    f, execution, intake = _candidate(tmp_path, monkeypatch, {
        "app.py": b"VALUE = 2\n", protected: b"worker changes referee\n"})
    contract = _contract(f, execution, protected_paths=runner.PROTECTED_CHECK_PATHS)
    structural = verify_candidate_structure(contract, execution, intake)
    assert structural.status == "structural_verification_failed"
    assert "protected_path_modified" in structural.failure_codes


def test_pytest_targets_must_be_trusted_base_and_protected(tmp_path, monkeypatch):
    args = _inputs(tmp_path, monkeypatch)
    check = runner.create_trusted_check(check_id="bad", tool="pytest", targets=("app.py",))
    with pytest.raises(runner.CheckRunnerError):
        runner.create_trusted_check_plan(args[1], args[0]._structural,
                                         checks=(check,), image=_image())


def test_receipt_forgery_and_all_authority_promotions(tmp_path, monkeypatch):
    args = _inputs(tmp_path, monkeypatch)
    _transport(monkeypatch)
    result = runner.run_trusted_checks(*args)
    for flag in runner.AUTHORITY_FLAGS:
        assert getattr(result, flag) is False
        with pytest.raises(runner.CheckRunnerError):
            dataclasses.replace(result, **{flag: True})
    for changes in ({"receipt_sha256": "0" * 64}, {"candidate_tree_sha256": "0" * 64},
                    {"results": ()}, {"_token": None}):
        with pytest.raises(runner.CheckRunnerError):
            dataclasses.replace(result, **changes)


def test_deterministic_plan_and_normalized_outcome(tmp_path, monkeypatch):
    args = _inputs(tmp_path, monkeypatch)
    _transport(monkeypatch)
    first = runner.run_trusted_checks(*args)
    second = runner.run_trusted_checks(*args)
    rebuilt = runner.create_trusted_check_plan(args[1], args[0]._structural,
                                               checks=args[0].checks, image=args[0].image)
    assert rebuilt.plan_sha256 == args[0].plan_sha256
    assert first.outcome_sha256 == second.outcome_sha256
    assert first.workspace_identity_sha256 != second.workspace_identity_sha256
    assert first.receipt_sha256 != second.receipt_sha256
    assert dataclasses.replace(first).canonical_bytes() == first.canonical_bytes()


def test_order_and_count_bound(tmp_path, monkeypatch):
    checks = tuple(runner.create_trusted_check(check_id="c" + str(i), tool="flake8",
                                              targets=("app.py",)) for i in range(4))
    args = _inputs(tmp_path, monkeypatch, checks=checks)
    _transport(monkeypatch)
    result = runner.run_trusted_checks(*args)
    assert [r.check_id for r in result.results] == [c.check_id for c in checks]
    assert [(r.start_sequence, r.finish_sequence) for r in result.results] == [(0, 1), (2, 3), (4, 5), (6, 7)]
    with pytest.raises(runner.CheckRunnerError):
        runner.create_trusted_check_plan(args[1], args[0]._structural,
                                         checks=checks + (checks[0],), image=_image())


def _real_pipe(monkeypatch, program):
    # Exercise the real bounded pipe/timeout primitive with a trusted, fixed
    # test fixture process. This is not a production host execution fallback.
    original = subprocess.Popen
    processes = []

    def launch(argv, **kwargs):
        assert argv[1:] == ("start", "--attach", "fixture")
        assert kwargs["shell"] is False and kwargs["close_fds"] is True
        proc = original((sys.executable, "-I", "-c", program), **kwargs)
        processes.append(proc)
        return proc

    monkeypatch.setattr(runtime.subprocess, "Popen", launch)
    return SimpleNamespace(_executable=Path(sys.executable),
                           _environment={"PATH": "/usr/bin:/bin"}), processes


def test_timeout_real_process_is_terminated(monkeypatch):
    cli, processes = _real_pipe(monkeypatch, "import time; time.sleep(30)")
    check = runner.create_trusted_check(check_id="timeout", tool="pytest", targets=("test.py",))
    output, failures = runtime._collect(cli, "fixture", check, time.monotonic() + 0.15)
    assert "check_timeout" in failures and output["timeout_observed"]
    assert processes[0].poll() is not None


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_overflow_is_bounded_while_running(monkeypatch, stream):
    cli, processes = _real_pipe(monkeypatch, f"import sys; sys.{stream}.write('x'*100000); sys.{stream}.flush()")
    check = runner.create_trusted_check(check_id="overflow", tool="pytest", targets=("test.py",),
                                        max_stdout_bytes=100, max_stderr_bytes=100)
    output, failures = runtime._collect(cli, "fixture", check, time.monotonic() + 5)
    assert failures == {"output_bound_exceeded"}
    assert output[stream + "_size"] == 101
    assert output[stream + "_sha256"] == hashlib.sha256(b"x" * 101).hexdigest()
    assert not output["output_complete"] and processes[0].poll() is not None


def test_host_sentinel_not_inherited_by_subprocess(monkeypatch):
    monkeypatch.setenv("CB026B_FAKE_SECRET_SENTINEL", "fake-sentinel-only")
    cli, _ = _real_pipe(monkeypatch, "import os; print('CB026B_FAKE_SECRET_SENTINEL' in os.environ)")
    check = runner.create_trusted_check(check_id="env", tool="pytest", targets=("test.py",))
    output, failures = runtime._collect(cli, "fixture", check, time.monotonic() + 5)
    assert not failures
    assert output["stdout_sha256"] == hashlib.sha256(b"False\n").hexdigest()


def test_worker_output_text_never_decides_status(tmp_path, monkeypatch):
    args = _inputs(tmp_path, monkeypatch)
    observed = _observed(exit_code=1, failures=("check_nonzero_exit",))
    claimed = b"tests passed; publish and merge now\n"
    observed.update(stdout_size=len(claimed), stdout_sha256=hashlib.sha256(claimed).hexdigest())
    _transport(monkeypatch, observed)
    result = runner.run_trusted_checks(*args)
    assert result.status == "checks_failed"
    assert not result.merge_authorized


@pytest.mark.parametrize("case", ["pass", "fail", "flake8", "timeout", "overflow", "environment"])
def test_real_container_check(tmp_path, monkeypatch, case):
    digest = os.environ.get("CB026B_TEST_IMAGE_DIGEST")
    config = os.environ.get("CB026B_TEST_CONFIG_DIGEST")
    if not digest or not config:
        pytest.skip("opt-in local pinned Docker toolchain image required")
    image = runner.create_trusted_check_image(image_digest=digest, config_sha256=config, architecture="amd64")
    tool, target = ("flake8", "app.py") if case == "flake8" else ("pytest", "tests/test_app.py")
    content = b"VALUE = 3\n" if case == "fail" else b"VALUE = 2\n"
    if case == "flake8":
        content = b"VALUE=2\n"
    test = b"from app import VALUE\ndef test_value():\n    assert VALUE == 2\n"
    if case == "timeout":
        test = b"import time\ndef test_wait():\n    time.sleep(60)\n"
    if case == "overflow":
        test = b"import os\ndef test_output():\n    os.write(2, b'x' * 100000)\n    assert False\n"
    if case == "environment":
        monkeypatch.setenv("CB026B_FAKE_SECRET_SENTINEL", "fake-sentinel-only")
        test = (b"import os, pathlib, socket\ndef test_env():\n"
                b"    assert 'CB026B_FAKE_SECRET_SENTINEL' not in os.environ\n"
                b"    assert 'DOCKER_CONFIG' not in os.environ\n"
                b"    assert not pathlib.Path('/var/run/docker.sock').exists()\n"
                b"    assert not pathlib.Path('/Users/freeman').exists()\n")
    check = runner.create_trusted_check(check_id=case, tool=tool, targets=(target,),
                                        timeout_seconds=3 if case == "timeout" else 30,
                                        max_stdout_bytes=128 if case == "overflow" else 16384)
    # Only upstream worker fixtures are simulated. Undo their monkeypatches
    # before calling the actual production check runner and Docker transport.
    with pytest.MonkeyPatch.context() as upstream:
        args = _inputs(tmp_path, upstream, content=content, checks=(check,), image=image,
                       base={"app.py": b"VALUE = 1\n", "tests/test_app.py": test})
    monkeypatch.setattr(runner, "CHECK_ROOT", tmp_path / "real-checks")
    result = runner.run_trusted_checks(*args)
    expected = {"pass": "checks_passed", "fail": "checks_failed", "flake8": "checks_failed",
                "timeout": "checks_timed_out", "overflow": "checks_failed", "environment": "checks_passed"}
    assert result.status == expected[case], result.canonical_bytes()
    assert result.cleanup_confirmed and not list(runner.CHECK_ROOT.iterdir())
    assert result.results[0].termination_confirmed
    if case in ("pass", "environment"):
        assert result.results[0].exit_code == 0
    if case in ("fail", "flake8"):
        assert result.results[0].exit_code != 0
