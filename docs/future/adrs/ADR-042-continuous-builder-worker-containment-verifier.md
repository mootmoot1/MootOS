# ADR-042 — Automated coding workers require container containment and independent verification

## Status

Proposed. No worker launch or verifier command execution is enabled by this record.

## Worker model

Workers are replaceable, provider-neutral executors behind `prepare`, `start`, `poll`, `cancel`, and `collect` operations. Requests bind provider adapter/version/config digest, approved build handoff, base commit, frozen paths, resource limits, timeouts, and attempt ID. Results are untrusted artifacts and bounded status metadata. Provider/model identity is recorded, not treated as proof of authorship or competence.

## Containment

Automated dispatch requires a disposable OS-level container or stronger sandbox. A Git worktree alone is insufficient. The sandbox receives a fresh repository reconstruction at a pinned commit, temporary home/database/cache paths, an environment allowlist, no production credentials, no host Git control files, no privileged mounts, no container socket, and deny-by-default network. CPU, memory, process, disk, output, token, and wall-time limits are mandatory.

Repository hooks and executable configuration are disabled or reconstructed from trusted policy. Symlinks, path traversal, submodules, generated files, and archive extraction are validated. Cancellation revokes the lease and terminates the sandbox; cleanup failure is an auditable blocked condition.

### Phase 4B runtime-foundation decision

The first production containment backend is Docker, controlled only by the
trusted MootOS supervisor. Docker is a host trust anchor, not worker authority.
The Docker socket, daemon endpoint, host Docker configuration, daemon
credentials, and any other container-control interface must never be mounted
or exposed inside a worker. Provider claims and policy compatibility remain
descriptive until the supervisor produces exact runtime enforcement evidence.

The first proof worker will be a MootOS-owned, deterministic, offline fixture
worker. Its image is pinned by immutable digest, its entrypoint and structured
argument contract are fixed by MootOS policy, it receives no network or
credentials, and it operates only on a disposable workspace. Mutable image
tags, arbitrary shell commands, and worker-selected executables are forbidden.

Before CB-022, the runtime foundation binds the Docker runtime identity,
pinned image/config, fixed entrypoint, planned repository materialization,
required enforcement classes, and future handle/cancellation semantics. These
are inert contracts: no repository is materialized, Docker is not contacted,
runtime isolation is not verified, and launch is not authorized. CB-022 must
revalidate every identity and replace structural requirements with evidence
from actual enforcement before gaining one-worker process authority.

## Verifier command authority

The verifier is distinct from the worker and reconstructs a clean tree from trusted base plus returned patch. Commands come only from a versioned human-approved verifier policy and structured test declarations. A command is an argv tuple with fixed executable identity, repository-relative working directory, explicit environment allowlist, timeout, resource cap, and bounded output capture. Shell strings, redirections, command substitution, worker-proposed commands, and tool-output-proposed commands are forbidden.

The verifier may execute project tests, FAIL_TO_PASS/PASS_TO_PASS checks, lint, type checks, and protected-core/security gates in its own contained environment. Passing commands do not approve the artifact. The receipt binds base, patch, resulting tree, scope, policy version, command identities, exit classifications, bounded output digests, and environment identity.

Test and collection code is untrusted and therefore runs inside containment. A timeout, malformed result, sandbox escape signal, environmental ambiguity, missing evidence, or mismatch fails closed. Raw output is never authority and must be secret-scanned before bounded retention.

## Authority not gained

This boundary does not grant GitHub, push, merge, deploy, production filesystem, credential, root, dynamic registration, arbitrary shell, approval, or retry authority. Networked dependency installation, if ever needed, requires a pinned artifact mirror and separate supply-chain decision.
