import ast
import hashlib
import json
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from backend.continuous_builder.docker_runtime_contract import (
    create_docker_runtime_descriptor,
    create_pinned_offline_worker_image,
)
from backend.continuous_builder.repository_materialization import (
    create_planned_materialization_receipt,
    create_repository_materialization_contract,
)
from backend.continuous_builder.runtime_enforcement import (
    create_prepared_execution_handle_contract,
    create_runtime_cancellation_semantics,
    create_docker_enforcement_contract,
    create_runtime_foundation_readiness,
    default_docker_enforcement_controls,
)
from backend.continuous_builder.sandbox_policy import (
    evaluate_containment_preflight,
)
from backend.continuous_builder.sandbox_repository import (
    RepositoryManifestEntry,
    create_disposable_repository_plan,
    create_repository_source_evidence,
)
from backend.continuous_builder.worker_runtime import (
    DockerWorkerRuntime,
    RuntimeEnforcementEvidence,
    VerifiedMaterializationReceipt,
    WorkerRuntimeError,
    _CommandResult,
)
import backend.continuous_builder.worker_runtime as worker_runtime
from tests.test_continuous_builder_sandbox_policy import (
    _policy, _provider, _resources,
)
from tests.test_continuous_builder_worker_action import _action


CONTENT = b"offline source\n"
CONFIG_DIGEST = "b" * 64
IMAGE_DIGEST = "sha256:" + "a" * 64
CONTAINER_ID = "c" * 64


def _foundation(resources=None):
    action = _action()
    request = action.authorization.request
    entry = RepositoryManifestEntry(
        "source.txt",
        "regular_file",
        hashlib.sha256(CONTENT).hexdigest(),
        len(CONTENT),
    )
    source = create_repository_source_evidence(
        "mootos-source", request.job.base_sha, (entry,)
    )
    plan = create_disposable_repository_plan(
        request, source, "disposable-attempt-1"
    )
    policy = _policy(plan, **({"resources": resources} if resources else {}))
    provider = _provider()
    preflight = evaluate_containment_preflight(provider, plan, policy)
    materialization = create_planned_materialization_receipt(
        create_repository_materialization_contract(
            plan, "materialization-attempt-1"
        )
    )
    runtime = create_docker_runtime_descriptor(
        "docker-local-v1",
        provider.provider_id,
        "mootos-supervisor-docker",
        "28.4.0",
        "1.51",
        "linux",
        "amd64",
    )
    image = create_pinned_offline_worker_image(
        "mootos/offline-fixture-worker",
        IMAGE_DIGEST,
        "linux",
        "amd64",
        CONFIG_DIGEST,
    )
    enforcement = create_docker_enforcement_contract(
        runtime, image, policy, default_docker_enforcement_controls()
    )
    return create_runtime_foundation_readiness(
        action, preflight, materialization, enforcement
    )


