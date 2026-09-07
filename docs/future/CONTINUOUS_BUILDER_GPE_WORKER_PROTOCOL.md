# GP-E — Provider-neutral worker protocol

Status: protocol implementation for human review. Base:
`c2463174268e533178de4f84442ed549da19d1c8`.
Protocol/schema family: `gpe-worker-v1`; message `kind` discriminates identity,
request, result, and slice/job correlation. No execution authorization.

**The system owns truth. The worker only proposes changes.**

## Boundaries and economy

Two new non-TCB production modules: `gpe_protocol.py` for bounded sealed
messages and binding checks; `gpe_adapter.py` for the adapter interface and
result/error normalization. The two fictional adapters live only in tests.
No SDK, routing layer, daemon, storage layer, dispatch loop, or migration.
Existing `worker_provider.WorkerDescriptor` remains the earlier descriptive
matching contract, and existing containment/runtime contracts remain unchanged.
GP-E adds the GP-B/C/D wire boundary, not another matcher or executor.

Provider is the inference/service connection. Worker is the coding-agent
implementation using that connection. `WorkerIdentity` distinguishes worker
type, implementation and version from optional provider/model IDs. Its
advertised capabilities reuse GP-C's IDs; they describe technical support,
never admission, credentials, authority, or trusted verification.

Canonical JSON/SHA-256 and validation primitives come from `gpa_eval_schema`.
The small private sealing base is local to these four message kinds; it is not
a general serialization framework. Frozen fields use tuples and scalars.
Every message contains explicit false authority fields. Digests detect changes;
they are **not signatures**, proof of origin, or launch tokens. Wire parsing
requires exact fields, supported versions, valid bounds and digests; duplicate
JSON keys and nonfinite usage values fail closed. Messages are limited to
128 KiB; exact supplied context is separately limited to 2 MiB, including at
most eight existing CE supplements. CE's own smaller content budgets still apply.

## WorkerRequest

`create_worker_request` takes system-owned GP-D header/attempt, GP-B contract/
plan, GP-C decision/input, CE package/supplements, and product correlation.
It revalidates their seals and cross-checks identities, digests, repository,
base, architecture baseline, policy identity, scope, budgets, and gates.
`validate_worker_request` reconstructs and compares the exact message against
those system inputs, detecting even a worker's independently re-sealed forgery.
The caller must resolve these inputs from system-owned evidence and GP-D truth;
accepting worker replacements defeats the boundary.

The packet contains:

- Deterministic request ID, job ID, attempt ID and header/attempt digests.
- IDs/digests of FrozenTaskContract, ExecutionPlan, AdmissionDecision, and
  AdmissionInput. It does not copy those full objects.
- Repository/base SHA, allowed/forbidden scope, admitted capability IDs,
  the four GP-D budget ceilings, required gates, GP-C human-gated capability
  IDs and overall admission outcome.
- Goal, success criteria, frozen constraints, fixed stop conditions and
  the versioned WorkerResult output contract.
- Exact CE binding and sealed slice/job correlation.

The GP-C decision's `input_sha256` names **TrustedAdmissionFacts**, not
AdmissionInput. GP-E reuses `facts_from_admission_input` to check that binding
and additionally preserves the original input's ID/digest. Per-capability
rows bind their original request digests. Only admitted request scope,
operation/resource and budget constraints are projected into canonical JSON
strings in the packet; provider/model annotations and full request objects
are omitted. This small duplication makes the worker's limits explicit.

Runtime bounds are the **intersection** of each admitted request's bounds,
the GP-D ceilings and the frozen contract. Forbidden scope always wins.
`None` means an unspecified bound, not a grant or zero usage. Advertising a
broader capability cannot change any of these values. Human-gated capabilities
are not included in admitted capabilities. Packaging a reviewable request,
including a blocked/human-gated decision, never clears its gates or permits
launch. GP-F must enforce the admission outcome and obtain the separate
required approvals before execution.

## Context Engine / System Model

Use existing `assemble_context_package` / `adapter_build_context_package` and
`seal_supplement_request` / `fulfill_supplement` upstream. Existing deterministic
selection, exclusions, evidence retrieval and supplement-denial rules are
unchanged. GP-E performs no repository selection or extraction.

`context_binding` records the package digest (also used as its content-addressed
ID), base SHA, CE request digest, System Model digest, ordered supplement and
supplement-request digest pairs, and the hash of every exact delivered payload.
CE has no standalone package ID; `sha256:<package_sha256>` is its stable GP-E
reference. CE's source/evidence references are transitively bound by the package
seal and are present in the supplied package bytes. Supplements must match the
original CE request, package and base; duplicates and omissions are rejected.

`prepare_context` returns the existing CE canonical bytes after binding checks.
The adapter receives this ordered tuple alongside WorkerRequest. This establishes
what bytes the system supplied, not proof that a model read or understood them.
WorkerResult cannot supply replacement context metadata. Retain the payloads as
system evidence; a digest alone does not make unavailable bytes reconstructible.
CE and SM remain descriptive and outside the TCB.

