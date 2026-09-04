# MootOS Future Roadmap

This document extends, but does not replace, the current root `ROADMAP.md`.

## NOW

- Continuous Builder Phase 3 (CB-014–018 inert worker and dispatch contracts) is complete and merged.
- Build the minimum Phase 4 contained-worker path needed to prove that one frozen slice can be executed by one disposable worker under explicit human approval, isolation, bounded authority, and cleanup evidence.
- Do not let Phase 4 quietly become a provider-specific Codex/Claude executor. The worker boundary must remain provider-neutral so Claude, Codex, rented-GPU/open-weight workers, and future local workers can share the same frozen request/authorization/result contracts.
- Treat premium-model quota and cost as a first-class architecture constraint. Routine implementation must progressively move away from requiring Claude/Codex for every slice.

## IMMEDIATE ACCELERATION TRACK — SYSTEM INTELLIGENCE & WORKER SCALING

This track moves near the top of the roadmap because premium coding-agent quota is already constraining development throughput. It is not a hard turn away from Continuous Builder; it is the layer that lets Continuous Builder scale without requiring one premium model to understand or implement the whole system.

### 1. Trusted System Model / MootOS Self-Map

Maintain a machine-readable, continuously reconcilable model of MootOS itself:

- subsystems, modules, files, classes/functions, schemas, tools, tests, ADRs, capabilities, owners, and authority boundaries;
- dependency/call/import relationships and known path overlap/conflict relationships;
- current blueprint/slice state, recent accepted changes, known failures, and rollback/test evidence;
- confidence/provenance for every important fact.

The self-map is operational system awareness, not consciousness. It must distinguish mechanically observed facts from model-generated interpretation. Source code, tests, Git history, schemas, receipts, and durable state remain ground truth wherever available.

### 2. Context Engine / Context Librarian

Given a goal or frozen slice, construct the smallest sufficient, source-bound context package instead of giving a worker the entire repository.

A context package may include:

- exact files or bounded excerpts;
- relevant interfaces from neighboring modules;
- dependency/impact evidence;
- ADR/decision excerpts;
- frozen scope, base revision, acceptance criteria, tests, and gates;
- prior failure/correction evidence when relevant;
- explicit forbidden authority and non-goals.

Core invariant: **no worker should require global MootOS context to perform routine work. MootOS owns the map; the worker receives the neighborhood.**

### 3. Hierarchical Task Decomposer

Allow large goals to be progressively reduced into bounded work without changing product intent or authority:

`goal -> program -> milestone -> phase -> feature -> slice -> atomic worker task`

The decomposer may propose smaller steps but cannot silently change approved intent, dependencies, risk classification, permissions, budgets, acceptance criteria, or queue authority. Hard changes escalate to a premium architect/human review.

### 4. Provider-Neutral Worker Router

Treat workers as interchangeable implementations behind the same frozen worker contract:

- Claude;
- ChatGPT/Codex;
- rented-GPU open-weight coding workers;
- future first-party/local GPU workers.

Start with manual worker choice. Later route deterministically/advisorially using capability, success history, quota, cost, latency, availability, context limits, and user budget. Provider metadata never grants authority.

### 5. Specialized Worker Roles

Do not reduce the GPU strategy to “a cheaper Codex.” Support specialized roles where useful:

- Builder — implement one bounded slice;
- Context/Impact Analyst — construct or challenge affected-system context;
- Repair Worker — handle bounded test failures/correction attempts;
- System-Map Reconciler — update proposed self-map facts from verified accepted changes;
- optional independent reviewer roles where they add measurable value.

Run multiple workers only when dependency/path/conflict analysis proves the work can safely overlap. Optimize for successful verified slices per dollar/hour, not raw GPU utilization.

### 6. Trusted Reconciliation Loop

After a change is independently verified and accepted:

`verified code/tests/receipts -> reconcile System Model -> new context packages -> future planning`

LLM claims never directly become trusted self-knowledge. New system facts must carry provenance and, where possible, mechanical evidence.

### 7. Premium Escalation Policy

Use expensive intelligence where it creates the most leverage:

- architecture and large blueprint creation;
- ambiguous or cross-system changes;
- security/authority-sensitive work;
- repeated worker failures;
- difficult debugging and review;
- changes where the context engine cannot establish high-confidence boundaries.

Use lower-cost workers for clear, frozen, testable implementation work. Explicit design objective: **minimize unnecessary premium-model consumption without weakening correctness, verification, or human authority.**

### 8. Compute / GPU Benchmark Program

Before buying hardware, rent and benchmark real MootOS slices. Compare one, two, then more concurrent workers on the same hardware/model combination. Measure:

- successful verified slices per hour;
- first-pass acceptance/test rate;
- correction/escalation rate;
- wall-clock time per successful slice;
- GPU utilization and memory pressure;
- cost per successful verified slice.

Prefer the concurrency level with the highest useful throughput, not the highest visible utilization. Initial target hardware classes may include 48 GB and 80 GB VRAM rentals; model choice remains benchmark-driven.

## SEQUENCING

1. Phase 4 minimum containment plumbing and one-worker proof remain the immediate execution prerequisite.
2. Before broadening provider/runtime authority, materialize the System Model, Context Engine, decomposition, and provider-routing program into implementation-grade slices.
3. Phase 5 independent verification remains mandatory before cheap/open workers can be trusted for unattended volume.
4. System Intelligence and provider scaling should develop alongside the verifier path rather than waiting until the end of the original Continuous Builder program.
5. Parallel/background worker scaling does not activate until conflict control, leases, budgets, kill switches, and verifier evidence are proven.
6. Main merge/deployment authority remains human-controlled unless separately redesigned and approved in a future governance program.

## NEXT

1. Minimum contained worker runtime and one-worker proof.
2. System Model / self-map foundation.
3. Context Engine / source-bound context packages.
4. Hierarchical Task Decomposer.
5. Provider Router and provider capability/scorecard contracts.
6. Independent verifier and bounded correction pipeline.
7. Controlled parallelism/conflict control and multi-worker scheduling.
8. Staging manager and evidence-based staging promotion.
9. Reliability/Evaluation foundation.
10. Chaos/Evolution Lab foundations.
11. Stronger permissions/approvals/audit/rollback.
12. Shared connector framework, workflows, events, background jobs.
13. Systems Architect and technology intelligence.

## THEN — REAL-WORLD VALUE

1. Studio/Client OS.
2. Social/Content system.
3. Video engine.
4. Business/Revenue brain.
5. Treasury Simulator and controlled Capital Agent.
6. Communications, calendar, people, files, devices, cars, personal finance.

## LATER — JARVIS LAYER

- Daily executive command center.
- Goal-driven opportunity research.
- Long-horizon missions.
- Multimodal/voice/wearable operation.
- Cross-system workflows.
- Proactive opportunity and innovation radar.
- Controlled computer use.

## LABS

- Chaos Lab: intentionally break disposable MootOS copies.
- Evolution Lab: let multiple coding workers aggressively build hundreds to ~1,000 slices in disposable repos and measure where autonomous development succeeds, drifts, or fails.
- Lab Promotion Engine: turn proven discoveries into production-ready promotion packages and temporary roadmap interrupts after human approval.

## UI/UX OVERHAUL

After major system specs are clear, perform a collaborative visual redesign. Exchange references/mockups, settle information architecture and Jarvis-like visual language, then create implementation slices. Do not lock the final UI before the underlying systems are understood.
