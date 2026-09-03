# Continuous Builder implementation program

## Objective and baseline

Continuous Builder turns an exact human-approved blueprint into deterministic queue decisions, contained coding-worker attempts, independent verification, and bounded human-review packages. It may later prepare separately authorized external actions. It never invents product intent or gains automatic Main/deployment authority.

Reuse: V0.4A build job, frozen scope, brief, intake, evidence, bundle, and handoff; V0.4B workflow binding; V0.4C immutable review/publication contracts; V0.4D registry revalidation, budget accounting, central executor, Run, and frozen-operation patterns; existing protected-core gates. Missing: canonical blueprints, durable queue/audit, leases, deterministic Chief Builder, contained automated workers, verifier command policy, artifact storage, supervision, parallel conflict control, authenticated identities, GitHub/staging execution and verification, and Lab infrastructure.

All filenames below are proposed. Each slice gets a separate commit and focused tests. A hard stop means no following authority-bearing slice begins without explicit human approval.

## Phase 1 — Pure planning contracts

| Slice | Objective / contract | Likely files | Invariants, authority, tests, rollback |
| --- | --- | --- | --- |
| CB-001 | Immutable Blueprint, Slice, dependency, scope, budget, and approval-input models | `backend/continuous_builder/blueprint.py`, tests | Bounded canonical data; no approval claim or I/O. Test malformed/oversize/Unicode/immutability. Delete-only rollback. |
| CB-002 | Parse canonical JSON and bind schema/version/content digest/provenance | `blueprint_loader.py`, tests | Unknown fields and digest mismatch fail; supplied identity not authenticated. No persistence. Golden/canonicalization/forgery tests. |
| CB-003 | Validate graph, exact paths, authority declarations, acceptance/test contract | `blueprint_validation.py`, tests | Cycles, missing deps, forbidden authority, ambiguous scope rejected. No scheduling. |
| CB-004 | Pure queue-event/state-machine and receipt models | `queue_model.py`, tests | Closed transitions and bounded append semantics in memory only. No DB. Replay/forgery tests. |
| CB-005 | Deterministic dependency eligibility engine | `eligibility.py`, tests | Hard receipts exact; soft deps non-blocking; stale facts fail. No worker authority. |
| CB-006 | Deterministic priority engine per ADR-037 | `priority.py`, tests | Full scoring/tie-break receipt; model text excluded. Permutation/property tests. |
| CB-007 | Chief Builder plan receipt combining eligibility and priority | `chief_builder.py`, tests | Advisory plan only; no queue mutation or dispatch. Snapshot/bound tests. |

**Safe batch:** CB-001–007 may run sequentially in one session with separate commits. **Hard stop:** approve contracts before persistence.

## Phase 2 — Durable queue and audit

| Slice | Objective / contract | Likely files | Invariants, authority, tests, rollback |
| --- | --- | --- | --- |
| CB-008 | Exact schema/migration and backup/restore design | migration ADR/addendum, migration tests | No migration until reviewed; downgrade/disable path proven. |
| CB-009 | Persist immutable blueprint snapshots and approvals | migration + `blueprint_store.py` | Transactional exact digest; no execution. Temp-DB, duplicate/version tests. Restore migration rollback. |
| CB-010 | Append queue/audit events transactionally | `queue_store.py` | CAS sequence/digest, closed transitions. Concurrency/tamper tests. |
| CB-011 | Replay and cached state projection | `queue_projection.py` | Replay authoritative; cache discardable. Corruption/reordering tests. |
| CB-012 | Attempt identity, leases, heartbeat, cancellation intent | `leases.py` | Expiry means uncertain, never stopped; single active lease. Race/time-control tests. |
| CB-013 | Durable idempotency and bounded audit/artifact references | `audit.py`, `artifact_refs.py` | Unique transaction proves replay control; no raw logs/secrets. Duplicate/crash tests. |

**Hard stop before CB-009:** production DB migration and persistence approval. CB-009–013 can batch only in isolated temporary databases after the migration stop. Rollback disables writers, restores backup if migrated, and preserves audit evidence.

## Phase 3 — Inert worker and dispatch contracts

| Slice | Objective / contract | Likely files | Invariants, authority, tests, rollback |
| --- | --- | --- | --- |
| CB-014 | Provider-neutral worker descriptors and capability matching | `worker_provider.py`, tests | Provider metadata cannot grant authority; deterministic match. No launch. |
| CB-015 | Frozen worker request from V0.4A handoff/base/scope/budgets | `worker_request.py`, tests | Exact source binding; no credentials/commands. Mutation tests. |
| CB-016 | Separate dispatch authorization bound to one request/attempt | `worker_authorization.py`, tests | Bound supplied identity, authentication explicit; authorization is not launch. |
| CB-017 | Inert launch action and cancellation/result receipt models | `worker_action.py`, tests | Single-purpose; `executed=false`; provider output untrusted. Size/forgery tests. |
| CB-018 | Chief-plan-to-worker adapter | `worker_planning.py`, tests | Only eligible leased slice; no scope growth. End-to-end offline contract test. |

**Safe batch:** CB-014–018, separate commits. **Hard stop:** automated process/container authority before Phase 4.

## Phase 4 — Contained runtime and supervision