class FakeDocker:
    def __init__(
        self,
        *,
        image_present=True,
        exit_code=0,
        logs=b'{"reported":"success"}\n',
        stop_succeeds=True,
        kill_succeeds=True,
        inspect_disappears=False,
        enforcement_changes=None,
    ):
        self.image_present = image_present
        self.exit_code = exit_code
        self.logs = logs
        self.stop_succeeds = stop_succeeds
        self.kill_succeeds = kill_succeeds
        self.inspect_disappears = inspect_disappears
        self.enforcement_changes = enforcement_changes or {}
        self.commands = []
        self.created_arguments = None
        self.started = False
        self.cancelled = False
        self.polls = 0

    def run(self, arguments, timeout):
        assert type(arguments) is tuple
        assert timeout > 0
        self.commands.append(arguments)
        if arguments[0] == "version":
            return _CommandResult(0, json.dumps({
                "Version": "28.4.0",
                "ApiVersion": "1.51",
                "Os": "linux",
                "Arch": "amd64",
            }).encode(), b"")
        if arguments[:2] == ("image", "inspect"):
            if not self.image_present:
                return _CommandResult(1, b"", b"image absent")
            return _CommandResult(0, json.dumps([{
                "Id": "sha256:" + CONFIG_DIGEST,
                "RepoDigests": [
                    "mootos/offline-fixture-worker@" + IMAGE_DIGEST
                ],
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "Entrypoint": [
                        "/opt/mootos/bin/offline-fixture-worker"
                    ],
                    "Cmd": None,
                },
            }]).encode(), b"")
        if arguments[0] == "create":
            self.created_arguments = arguments
            return _CommandResult(0, (CONTAINER_ID + "\n").encode(), b"")
        if arguments[0] == "start":
            self.started = True
            return _CommandResult(0, (CONTAINER_ID + "\n").encode(), b"")
        if arguments[0] == "inspect":
            if self.inspect_disappears and self.started:
                return _CommandResult(1, b"", b"not found")
            return _CommandResult(0, json.dumps([
                self._container_inspection()
            ]).encode(), b"")
        if arguments[0] == "logs":
            return _CommandResult(0, self.logs, b"fixture stderr")
        if arguments[0] == "stop":
            if not self.stop_succeeds:
                return _CommandResult(1, b"", b"stop failed")
            self.cancelled = True
            return _CommandResult(0, (CONTAINER_ID + "\n").encode(), b"")
        if arguments[0] == "kill":
            if not self.kill_succeeds:
                return _CommandResult(1, b"", b"kill failed")
            self.cancelled = True
            return _CommandResult(0, (CONTAINER_ID + "\n").encode(), b"")
        if arguments[:2] == ("rm", "--force"):
            return _CommandResult(0, CONTAINER_ID.encode(), b"")
        raise AssertionError(f"unexpected Docker arguments: {arguments}")

    def _container_inspection(self):
        arguments = self.created_arguments
        mount_value = arguments[arguments.index("--mount") + 1]
        source = mount_value.split("src=", 1)[1].split(",", 1)[0]
        memory = int(arguments[arguments.index("--memory") + 1])
        cpus = float(arguments[arguments.index("--cpus") + 1])
        pids = int(arguments[arguments.index("--pids-limit") + 1])
        tmpfs_values = [
            arguments[index + 1]
            for index, value in enumerate(arguments)
            if value == "--tmpfs"
        ]
        tmpfs = {
            value.split(":", 1)[0]: value.split(":", 1)[1]
            for value in tmpfs_values
        }
        if not self.started:
            state = {
                "Status": "created",
                "Running": False,
                "ExitCode": 0,
                "FinishedAt": "",
                "Dead": False,
                "OOMKilled": False,
            }
        elif self.cancelled:
            state = {
                "Status": "exited",
                "Running": False,
                "ExitCode": 143,
                "FinishedAt": "2026-01-01T00:00:02Z",
                "Dead": False,
                "OOMKilled": False,
            }
        else:
            self.polls += 1
            running = self.polls == 1
            state = {
                "Status": "running" if running else "exited",
                "Running": running,
                "ExitCode": self.exit_code,
                "FinishedAt": "" if running else "2026-01-01T00:00:01Z",
                "Dead": False,
                "OOMKilled": False,
            }
        value = {
            "Id": CONTAINER_ID,
            "Image": "sha256:" + CONFIG_DIGEST,
            "State": state,
            "Config": {
                "Env": ["LANG=C.UTF-8", "LC_ALL=C.UTF-8", "PYTHONHASHSEED=0"],
                "User": "65532:65532",
                "Entrypoint": [
                    "/opt/mootos/bin/offline-fixture-worker"
                ],
                "Image": "mootos/offline-fixture-worker@" + IMAGE_DIGEST,
            },
            "HostConfig": {
                "NetworkMode": "none",
                "Privileged": False,
                "ReadonlyRootfs": True,
                "PidMode": "",
                "IpcMode": "private",
                "Memory": memory,
                "NanoCpus": int(cpus * 1000000000),
                "PidsLimit": pids,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Tmpfs": tmpfs,
            },
            "Mounts": [{
                "Source": source,
                "Destination": "/source",
                "RW": False,
            }],
        }
        for path, changed in self.enforcement_changes.items():
            target = value
            pieces = path.split(".")
            for piece in pieces[:-1]:
                target = target[piece]
            target[pieces[-1]] = changed
        return value


