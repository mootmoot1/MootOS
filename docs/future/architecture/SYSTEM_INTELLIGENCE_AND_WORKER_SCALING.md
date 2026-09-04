# System Intelligence and Worker Scaling

## Purpose

MootOS must scale beyond a development workflow in which every implementation slice consumes premium Claude/Codex capacity. The target is not a cheap replacement coder. The target is a governed software-building system that maintains an evidence-backed model of itself, assembles precise context for each job, decomposes oversized work, routes work across interchangeable providers, and escalates only the work that actually requires premium intelligence.

This program is intentionally coupled to Continuous Builder. Continuous Builder remains the authority/governance control plane; System Intelligence supplies system understanding and context; workers remain bounded executors; the verifier establishes trusted evidence.

## Core architectural principle

**No individual model is expected to hold all of MootOS in context. MootOS must be able to reconstruct the smallest sufficient context for a task from a trusted system model.**

The system owns the map. A worker receives only the neighborhood it needs.

## 1. Trusted System Model

The System Model is a machine-readable, provenance-bearing representation of MootOS. It should eventually describe:

- repository systems, modules, files, classes/functions, schemas, APIs, tools, and tests;
- dependency, import, call, data-flow, and path-conflict relationships where mechanically derivable;
- ADRs, architecture decisions, invariants, non-goals, ownership, risk classes, and authority boundaries;
- Continuous Builder blueprints, slices, attempts, leases, receipts, and accepted outcomes;
- capabilities and which subsystems implement them;
- recent accepted changes, known failures, rollback evidence, and confidence/health signals.

### Trust classes

System knowledge must distinguish at least:

1. **mechanically observed** — code/parser/schema/test/Git/receipt evidence;
2. **human-approved architectural fact** — approved ADR/spec/blueprint;
3. **derived interpretation** — deterministic inference from trusted sources;
4. **model-proposed interpretation** — advisory and untrusted until reconciled.

LLM output cannot silently become trusted system truth.

## 2. Context Engine / Librarian

The Context Engine receives a frozen goal/slice plus trusted System Model references and constructs a bounded context package for a worker or reviewer.

A context package should be exact-bound to its source revision and may include:

- task objective and acceptance criteria;
- allowed/forbidden scope;
- exact source revision and affected files;
- relevant file excerpts rather than whole-repository dumps;
- neighboring public interfaces and dependency summaries;
- relevant ADR/decision excerpts;
- required tests/gates and prior failure evidence;
- known side effects and conflict evidence;
- explicit permissions, non-goals, and authority that is *not* granted;
- provenance/digests for the material included.

### Context invariants

- Retrieval cannot grant authority.
- Context construction cannot enlarge scope or budget.
- Missing or contradictory high-risk context fails closed or escalates.
- Workers may request more context, but additions pass through the same policy/binding process.
- Context packages are disposable views, not a new source of truth.
- Secrets/credentials are excluded unless a later separately approved authority program explicitly permits them.

## 3. Hierarchical Task Decomposer

Large goals should be decomposed progressively:

`goal -> program -> milestone -> phase -> feature -> slice -> atomic worker task`

The decomposer exists to keep work understandable even when MootOS becomes too large for one Claude/Codex context window.

### Decomposition invariants

A decomposer may propose smaller units, but cannot silently alter:

- product intent;
- approved dependencies;
- authority/risk classification;
- allowed paths or permissions;
- budget ceilings;
- acceptance criteria;
- human checkpoints;
- queue transitions.

If decomposition requires changing those facts, it produces a proposal for human/premium-architect review instead of activating the change.

## 4. Provider-Neutral Worker Router

All coding providers sit behind the same frozen worker boundary. Candidate providers include:

- Claude;
- ChatGPT/Codex;
- rented-GPU open-weight coding models;
- future local/first-party GPU workers.

Initial mode: explicit human selection.

Later advisory/automatic routing may consider:

- required capabilities and context/output limits;
- historical first-pass success rate;
- verifier/correction rate;
- average wall-clock time;
- quota remaining;
- dollar cost;
- availability/latency;
- risk class;
- user-selected budget/mode.

Possible user modes later include Cheap, Balanced, Maximum Quality, and Spend Up To $X.

Provider metadata remains descriptive and cannot grant execution, network, credential, GitHub, deployment, approval, budget-growth, or queue authority.