## WorkerResult and errors

WorkerResult binds request ID **and digest**, job/attempt IDs and worker identity.
It includes a small status vocabulary, content-addressed artifact locators,
changed-path claims, bounded command/test claims and stdout/stderr summaries,
worker-reported completion, stop/error details, optional integer usage values
(input/output tokens, elapsed milliseconds, cost in micro-USD) and result digest.
All of these are **untrusted claims**, including artifact digests and usage.
Locators are never opened by GP-E; quarantine must validate actual artifact
bytes and paths, and the trusted verifier must independently run checks.

Statuses: `completed`, `partial`, `blocked`, `failed`, `timed_out`, `cancelled`,
`context_insufficient`, `capability_denied`, `execution_unknown`. They are worker
outcomes, not GP-D terminal states. `completed` is never `terminal_success`.
A worker may contradict itself (e.g. a completion claim with a failure status);
that remains evidence, not a successful system outcome.

Adapter implementations normalize their SDK-specific errors into:
`rate_limited`, `provider_unavailable`, `authentication_unavailable`,
`model_unavailable`, `context_too_large`, `malformed_response`,
`worker_protocol_violation`, `timed_out`, `cancelled`, `sandbox_failure`, or
`unknown_failure`. Unknown provider codes become `unknown_failure`.
These are transport/adapter categories, **not another GP-D retry taxonomy**.
No SDK exception is imported or automatically logged; only caller-sanitized,
bounded details may be supplied. Oversized details are rejected, not silently
accepted. No downstream retry eligibility is computed here.

`normalize_adapter_error` defaults to `execution_unknown`. A clean failure is
representable only when the system observed failure before invocation and
explicitly supplies `execution_may_have_occurred=False`. A provider timeout,
error message or missed heartbeat is not proof of no side effect.
`receive_worker_result` requires an explicit supervisor uncertainty argument.
Malformed post-invocation responses become `execution_unknown`; known durable
uncertainty overrides even a well-formed success claim. GP-D reconciliation
remains authoritative and cannot be cleared by these functions.

## Adapter contract and attempt semantics

`WorkerAdapter` is a typing Protocol: descriptive `identity` and one
`invoke(request, context_bytes) -> WorkerResult` boundary. There is no generic
invoke wrapper that might accidentally launch arbitrary implementations.
AlphaFake and BetaFake are inert test references: the same packet yields a
completed claim or a normalized blocked result. Error/timeout tests use fake
provider exceptions and make no network calls or worker processes.

One request binds one `started` GP-D attempt and its header. Other attempt
statuses, wrong jobs, and stale header digests are rejected. The request ID is
`gpe_` plus 60 hex characters of a domain-versioned SHA-256 over job/attempt IDs
(to respect existing GP-A ID bounds); the complete message has a full SHA-256
seal. Reconstructing the same packet is replay, not execution. A proper retry
uses a new GP-D attempt ID, yielding a different request ID; an old result cannot
bind to it. Existing GP-D append-only attempt rules enforce history.

**No durable dispatch reservation is implemented.** GP-F must persist the exact
request ID/digest and context references before launch, reject a conflicting
packet under the same attempt, and prevent duplicate execution on replay. The
factory alone cannot establish that an attempt is current or unused after a
restart. It does not silently create attempts or retry. This is the intended
GP-F execution boundary, not process-local durability masquerading as a ledger.

## Slice/job correlation (ADR-044)

`SliceJobCorrelation` seals blueprint ID/digest, slice ID, job ID/header digest.
Product IDs retain the existing blueprint ID syntax. The system resolves the
product references; the record is provenance, not verification of a queue
transition or a foreign-key migration. A slice can cause multiple jobs, and a
job can have multiple attempts. It contains no queue state, job state, completion
flag, or authority. Even a trusted GP-D terminal success cannot complete the
slice through this record. Queue SQLite remains roadmap truth; GP-D JSONL remains
execution truth. No store is added or unified.

## GP-F handoff

Before the first real worker, GP-F must:

1. Resolve authoritative upstream records, validate the packet, check current
   GP-D state/attempt/lease and live policy, and enforce human gates separately.
2. Record dispatch identity and exact evidence through an approved durable path;
   enforce replay/conflicting-packet handling and new-attempt retry rules.
3. Authorize and supervise the worker process/provider, enforce admitted scope,
   capability and budget intersections, and deliver exactly the bound CE bytes.
4. Carry GP-D execution uncertainty into result intake. Reconcile explicitly
   whenever effects or termination are uncertain; never retry by error category.
5. Quarantine artifacts, independently verify, apply trusted policy and retain
   human approval for product advancement, GitHub publication and Main merge.

These contracts are ready for GP-F integration design, not a production launch.
No TCB imports/membership/protected paths are changed. No DB/schema/storage
migration, real provider, autonomous retry/reconciliation, GitHub mutation,
parallel execution, Main merge or deployment is implemented by GP-E.
