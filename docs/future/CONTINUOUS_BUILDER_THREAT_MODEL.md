# Continuous Builder threat model

## Scope and trust zones

This model covers the proposed Continuous Builder control plane, blueprint and queue stores, worker and verifier sandboxes, artifact store, future external-action adapters, and Evolution Lab boundary. It does not authorize their implementation.

Protected assets are product intent, approved scope, source and Git history, production data and credentials, registry/executor policy, queue/audit integrity, verification evidence, human approvals, external actions, and resource budgets.

Trust decreases across these zones: human-approved policy; deterministic control plane; durable store; verifier sandbox; worker/provider; external services; Evolution Lab. Worker output, model narration, repository test code, tool output, external receipts, and Lab artifacts are untrusted data.

## Threats and required controls

| Threat | Failure sought | Required mechanical control |
| --- | --- | --- |
| Prompt/spec injection | Output chooses tools, commands, scope, risk, approval, or new steps | Closed schemas; authority only from approved blueprint/registry/policy; output fields never interpreted as control instructions |
| Blueprint substitution | Run altered or unapproved work | Canonical digest, immutable version, exact approval binding, runtime revalidation |
| Queue forgery/state skipping | Claim eligibility, verification, or completion | Append-only validated events, prior-digest/sequence binding, transaction/CAS, replayed projection |
| Duplicate dispatch/replay | Two workers or repeated side effects | Leases, attempt IDs, transactional unique idempotency records; reconcile uncertainty before redispatch |
| Dependency confusion | Run on missing, stale, or merely narrated prerequisites | Exact dependency receipt/tree/version binding; fail closed on changed facts |
| Scope/path escape | Modify protected or host files | Frozen path allowlist; reject traversal, absolute paths, symlinks, submodules, archives, and forbidden paths |
| Shared Git control | Hooks/config/worktree compromise host or history | Fresh isolated repository; no shared `.git`; hooks disabled; no host credentials or writable mounts |
| Command injection | Worker controls verifier process | Versioned argv-only command policy; fixed cwd/env/executable; no shell or worker-provided command |
| Malicious tests/code | Exfiltrate, persist, fork bomb, or escape during verification | Container isolation, deny network, env allowlist, resource/process/time limits, disposable teardown |
| Secret leakage | Credentials enter prompts, logs, artifacts, or network | No production secrets; allowlisted env; secret scanning; bounded sanitized receipts; network deny-by-default |
| Evidence spoofing | Worker claims tests or edits receipts | Verifier independently reconstructs tree/runs commands; digest-bind receipts; worker narrative ignored |
| Registry/policy TOCTOU | Execute under different authority facts | Revalidate exact policy/registry/provider facts immediately before action; no silent re-plan |
| Provider compromise | Fabricate status, overrun, or return malicious artifacts | Treat provider as untrusted; local budgets/timeouts; independent verification; cancellation/kill switch |
| Stall/resource exhaustion | Hold leases or consume unbounded cost | Expiring leases, heartbeats, global/per-attempt caps, circuit breaker, operator kill switch |
| Uncertain outcome | Retry an action that may already have happened | Explicit `uncertain` state; no automatic external retry; independent reconciliation |
| Review/approval confusion | Treat advice, bound identity, or passage of time as approval | Separate decision/authorization/action/execution/verification models; explicit authentication flags |
| GitHub confused deputy | Broaden repository/ref/content operation | Single-purpose authorization; least-privilege credentials; exact scope digests; separate executor and verifier |
| Lab escape/promotion laundering | Lab code or authority reaches production | Separate repo/runtime/credentials/queue; evidence-only promotion; new production slice and normal gates |
| Log/audit abuse | Leak secrets, exhaust storage, or overwrite history | Bounded metadata, separate governed artifacts, retention, append-only events, redact before persistence |
| Cleanup failure | Residual container/files remain usable | Teardown receipt, quarantine, block new work on failed cleanup, operator reconciliation |

## Adversarial invariants

Tests must demonstrate that no worker/provider/tool result can choose a tool, command, risk, scope, budget, dependency, approval, credential, queue transition, or retry. Mutations at every adjacent identity boundary must fail closed. Forged receipts, stale leases, digest collisions simulated by mismatched content, reordered events, duplicate idempotency keys, malicious paths, Unicode/size boundaries, output floods, timeouts, and cancellation races require focused tests.

Containment must be attacked with symlink escape, Git hooks, subprocess trees, environment reads, network attempts, filesystem mounts, archive traversal, test-collection code, and cleanup failure. These tests run only in a disposable security-test environment, never against production data.

## Residual risks

The host container runtime, kernel, dependency supply chain, provider service, identity source, database administrator, and future GitHub credential holder remain trust anchors. Hashes provide binding, not authenticity. A passing test suite cannot prove semantic correctness. Durable audit is not tamper-proof without external attestation. These risks require operational controls and future ADRs; they are not solved by agent judgment.

