"""Supervisor-only Docker transport for CB-026B's two fixed check commands.

No candidate code runs on the host. Reuses CB-022's fixed Docker executable,
private credential-free CLI environment and bounded control calls. Attached
output is drained incrementally; Docker logging is disabled to bound disk use.
"""

import hashlib
import os
import re
import selectors
import signal
import subprocess
import time

from .worker_runtime import _DockerCli, WorkerRuntimeError, CONTAINER_PATH
from .check_runner import (
    CheckRunnerError, MAX_TOTAL_SECONDS, _canonical, _digest, _observe_tree,
    _require,
)


_ENV = (
    "HOME=/tmp", "LANG=C.UTF-8", "LC_ALL=C.UTF-8",
    "PATH=" + CONTAINER_PATH, "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
    "PYTHONDONTWRITEBYTECODE=1", "PYTHONHASHSEED=0", "TMPDIR=/tmp",
)
_TMPFS = {
    "/tmp": "rw,nosuid,nodev,noexec,size=16777216,nr_inodes=1024,uid=65532,gid=65532,mode=0700",
}
_MEMORY = 512 * 1024 * 1024
_PIDS = 16


def _control(cli, argv, timeout=5):
    result = cli.run(tuple(argv), timeout)
    _require(result.returncode == 0, "execution_uncertain")
    return result.stdout


def _json(raw):
    import json
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as error:
        raise CheckRunnerError("execution_uncertain") from error


def _inspect(cli, name):
    value = _json(_control(cli, ("inspect", name)))
    _require(type(value) is list and len(value) == 1, "execution_uncertain")
    return value[0]


def _image(cli, image):
    values = _json(_control(cli, ("image", "inspect", image.reference)))
    _require(type(values) is list and len(values) == 1, "containment_unproven")
    observed = values[0]
    config = observed.get("Config") or {}
    descriptor = observed.get("Descriptor") or {}
    config_id = (descriptor.get("annotations") or {}).get(
        "config.digest", observed.get("Id"))
    _require(image.reference in (observed.get("RepoDigests") or [])
             and config_id == "sha256:" + image.config_sha256
             and (not descriptor or descriptor.get("digest") == "sha256:" + image.image_digest)
             and observed.get("Os") == "linux"
             and observed.get("Architecture") == image.architecture
             and config.get("Entrypoint") == ["/usr/local/bin/python3"]
             and config.get("Cmd") in (None, [])
             and config.get("Env") == ["PATH=" + CONTAINER_PATH]
             and not config.get("Volumes") and not config.get("OnBuild"),
             "containment_unproven")
    return observed


def _create_argv(plan, check, root, name):
    argv = [
        "create", "--pull=never", "--name", name,
        "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true", "--user=65532:65532",
        "--pids-limit=" + str(_PIDS), "--memory=" + str(_MEMORY),
        "--memory-swap=" + str(_MEMORY), "--cpus=2.000",
        "--ipc=private", "--shm-size=16777216", "--log-driver=none",
        "--mount", "type=bind,src=" + str(root) + ",dst=/candidate,readonly",
        "--tmpfs", "/tmp:" + _TMPFS["/tmp"], "--workdir=/candidate",
    ]
    for value in _ENV:
        argv.extend(("--env", value))
    argv.extend(("--entrypoint", check.argv[0], plan.image.reference))
    argv.extend(check.argv[1:])
    return tuple(argv)


def _verify_container(observed, image, plan, check, root):
    host = observed.get("HostConfig") or {}
    config = observed.get("Config") or {}
    mounts = observed.get("Mounts") or []
    security = set(host.get("SecurityOpt") or [])
    _require(
        (observed.get("State") or {}).get("Status") == "created"
        and observed.get("Image") == image.get("Id")
        and host.get("NetworkMode") == "none"
        and host.get("ReadonlyRootfs") is True
        and host.get("Privileged") is False
        and host.get("PidMode") in ("", None)
        and host.get("IpcMode") == "private"
        and host.get("ShmSize") == 16777216
        and host.get("Memory") == _MEMORY
        and host.get("MemorySwap") == _MEMORY
        and host.get("NanoCpus") == 2000000000
        and host.get("PidsLimit") == _PIDS
        and set(host.get("CapDrop") or []) == {"ALL"}
        and not host.get("CapAdd") and not host.get("Devices")
        and security in ({"no-new-privileges"}, {"no-new-privileges:true"})
        and host.get("LogConfig") == {"Type": "none", "Config": {}}
        and host.get("Tmpfs") == _TMPFS
        and len(mounts) == 1 and mounts[0].get("Source") == str(root)
        and mounts[0].get("Destination") == "/candidate"
        and mounts[0].get("RW") is False
        and config.get("WorkingDir") == check.working_directory
        and config.get("User") == "65532:65532"
        and set(config.get("Env") or []) == set(_ENV)
        and config.get("Entrypoint") == [check.argv[0]]
        and config.get("Cmd") == list(check.argv[1:])
        and config.get("Image") == plan.image.reference
        and config.get("Tty") is False,
        "containment_unproven",
    )


def _stop(cli, name):
    """Stop/kill the whole container, including descendants that call setsid."""
    try:
        cli.run(("stop", "--time=1", name), 3)
        state = _inspect(cli, name).get("State") or {}
        if state.get("Running") is False and state.get("Status") in ("exited", "created", "dead"):
            return True
    except (WorkerRuntimeError, CheckRunnerError):
        pass
    try:
        cli.run(("kill", name), 3)
        state = _inspect(cli, name).get("State") or {}
        return state.get("Running") is False and state.get("Status") in ("exited", "created", "dead")
    except (WorkerRuntimeError, CheckRunnerError):
        return False