def _execute(tmp_path, monkeypatch, fake=None, foundation=None, **changes):
    monkeypatch.setattr(worker_runtime, "RUNTIME_ROOT", tmp_path / "runtime")
    runtime = DockerWorkerRuntime(poll_interval=0)
    fake = fake or FakeDocker()
    runtime._docker = fake
    foundation = foundation or _foundation()
    values = {
        "foundation": foundation,
        "source_files": {"source.txt": CONTENT},
        "execution_handle": create_prepared_execution_handle_contract(
            foundation, "execution-1", "supervisor:mootos"
        ),
    }
    values.update(changes)
    return runtime.execute(**values), fake


def _forge(instance, **changes):
    forged = object.__new__(type(instance))
    for item in fields(instance):
        object.__setattr__(
            forged,
            item.name,
            changes.get(item.name, getattr(instance, item.name)),
        )
    return forged


def test_successful_offline_worker_is_contained_and_untrusted(
    tmp_path, monkeypatch,
):
    receipt, fake = _execute(tmp_path, monkeypatch)
    assert receipt.final_state == "succeeded"
    assert receipt.lifecycle_states == (
        "prepared", "launching", "running", "succeeded"
    )
    assert receipt.exit_code == 0
    assert receipt.result_verified is False
    assert receipt.execution_performed is True
    assert receipt.runtime_isolation_verified is True
    assert receipt.materialization_verified is True
    assert receipt.worker_output_trusted is False
    assert receipt.patch_verified is False
    assert receipt.externally_verified is False
    assert receipt.publication_authorized is False
    assert receipt.queue_transition_authorized is False
    assert receipt.github_authorized is False
    assert receipt.materialization_receipt.materialization_verified is True
    assert receipt.materialization_receipt.materialization_performed is True
    assert receipt.enforcement_evidence.runtime_isolation_verified is True
    assert receipt.enforcement_evidence.execution_performed is False
    assert receipt.cleanup_confirmed is True
    assert list((tmp_path / "runtime").iterdir()) == []
    create = fake.created_arguments
    assert create[create.index("--network") + 1] == "none"
    assert "--privileged" not in create
    assert "--pid" not in create
    assert "--ipc" not in create
    assert "/var/run/docker.sock" not in " ".join(create)
    assert "--read-only" in create
    assert "--pids-limit" in create
    assert "--memory" in create
    assert "--cpus" in create
    assert "--tmpfs" in create
    with pytest.raises(FrozenInstanceError):
        receipt.final_state = "failed"


@pytest.mark.parametrize(
    "field",
    (
        "action_digest",
        "authorization_digest",
        "request_digest",
        "attempt_id",
        "worker_provider_id",
        "sandbox_provider_id",
        "policy_digest",
        "reconstruction_plan_digest",
        "materialization_receipt_digest",
        "runtime_descriptor_digest",
        "image_contract_digest",
        "pinned_base_sha",
    ),
)
def test_stale_runtime_binding_is_rejected_before_execution(
    tmp_path, monkeypatch, field,
):
    foundation = _foundation()
    value = "wrong" if not field.endswith("digest") else "0" * 64
    if field == "pinned_base_sha":
        value = "b" * 40
    forged = _forge(foundation, **{field: value})
    fake = FakeDocker()
    with pytest.raises(WorkerRuntimeError, match="binding mismatch"):
        _execute(
            tmp_path, monkeypatch, fake=fake, foundation=forged,
        )
    assert fake.commands == []


def test_missing_local_image_fails_closed_and_cleans_workspace(
    tmp_path, monkeypatch,
):
    with pytest.raises(WorkerRuntimeError, match="image inspection failed"):
        _execute(tmp_path, monkeypatch, fake=FakeDocker(image_present=False))
    assert list((tmp_path / "runtime").iterdir()) == []


