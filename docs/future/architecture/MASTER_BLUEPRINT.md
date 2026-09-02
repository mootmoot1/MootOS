# MootOS Master Architecture Blueprint

**Status:** Future master engineering plan. Planning only; does not describe current runtime authority.

## North star

MootOS should become a private, permissioned personal AI operating layer that can understand Moot's goals, maintain durable context, research opportunities, propose projects, safely build approved software, coordinate tools and specialist agents, learn from outcomes, and eventually operate authorized parts of Moot's work and life.

Prime directive: **continuously improve Moot and continuously improve MootOS, while keeping Moot in control.**

## Core architecture

MootOS evolves as a control plane over replaceable workers and services, not as one giant agent. The core owns durable state, policies, approvals, audit evidence, capability truth, planning, and orchestration. Models, coding workers, payment providers, communication providers, and external APIs are adapters.

### Authority hierarchy

- Human: final strategic authority; Main merge; high-risk approvals; irreversible actions.
- Chief Builder: roadmap interpretation, dependency reasoning, priority, safe dispatch, review coordination, staging, learning.
- Specialist builders: bounded domain implementation.
- Independent reviewer: adversarial review separate from the builder.
- Mechanical gates: deterministic enforcement.
- Chaos Lab: destructive testing in disposable environments.
- Evolution Lab: aggressive alternative development in disposable repos.

### Environments

- **Main:** trusted production source; no autonomous merge.
- **Staging:** integration candidate; limited evidence-based auto-promotion allowed.
- **Sandbox:** disposable experiments.
- **Chaos Lab:** disposable break-it environment.
- **Evolution Lab:** disposable build-far-ahead environment.

### Work object hierarchy

Idea -> Opportunity -> System Spec -> Capability -> Slice -> Task/Experiment.

Slices are the normal PR-sized unit. Every slice has scope, dependencies, permissions, acceptance criteria, failure cases, tests, rollback, and a Do Not Touch boundary.

### Slice lifecycle

Idea, Researching, Designing, Ready to Build, Scheduled, Building, Blocked, Reviewing, Changes Requested, Staging, Testing, Ready for Main, Done, Paused, Superseded, Retired, Cancelled.

Every state transition records why it occurred.

## Development philosophy

1. Preserve Moot's core idea; improve implementation proactively.
2. Reuse shared capabilities quietly; propose new shared abstractions explicitly.
3. Build high-leverage foundations first; later blend in quick wins.
4. Prefer high expected value, not complexity for its own sake.
5. Research first when confidence is too low for a complex build.
6. Quiet by default; interrupt only for blockers, major discoveries, risks, approvals, or meaningful milestones.
7. Every meaningful success/failure improves a living engineering playbook.
8. External services are replaceable adapters, not architecture.
9. No production secret should become model context when a capability token or mediated adapter can be used instead.
10. Autonomy is earned from measured reliability.

## Continuous Builder target loop

Idea or goal -> Architect enriches -> spec -> slice graph -> priority -> safe worker handoff -> isolated build -> mechanical tests -> independent review -> PR -> staging -> Chaos testing -> human Main approval -> outcome feedback -> playbook update -> next Ready slice.

Independent work may run in parallel. Dependent work never stacks on unmerged assumptions unless explicitly modeled in an isolated integration branch.

## Five-hour staging rule

If Moot is unavailable for about five hours, an independent low-risk PR may be promoted to Staging only when all required tests are green, dependency independence is high-confidence, security checks pass, Chaos has no blocker, and rollback is proven. Nothing in this rule authorizes Main merge.

## Major platform systems

- Continuous Builder and Chief Builder
- Build Queue, dependency graph, priority engine
- Staging/deployment intelligence
- Chaos Lab and evaluation platform
- Security, identity, approval, audit, kill-switch
- Shared connector framework
- Durable workflows, events, background jobs
- Memory and knowledge platform
- Model/provider abstraction and routing
- Research and technology intelligence
- Systems Architect and roadmap intelligence
- Notification/attention system
- Personal Executive/Jarvis layer
- People/relationship platform
- Studio/Client OS
- Pro Tools/engineering assistant
- Social content system
- Video engine
- Business/revenue brain
- Treasury/Capital Agent
- Personal finance
- Communications hub
- Calendar/scheduling
- Vehicle system
- Device/computer manager
- File/document intelligence
- Multimodal and voice/wearables
- UI/UX overhaul
- Backup/disaster recovery
- Observability and cost intelligence
- Long-horizon missions
- Innovation Radar
- Feature lifecycle/product intelligence
- Cross-system workflows
- Evolution Lab

The canonical planned slice inventory is `../build-queue/SLICE_CATALOG.md`.

## Success condition

MootOS is not considered successful because it has many features. It succeeds when it repeatedly converts Moot's goals into useful, auditable outcomes with low friction; catches its own weaknesses; safely improves itself; and makes the next capability easier to build than the last.