def _cleanup_container(cli, name):
    try:
        cli.run(("rm", "--force", name), 5)
        remaining = _control(cli, (
            "ps", "-a", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}",
        ))
        return remaining.strip() == b""
    except (WorkerRuntimeError, CheckRunnerError):
        return False


def _collect(cli, name, check, deadline):
    """Bound memory and both pipes while they are being produced, not afterward."""
    hashes = [hashlib.sha256(), hashlib.sha256()]
    sizes = [0, 0]
    limits = [check.max_stdout_bytes, check.max_stderr_bytes]
    failures = set()
    proc = None
    selector = selectors.DefaultSelector()
    try:
        proc = subprocess.Popen(
            (str(cli._executable), "start", "--attach", name),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, close_fds=True, start_new_session=True,
            env=dict(cli._environment),
        )
        for index, stream in enumerate((proc.stdout, proc.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, index)
        while selector.get_map() or proc.poll() is None:
            if time.monotonic() >= deadline:
                failures.add("check_timeout")
                break
            for key, _ in selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                index = key.data
                try:
                    chunk = os.read(key.fd, min(8192, limits[index] + 1 - sizes[index]))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                sizes[index] += len(chunk)
                hashes[index].update(chunk)
                if sizes[index] > limits[index]:
                    failures.add("output_bound_exceeded")
                    break
            if failures:
                break
        if not failures and proc.wait(timeout=1) not in (0, 1, 2, 3, 4, 5):
            failures.add("execution_uncertain")
    except (OSError, subprocess.SubprocessError):
        failures.add("execution_uncertain")
    finally:
        if proc is not None:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=0.5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=1)
                    except (ProcessLookupError, subprocess.TimeoutExpired):
                        failures.add("execution_uncertain")
            for stream in (proc.stdout, proc.stderr):
                stream.close()
        selector.close()
    return {
        "stdout_size": sizes[0], "stdout_sha256": hashes[0].hexdigest(),
        "stderr_size": sizes[1], "stderr_sha256": hashes[1].hexdigest(),
        "output_complete": not failures,
        "timeout_observed": "check_timeout" in failures,
    }, failures


def _execute_one(cli, image, plan, check, root, index, deadline):
    name = "cb026b-" + _digest((str(root) + str(index)).encode())[:24]
    result = {
        "container_id": "", "containment_sha256": _digest(b"unproven"),
        "execution_performed": False, "exit_code": None,
        "stdout_size": 0, "stdout_sha256": _digest(b""),
        "stderr_size": 0, "stderr_sha256": _digest(b""),
        "output_complete": False, "timeout_observed": False,
        "termination_confirmed": False, "cleanup_confirmed": False,
    }
    failures = set()
    try:
        _require(time.monotonic() < deadline, "check_timeout")
        raw_id = _control(cli, _create_argv(plan, check, root, name))
        container_id = raw_id.decode("ascii").strip()
        _require(re.fullmatch(r"[0-9a-f]{64}", container_id) is not None,
                 "execution_uncertain")
        result["container_id"] = container_id
        inspected = _inspect(cli, name)
        _require(inspected.get("Id") == container_id, "containment_unproven")
        _verify_container(inspected, image, plan, check, root)
        result["containment_sha256"] = _digest(_canonical(inspected))
        _require(_observe_tree(root) == plan.candidate_tree_sha256,
                 "candidate_tree_digest_mismatch")
        _require(time.monotonic() < deadline, "check_timeout")
        output, stream_failures = _collect(cli, name, check, deadline)
        result.update(output)
        failures.update(stream_failures)
        if failures:
            _stop(cli, name)
        state = _inspect(cli, name).get("State") or {}
        result["execution_performed"] = bool(state.get("StartedAt")) and not str(
            state.get("StartedAt")).startswith("0001-")
        result["termination_confirmed"] = state.get("Running") is False and (
            state.get("Status") == "exited")
        result["exit_code"] = state.get("ExitCode")
        if not result["execution_performed"] or not result["termination_confirmed"]:
            failures.add("execution_uncertain")
        if result["exit_code"] not in check.expected_exit_codes:
            failures.add("check_nonzero_exit")
        if state.get("OOMKilled") or state.get("Error"):
            failures.add("execution_uncertain")
    except CheckRunnerError as error:
        failures.add(error.code)
    except (WorkerRuntimeError, OSError, ValueError, KeyError):
        failures.add("execution_uncertain")
    finally:
        if not result["termination_confirmed"]:
            result["termination_confirmed"] = _stop(cli, name)
        result["cleanup_confirmed"] = _cleanup_container(cli, name)
        if not result["termination_confirmed"]:
            failures.add("execution_uncertain")
        if not result["cleanup_confirmed"]:
            failures.add("cleanup_uncertain")
    if not result["output_complete"] and not failures & {
            "check_timeout", "output_bound_exceeded", "execution_uncertain"}:
        failures.add("execution_uncertain")
    result["timeout_observed"] = "check_timeout" in failures
    result["failure_codes"] = tuple(sorted(failures))
    return result


def execute_checks(plan, root):
    """Internal sequential transport, never a worker-facing arbitrary executor."""
    deadline = time.monotonic() + MAX_TOTAL_SECONDS
    try:
        cli = _DockerCli()
        image = _image(cli, plan.image)
    except WorkerRuntimeError as error:
        raise CheckRunnerError("execution_uncertain") from error
    for index, check in enumerate(plan.checks):
        result = _execute_one(cli, image, plan, check, root, index,
                              min(deadline, time.monotonic() + check.timeout_seconds))
        yield result
        if result["failure_codes"]:
            break