| Slice | Objective / contract | Likely files | Invariants, authority, tests, rollback |
| --- | --- | --- | --- |
| CB-019 | Container environment provider interface and policy probe | `sandbox_provider.py`, security tests | Fail closed unless isolation features proven. No worker yet. |
| CB-020 | Disposable repository reconstruction at pinned base | `sandbox_repository.py`, tests | No shared `.git`, hooks, host writes, or path escape. |
| CB-021 | Environment, mount, credential, network, and resource policy | `sandbox_policy.py`, adversarial tests | Allowlist/deny-by-default, hard caps. |
| CB-022 | One-worker launch/poll/cancel/collect adapter | `worker_runtime.py`, tests | Exact authorized action only; bounded process authority inside sandbox. No GitHub. |
| CB-023 | Artifact intake, secret scan, quarantine, teardown receipt | `worker_artifact.py`, tests | Artifact untrusted; cleanup failure blocks. |
| CB-024 | Supervisor stall/crash/uncertain/circuit-breaker policy | `supervisor.py`, tests | Receipt-driven, no endless retry; kill switch. |
| CB-025 | Single-slice contained integration proof | dedicated integration tests/docs | Real disposable worker fixture, no production data/network/write. |

CB-019–021 can batch as containment plumbing; **hard human stop before CB-022** (first automated worker execution), and again after CB-025 security evidence. CB-022–025 must not share a batch with authorization changes.

## Phase 5 — Independent verification and bounded correction

| Slice | Objective / contract | Likely files | Invariants, authority, tests, rollback |
| --- | --- | --- | --- |
| CB-026 | Versioned structured verifier-command policy | `verifier_policy.py`, tests | argv only; no shell/worker commands. No execution. |
| CB-027 | Verifier sandbox and command runner | `verifier_runtime.py`, tests | Separate reconstruction/container; bounded command authority. Adversarial commands. |
| CB-028 | Frozen-scope and patch/tree verification adapter | `artifact_verifier.py`, tests | Exact base/patch/tree/path binding. |
| CB-029 | F2P/P2P, lint, gates, and environment evidence | `verification_evidence.py`, tests | Mechanical classifications; output bounded. |
| CB-030 | Advisory multi-provider review adapter | `builder_review.py`, tests | Reviewer cannot transition/approve; independent artifact binding. |
| CB-031 | At-most-two correction controller | `correction.py`, tests | New attempt IDs, unchanged scope/base, explicit budget; exhaustion to human. |
| CB-032 | Human review package and complete build receipt | `build_receipt.py`, tests/docs | `complete` is local build state only. Full offline/contained E2E. |

CB-026 is a safe pure slice. **Hard stop before CB-027** (verifier command execution). CB-027–032 may batch after that approval, with a stop before enabling automated correction rounds.

## Phase 6 — Controlled parallelism and operations

| Slice | Objective / contract | Likely files | Invariants, authority, tests, rollback |
| --- | --- | --- | --- |
| CB-033 | Static path/dependency conflict analysis | `conflicts.py`, tests | Unknown overlap conflicts; advisory first. |
| CB-034 | Runtime conflict revalidation and lease coordination | scheduler/store modules, tests | No overlapping authority; transaction/race tests. |
| CB-035 | Bounded concurrency scheduler | `scheduler.py`, tests | Global/provider budgets and kill switch; no background enablement by default. |
| CB-036 | Health/progress/audit read model | `builder_status.py`, tests | Read-only, sanitized, receipt-derived. |

CB-033–034 can batch. **Hard stop before CB-035** (parallel/background dispatch). CB-036 may follow after scheduler approval.

## Phase 7 — External publication and Staging (separate program)

CB-037 binds verified build receipts to V0.4C review contracts; CB-038 adds externally authenticated human/authorizer identity; CB-039 authorizes one GitHub action; CB-040 implements least-privilege GitHub execution; CB-041 independently verifies/reconciles GitHub state; CB-042 defines Staging authorization/action; CB-043 executes and verifies Staging; CB-044 adds separately authorized rollback.

Each authorization, execution, verification, Staging, and rollback boundary is a hard human stop and separate batch. No GitHub or deployment work begins without new ADRs for identity/credentials/execution/verification/uncertain outcomes. Main remains human-only.

## Phase 8 — Learning and Evolution Lab

CB-045 records bounded outcome features; CB-046 creates advisory playbook proposals; CB-047 creates human-approved priority-policy revisions; CB-048 produces provider scorecards without self-selection authority. These can batch as offline analytics but policy activation is a hard stop.

Lab work is a separate program: LAB-001 provisioning ADR; LAB-002 isolated repo/control plane; LAB-003 budgets/kill switch; LAB-004 experiment blueprint; LAB-005 worker scale scheduler; LAB-006 checkpoint/evidence; LAB-007 promotion package; LAB-008 production ingestion as untrusted proposal; LAB-009 disposable end-to-end proof. Provisioning, network/credentials, high concurrency, and production promotion are separate hard stops.

## Human approval checkpoints

Mandatory stops occur before: blueprint activation; DB migration/persistent writers; any automated worker launch; verifier command execution; automated correction; parallel/background dispatch; authenticated identity; GitHub credentials/execution; external verification/reconciliation; Staging action; rollback; Lab provisioning/network/high-volume execution; and production promotion of Lab output.

Never combine in one implementation batch: authorization with its executor; executor with independent verifier; DB schema approval with migration application; worker containment policy with first worker launch; verifier policy with first command execution; single-worker proof with parallel scheduler; reported external result with verified truth; Lab experiment with production promotion.

## Explicit deferrals

Authenticated human/provider identity, credential ownership, GitHub execution, external state verification, durable artifact-store selection, supply-chain mirror, retry of uncertain external outcomes, autonomous Main merge/deploy, persistent generalized mission resume, arbitrary shell/filesystem/network authority, dynamic tool registration, root privileges, capability installation, and Continuous Builder self-modification remain deferred.

