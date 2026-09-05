# CB-026B — trusted bounded check runner

Base: `4fa285f89de3e3a34421d960bdee146c47933472` (CB-026A).

## Boundary and API

`check_runner.py` adds immutable, content-addressed check definitions, a pinned
toolchain image contract, a trusted plan, ordered check results, and an aggregate
execution receipt. Only trusted supervisor code calls these factories. There is
no worker-facing deserializer, endpoint, queue integration, or automatic dispatch.
The private construction-token convention matches CB-026A; it is an in-process
boundary, not authentication of arbitrary host Python code.

```python
check = create_trusted_check(
    check_id="pytest", tool="pytest", targets=("tests/test_app.py",),
    timeout_seconds=30,
)
plan = create_trusted_check_plan(
    contract, structural_receipt, checks=(check,), image=trusted_image,
)
receipt = run_trusted_checks(plan, contract, execution_receipt, intake_result)
```

The image is provisioned and reviewed separately by the system, already present
locally, and pinned by image/manifest and config digests. Its repository is fixed
to `mootos/trusted-check-runner`. Verification never pulls or installs packages.
Image inspection verifies Linux architecture, fixed Python entrypoint, empty
default command, exact image environment, and absence of volumes/on-build hooks.

The plan binds the exact CB-026A receipt, candidate tree, base SHA, request,
ordered checks, image contract, and policy version. Execution reruns CB-026A
against the supplied contract/execution/intake evidence and compares the exact
structural receipt bytes. A failed or mismatched structural result cannot launch.

## Commands and reconstruction

Only two command profiles exist, with fixed interpreter and options:

- `/usr/local/bin/python3 -I -m pytest -q -p no:cacheprovider --noconftest -c /dev/null --rootdir=/candidate -o pythonpath=/candidate -- <targets>`
- `/usr/local/bin/python3 -I -m flake8 --isolated --jobs=1 -- <targets>`

Targets are explicit canonical `.py` paths, never option strings, globs, shell
syntax, or worker-selected commands. Pytest targets must exist in the trusted
base and be protected from replacement. The contract must also protect
`verifier_core.py`, `check_runner.py`, and `check_runtime.py`. No arbitrary argv,
working-directory, shell, environment, expected-exit-code, or host-path parameter
is exposed. The sole passing exit code is 0. Candidate claims are not consulted.

A new randomly identified workspace is created under the supervisor-owned 0700
root `/private/tmp/mootos-continuous-builder-checks`. Only trusted base bytes plus
exact admitted replacement bytes are materialized. The base and candidate
digests are recomputed; the on-disk candidate is rehashed before each check and
after execution. Symlinks, hard links, traversal, nonregular files, case/prefix
collisions, and excessive trees are rejected. Bounds: 4,096 files, 1 MiB per
file, 16 MiB total. The enclosing workspace remains private; inner directories
and files have explicit read permissions for the fixed nonroot container user,
independent of host umask. No production repo or old worker workspace is reused.

## Execution containment and bounds

`check_runtime.py` uses CB-022's fixed `_DockerCli` executable/environment and
control-call bounds. It does not generalize or weaken `DockerWorkerRuntime`'s
fixed offline-worker entrypoint. A separate attach-stream primitive is necessary
because CB-022 collects logs after completion, whereas check output must be
limited while the process is producing it.

Each check gets a new container and the same exact read-only candidate mount:
network none; read-only root filesystem; UID/GID 65532; all capabilities dropped;
no-new-privileges; private namespaces; no devices, host home, Docker socket,
credentials, or writable host mounts. Container inspection verifies these
settings before start, including exact argv, environment, and mount set.
Unexpected security options (including an unconfined seccomp override) fail
closed. CPU is capped at 2, memory at 512 MiB with no additional swap, and PIDs at
16. Temporary storage and private shared memory are each 16 MiB; `/tmp` also has
a 1,024-inode cap and noexec/nosuid/nodev. Docker logging is disabled.

The host subprocess is only the fixed Docker CLI attach operation, executed with
`shell=False`, closed inherited descriptors, no stdin, a new process session,
and CB-022's minimal credential-free supervisor environment. The container gets
fixed PATH/locale/Python/pytest settings and HOME/TMPDIR inside its own `/tmp`.
Python isolated mode and disabled pytest plugin auto-discovery prevent host or
candidate startup/config overrides; flake8 ignores local configuration.

At most four checks execute in order, stopping on the first failure. Each has a
1–30 second deadline; the run also has a shared 120-second execution deadline.
Finite Docker control/termination/cleanup grace is additional to that deadline:
ordinary control calls are capped at five seconds, stop/kill at three seconds,
and attach-process TERM/KILL waits at 0.5/1 second. There are no execution retries.

Each output stream is independently capped at 1–65,536 bytes (default 16,384).
Selectors drain pipes incrementally and stop at the configured bound plus one
detection byte, without retaining unbounded data. On overflow or timeout the
attach client is terminated and the entire container is stopped/killed, covering
descendants even if they create another process session. Removal is followed by
a successful absence query. Workspace cleanup uses CB-022's private cleanup
primitive. Any uncertainty prevents a passing result.

## Receipt semantics