def test_runtime_identity_mismatch_fails_before_image_or_launch(
    tmp_path, monkeypatch,
):
    class WrongRuntime(FakeDocker):
        def run(self, arguments, timeout):
            if arguments[0] == "version":
                self.commands.append(arguments)
                return _CommandResult(0, json.dumps({
                    "Version": "unexpected",
                    "ApiVersion": "1.51",
                    "Os": "linux",
                    "Arch": "amd64",
                }).encode(), b"")
            return super().run(arguments, timeout)

    fake = WrongRuntime()
    with pytest.raises(WorkerRuntimeError, match="runtime identity mismatch"):
        _execute(tmp_path, monkeypatch, fake=fake)
    assert not any(command[0] == "create" for command in fake.commands)


@pytest.mark.parametrize(
    "change",
    (
        {"HostConfig.NetworkMode": "host"},
        {"HostConfig.Privileged": True},
        {"HostConfig.PidMode": "host"},
        {"HostConfig.IpcMode": "host"},
        {"HostConfig.Memory": 0},
        {"HostConfig.NanoCpus": 0},
        {"HostConfig.PidsLimit": 0},
        {"HostConfig.ReadonlyRootfs": False},
        {"Mounts": []},
        {"Config.Env": ["GITHUB_TOKEN=bad"]},
    ),
)
def test_missing_runtime_enforcement_fails_before_start(
    tmp_path, monkeypatch, change,
):
    fake = FakeDocker(enforcement_changes=change)
    with pytest.raises(WorkerRuntimeError, match="containment inspection"):
        _execute(tmp_path, monkeypatch, fake=fake)
    assert not any(command[0] == "start" for command in fake.commands)


def test_materialization_mismatch_and_extra_file_fail_before_docker(
    tmp_path, monkeypatch,
):
    for files in (
        {"source.txt": b"wrong"},
        {"source.txt": CONTENT, "extra.txt": b"extra"},
    ):
        fake = FakeDocker()
        with pytest.raises(WorkerRuntimeError):
            _execute(
                tmp_path,
                monkeypatch,
                fake=fake,
                source_files=files,
            )
        assert fake.commands == []


def test_existing_or_symlinked_workspace_identity_fails_closed(
    tmp_path, monkeypatch,
):
    foundation = _foundation()
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    runtime_root.chmod(0o700)
    instance = "execution-" + hashlib.sha256(
        foundation.materialization_receipt.receipt_sha256.encode("ascii")
    ).hexdigest()[:24]
    (runtime_root / instance).symlink_to(tmp_path)
    fake = FakeDocker()
    with pytest.raises(WorkerRuntimeError, match="already exists"):
        _execute(
            tmp_path, monkeypatch, fake=fake, foundation=foundation,
        )
    assert fake.commands == []


def test_materialization_receipt_cannot_be_caller_fabricated():
    with pytest.raises(WorkerRuntimeError, match="trusted observed evidence"):
        VerifiedMaterializationReceipt(
            "materialization-1",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "d" * 64,
            "attempt-1",
            "e" * 40,
            "f" * 64,
            "c" * 64,
            1,
            1,
            "0" * 64,
        )


def test_runtime_enforcement_cannot_be_caller_fabricated():
    with pytest.raises(WorkerRuntimeError, match="trusted observed evidence"):
        RuntimeEnforcementEvidence(
            CONTAINER_ID,
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "d" * 64,
            "e" * 64,
            "f" * 64,
            "1" * 64,
            "0" * 64,
        )


def test_bounded_cancellation_confirms_exact_container(
    tmp_path, monkeypatch,
):
    foundation = _foundation()
    handle = create_prepared_execution_handle_contract(
        foundation, "execution-1", "supervisor:mootos"
    )
    cancellation = create_runtime_cancellation_semantics(
        "cancel-1", handle
    )
    receipt, fake = _execute(
        tmp_path,
        monkeypatch,
        foundation=foundation,
        execution_handle=handle,
        cancellation_semantics=cancellation,
    )
    assert receipt.final_state == "cancelled"
    assert receipt.cancellation_requested is True
    assert receipt.cancellation_confirmed is True
    assert receipt.termination_uncertain is False
    stop = next(command for command in fake.commands if command[0] == "stop")
    assert stop[-1] == CONTAINER_ID