## 5. Specialized Worker Roles

The GPU layer should support useful specialization rather than only cloning one coder role:

- **Builder** — implements a frozen bounded task;
- **Context/Impact Analyst** — proposes affected-system context and challenges omissions;
- **Repair Worker** — performs bounded corrections after verifier failures;
- **System-Map Reconciler** — proposes updates to the System Model after accepted changes;
- **Reviewer** — advisory independent artifact review where useful.

These roles do not have to be separate models. They are policy-constrained jobs that may be served by the same model/provider.

## 6. Trusted Reconciliation Loop

Accepted changes feed back into system understanding only after verification:

`frozen task -> worker -> untrusted artifact -> verifier -> accepted evidence -> reconcile System Model -> future context`

The reconciler should compare prior system facts to mechanically observed post-change facts and produce an auditable delta. Uncertain facts remain uncertain instead of being promoted because a model sounds confident.

## 7. Premium Escalation

Premium agents should be concentrated on high-leverage work:

- architecture and large blueprint design;
- ambiguous/cross-system changes;
- security and authority boundaries;
- repeated cheap-worker failures;
- difficult debugging;
- novel migrations or external side effects;
- cases where Context Engine confidence is insufficient.

Routine, explicit, frozen, testable slices should progressively move to lower-cost workers.

**Design objective:** minimize unnecessary premium-model consumption without weakening correctness, independent verification, or human authority.

## 8. Compute and concurrency strategy

GPU strategy is benchmark-driven. Do not assume the largest model is the best use of a rented GPU hour.

For a candidate GPU/model stack, benchmark one worker, then two, then additional concurrent workers where memory/compute allow. Measure:

- successful verified slices/hour;
- first-pass pass rate;
- correction/escalation rate;
- latency per successful slice;
- GPU/VRAM utilization;
- cost per successful verified slice.

The preferred concurrency level is the one with the highest reliable verified throughput, not necessarily 100% utilization.

Rent before buying dedicated hardware. Use real MootOS slices to determine whether 48 GB, 80 GB, or another class is actually justified.

## 9. Relationship to Continuous Builder phases

### Immediate

Phase 3 is complete. Phase 4 remains necessary because System Intelligence is only useful operationally once Continuous Builder has a proven contained worker boundary.

Phase 4 should preserve provider neutrality and prove the minimum safe path:

- containment policy;
- disposable repository reconstruction;
- environment/network/credential/resource policy;
- one explicitly authorized worker launch;
- artifact collection/quarantine/teardown;
- supervision and uncertain-outcome handling;
- one contained single-slice proof.

### Acceleration point

After the minimum contained worker path is proven, System Intelligence becomes a top-priority implementation program alongside the independent verifier, rather than waiting until all original Continuous Builder phases are complete.

Recommended sequence:

1. finish Phase 4 containment and single-worker proof;
2. materialize System Model + Context Engine foundations;
3. materialize Task Decomposer + provider routing contracts;
4. continue Phase 5 independent verifier and bounded correction;
5. benchmark an open/rented GPU worker behind the same frozen worker contract;
6. add provider scorecards and quota/cost-aware routing;
7. enable parallel workers only after conflict/lease/budget/kill-switch controls are proven.

## 10. Non-goals / hard boundaries

This program does **not** imply:

- consciousness or claims of subjective self-awareness;
- trusting model-generated descriptions of the system as ground truth;
- autonomous Main merge/deployment;
- silent scope or budget growth;
- worker self-authorization;
- arbitrary shell/network/filesystem authority;
- exposing secrets to context workers by default;
- allowing cheap workers to modify their own control-plane policy;
- skipping independent verification because a worker has a high benchmark score.

The goal is operational system awareness: MootOS should be able to answer what it is, what a subsystem does, what evidence supports that answer, what a proposed change touches, what is safe to delegate, and what must escalate.

## 11. Success criteria

This program is succeeding when:

- a worker can complete routine slices without ingesting the full repository;
- context packages are smaller while first-pass success stays stable or improves;
- MootOS can explain relevant dependencies and authority boundaries with provenance;
- accepted changes update system knowledge from verified reality;
- Claude/Codex usage shifts toward architecture/escalation instead of every implementation step;
- open/rented workers can complete a meaningful share of slices under the same verifier;
- cost and quota become routable resources rather than reasons development stops for days.