Receipts bind the plan and CB-026A identities, random workspace identity digest,
ordered check/argv identities, containment-inspection digest, container IDs,
logical start/finish sequence, observed exit codes, stdout/stderr sizes and
SHA-256 values, output completeness, timeout, termination, and cleanup facts.
Raw output is not retained, so test text is neither status authority nor a
diagnostic secret-retention channel. If capture is interrupted, stream sizes and
digests describe only the observed prefix and `output_complete=false`.

Aggregate statuses: `checks_passed`, `checks_failed`, `checks_timed_out`, and
`checks_uncertain`. Canonical bounded failure codes include nonzero exit,
timeout, output overflow, identity mismatch, invalid candidate input, unproven
containment, execution uncertainty, and cleanup uncertainty. Invalid plans are
rejected before workspace creation. Runtime failures produce nonpassing evidence.

Plan identities are deterministic. Actual receipt identities bind run-specific
workspace/container/output facts and therefore intentionally differ between runs.
`outcome_sha256` normalizes those runtime-dependent facts for comparing the same
plan's observed exit/failure outcomes; it does not replace the complete receipt.
Start/finish sequencing is logical ordering, not fabricated wall-clock timestamps.

Every receipt keeps these flags structurally false: `result_trusted`,
`worker_output_trusted`, `externally_verified`, `publication_authorized`,
`queue_transition_authorized`, `github_authorized`, `merge_authorized`, and
`main_advancement_authorized`. Passing checks are evidence, never permission.

## Local real proof (2026-09-05)

Docker Desktop 4.47.0 (206054), Engine 28.4.0, API 1.51, linux/amd64 on this Mac.
The existing local image was retained; resumption did not rebuild it:

- Image/manifest: `a6f5e9858a815c7db9cefb9d647f919faafe63639321e658d680b48fb3d0d775`
- Config: `4adf2d1d6e5959603d214b4c841382668ceebbbc47438b3a2d03b32c54957b72`
- Tools: pytest 8.4.1, flake8 7.1.2; copied offline from already installed pure
  Python packages into the prior pinned CB-022 Python image. No runtime install.

Standalone evidence used actual contained offline worker executions for `2\n`
and `3\n`, actual stdout bridging/CB-023 intake, and actual CB-026A structural
verification. It then ran the same trusted pytest target against fresh verifier
trees. A third trusted base test deliberately slept for 60 seconds under a
five-second check deadline.

| Case | Observed exit | Receipt status | Termination / cleanup |
| --- | --- | --- | --- |
| Positive `value.txt = 2\n` | 0 | `checks_passed` | confirmed / confirmed |
| Negative `value.txt = 3\n` | 1 | `checks_failed` (`check_nonzero_exit`) | confirmed / confirmed |
| Purpose-built timeout | 137 | `checks_timed_out` (`check_timeout`, `check_nonzero_exit`) | confirmed / confirmed |

Receipt digests, respectively:

- `68d346444e44ab06dee08bfc48ad870dc6cbd95eff9501479e9e09642eff8adf`
- `b05587a3efc78cc38a34539af21f0ca01cf197ea9b3ec95d0eabe1189ea5800f`
- `dd248606d8a0e8d3a1abd078ac1e47a2901321a09df452559f641742cdc7c173`

The earlier six-case real-container integration run passed in 36.89 seconds,
including failing flake8, output overflow, and fake-sentinel environment
isolation. The three standalone receipts above were captured after the final
umask and unexpected-security-option corrections. All production proof roots
were checked empty, and no verifier containers remained. Local receipts and
JUnit evidence are retained outside the repository in the task's
`cb026b-evidence` directory. No PR has been merged by this proof.

## Tests and remaining limitations

Focused tests: 192 passed, six opt-in image-dependent cases skipped. The focused
breakdown is check_runner 67, verifier_core 15, repository_materialization 28,
runtime_enforcement 36, worker_artifact 26, supervisor 20. Blocking flake8
(`E9,F63,F7,F82`) passed. The six optional real-container cases were separately
executed successfully as described above. Cross-version CI remains the main
Python 3.9/3.10/3.11 gate.

Broader regression: all `tests/test_continuous_builder_*.py` completed with
583 passed and six opt-in Docker cases skipped in 189.71 seconds.

The opt-in cases take trusted local image/config digests from
`CB026B_TEST_IMAGE_DIGEST` and `CB026B_TEST_CONFIG_DIGEST` in the **test harness**.
Production execution never reads those variables or accepts worker runtime
configuration. Unit tests simulate upstream CB-022 evidence; the standalone
proof used real upstream containers as well as real verifier containers.

Deferred, not implemented here: generalized toolchain provisioning/signatures,
dependency installation or mirrors, non-Docker execution, Windows pipe support,
networked tests, arbitrary tool profiles/options, writable candidate tests,
coverage/F2P/P2P or test-count acceptance rules, semantic correctness guarantees,
signed/cross-process receipt attestation, persistent orchestration, repair,
retries, scheduling, and any publication/queue/GitHub/merge authority. An exit-0
pytest process is evidence for this trusted check plan, not proof that hostile
candidate code is correct. Container security depends on the trusted host Docker
daemon/kernel and approved toolchain image. Uncertain Docker cleanup requires
operator attention; it never grants authority or triggers autonomous retries.

THE SYSTEM OWNS TRUTH. THE WORKER ONLY PROPOSES CHANGES.