def test_uncertain_cancellation_never_claims_stopped(tmp_path, monkeypatch):
    foundation = _foundation()
    handle = create_prepared_execution_handle_contract(
        foundation, "execution-1", "supervisor:mootos"
    )
    cancellation = create_runtime_cancellation_semantics(
        "cancel-1", handle
    )
    receipt, _ = _execute(
        tmp_path,
        monkeypatch,
        foundation=foundation,
        fake=FakeDocker(stop_succeeds=False, kill_succeeds=False),
        execution_handle=handle,
        cancellation_semantics=cancellation,
    )
    assert receipt.final_state == "termination_uncertain"
    assert receipt.cancellation_confirmed is False
    assert receipt.termination_uncertain is True


def test_wall_timeout_is_supervisor_enforced(tmp_path, monkeypatch):
    ticks = iter((0.0, 2.0))
    monkeypatch.setattr(worker_runtime.time, "monotonic", lambda: next(ticks))
    receipt, fake = _execute(
        tmp_path,
        monkeypatch,
        foundation=_foundation(resources=_resources(max_wall_seconds=1)),
    )
    assert receipt.final_state == "timed_out"
    assert receipt.timeout_observed is True
    assert any(command[0] == "stop" for command in fake.commands)


def test_container_disappearance_is_uncertain_not_success(
    tmp_path, monkeypatch,
):
    receipt, _ = _execute(
        tmp_path,
        monkeypatch,
        fake=FakeDocker(inspect_disappears=True),
    )
    assert receipt.final_state == "termination_uncertain"
    assert receipt.exit_code is None


def test_output_over_bound_fails_closed(tmp_path, monkeypatch):
    fake = FakeDocker(logs=b"x" * (1024 * 1024 + 1))
    with pytest.raises(WorkerRuntimeError, match="output exceeds bound"):
        _execute(tmp_path, monkeypatch, fake=fake)


def test_policy_output_bound_fails_closed(tmp_path, monkeypatch):
    fake = FakeDocker(logs=b"x" * 65537)
    with pytest.raises(WorkerRuntimeError, match="policy bound"):
        _execute(tmp_path, monkeypatch, fake=fake)


def test_cleanup_failure_is_explicit(tmp_path, monkeypatch):
    original = worker_runtime._remove_workspace

    def remove_but_report_uncertain(path):
        original(path)
        return False

    monkeypatch.setattr(
        worker_runtime, "_remove_workspace", remove_but_report_uncertain
    )
    receipt, _ = _execute(tmp_path, monkeypatch)
    assert receipt.cleanup_confirmed is False


def test_shell_like_execution_identity_is_rejected_before_docker(
    tmp_path, monkeypatch,
):
    fake = FakeDocker()
    with pytest.raises(WorkerRuntimeError, match="execution handle contract"):
        _execute(
            tmp_path,
            monkeypatch,
            fake=fake,
            execution_handle="execution-1;docker run attacker",
        )
    assert fake.commands == []


def test_fixture_worker_is_deterministic_and_has_no_network_or_commands(
    tmp_path, monkeypatch,
):
    source = tmp_path / "source"
    workspace = tmp_path / "workspace"
    source.mkdir()
    workspace.mkdir()
    (source / "source.txt").write_bytes(CONTENT)
    from backend.continuous_builder import offline_fixture_worker

    monkeypatch.setattr(offline_fixture_worker, "SOURCE_ROOT", source)
    monkeypatch.setattr(offline_fixture_worker, "WORKSPACE_ROOT", workspace)
    assert offline_fixture_worker.main((
        "attempt-1", "a" * 64, str(workspace),
    )) == 0


def test_runtime_module_uses_only_narrow_subprocess_boundary():
    source = Path(
        "backend/continuous_builder/worker_runtime.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "subprocess" in imports
    assert not imports & {
        "socket", "requests", "httpx", "urllib", "docker", "podman",
        "kubernetes", "paramiko", "fabric", "pexpect", "github",
        "keyring",
    }
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "run" in calls
    assert "system" not in calls
    assert "Popen" not in calls
    assert "shell=True" not in source.replace(" ", "")
