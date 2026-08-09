# MootOS Capability Architecture (V0.3 / V0.4)

**Status:** Locked architecture for the next major phase. Recorded August 9,
2026. This document is a plan, not an implementation record. **V0.3A
(Capability-Aware Tool System) is implemented and merged** — see
`docs/TOOL_SYSTEM.md` §16 for what exists in code. **V0.3B (Structured Gap
Reasoning) is implemented on branch
`claude/v0.3b-structured-gap-reasoning`, pending merge** — see
`docs/GAP_REASONING.md`. V0.3C–V0.3E and V0.4A–V0.4D remain plan only,
nothing implemented.
**Applies to:** design and build order for everything after V0.2A.
**Companion documents:** `docs/TOOL_SYSTEM.md` (the current executable Tool
System), ADR-027 (the V0.2A decision record), ADR-028 through ADR-034 (the
decisions this document encodes — see §11), `ARCHITECTURE.md` §8,
`ROADMAP.md`.

This document exists so Claude, Grok, Codex, ChatGPT, and future MootOS
sessions build against one reconciled plan instead of each re-deriving or
re-negotiating the architecture from a chat transcript. When this document
and a chat conversation disagree, this document (and the ADRs it points to)
wins until a new ADR supersedes it.

## 1. Why this document exists

V0.2A gave MootOS a small, fail-closed way to *invoke* a controlled set of
internal actions. The next phase is about MootOS accurately *knowing what it
has*, *reasoning about what it's missing*, and — much later, and only after
the process is proven by hand — *safely gaining new abilities with human
approval at every step*. That phase touches self-description, gap reasoning,
review process, and eventually self-building, all of which are easy to
over-build. This document is the boundary: it says what gets built, in what
order, and — just as importantly — what is deliberately deferred.

## 2. Non-negotiable: the Tool Registry remains the only executable source of truth

`backend/tool_registry.py` (see `docs/TOOL_SYSTEM.md` §4) stays the single
place that determines what MootOS can actually invoke. There is **no second
executable Capability Registry**. A tool is one invocable, registered
action — explicit registration, fail-closed lookup, no plugin discovery, no
model-supplied executor resolution, exactly as V0.2A already built it.

Everything this document adds is either:

- metadata *on* a `ToolDefinition` (extending the existing contract), or
- a semantic/reasoning layer *above* the registry that reads it but never
  becomes a second thing capable of executing.

If a future design ever proposes a capability that can run without a
corresponding registered `ToolDefinition`, that design is wrong under this
architecture and needs a new ADR to change this rule, not a workaround.

## 3. Conceptual model

Use this vocabulary consistently in code, docs, and prompts:

| Term | Definition |
| --- | --- |
| **Resource** | The thing being acted on: a Task, a Memory, a file, a repo, an email, a calendar event. Not executable. |
| **Connector** | The access boundary to an external system: web search, GitHub, Dropbox, a local device. Owns reachability/auth, not business logic. Added one at a time, concretely, as a real tool needs it — not built ahead of time as a generalized framework (see §9). |
| **Tool** | One registered, invocable action using the existing Tool Registry (`docs/TOOL_SYSTEM.md` §3–4). Implemented using zero or more connectors, reads/writes zero or more resources. This is the only executable layer. |
| **Capability** | A semantic grouping/ability backed by one or more tools (e.g. "manage tasks," "search the web," "archive files"). Capabilities describe and group; **they do not execute anything themselves.** A capability with no backing tool is a gap, not a broken capability. |
| **Workflow / Plan** | A runtime composition of tools for one user goal. This already exists implicitly as the bounded model↔tool conversation loop (`backend/tool_conversation.py`), already Run-audited. Not a persisted, versioned object at this stage (see §9). |

**"Primitive" is deliberately not introduced as a separate architecture
layer yet.** Today a tool already is the smallest unit — a thin adapter over
a domain helper (`backend/tools_reference.py`). A distinct "primitive"
layer beneath "tool" only earns its place once generated/composite tools
exist to justify it, which is V0.4A territory at the earliest. Do not name
it as a layer before then.

## 4. Source-of-truth hierarchy

| Question | Authority |
| --- | --- |
| What can execute? | The Tool Registry (`backend/tool_registry.py`) |
| What abilities do installed tools represent? | The generated capability catalog (§5) |
| What does a goal appear to require? | A structured, advisory Gap Report (§6, V0.3B) |
| What is actually installed? | Deployed code/version/commit |
| What should be built next? | Human-approved roadmap/build specification |

**Model memory is authoritative for none of these.** A model recalling that
it "has" a capability, from conversation history or training, proves
nothing about what is actually registered. This extends the existing
capability-honesty rule already enforced by `CAPABILITY_MANIFEST`
(`backend/model_input.py`; see ADR-022) to every new reasoning layer added
below.

## 5. Generated capability manifest

The current model-facing capability text (`CAPABILITY_MANIFEST` in
`backend/model_input.py`) is hand-maintained prose. That is a known,
accepted gap for V0.2A, and it is exactly the kind of drift this phase
exists to close: nothing enforces that the prose still matches the
registry after a tool is added, removed, or changed.

**Decision:** the model-facing capability manifest/catalog must eventually
be generated from the actual registered tool/capability metadata, not
authored by hand. See ADR-029. This does not have to happen in one step —
V0.3A's job is to make the registry metadata rich enough that generation is
possible; the generation step itself can land incrementally as long as the
manifest is never allowed to assert a capability the registry doesn't back.

## 6. Phase roadmap

### V0.3A — Capability-Aware Tool System

**Implemented and merged.** See `docs/TOOL_SYSTEM.md` §16 for the concrete
result (`backend/capability_catalog.py`, extended `ToolDefinition`) and
ADR-028/ADR-029 for the decisions it carries out.

**Purpose:** make MootOS accurately understand what it already has.

Extend `ToolDefinition` with only what gap reasoning and an honest
self-description actually need:

- side effects
- idempotency
- limitations
- dependencies
- semantic capability/category references, as needed to group tools under
  the Capability concept in §3

**Do not mark missing capabilities as registered tools.** A capability
MootOS doesn't have yet is not a `ToolDefinition` with a stub executor —
missing-capability information belongs in gap reports and catalog
reasoning (V0.3B), never in the registry itself. The registry only ever
describes what is real.

**Expected outcome:** MootOS can truthfully answer "What can you currently
do?" from the live registry/catalog — see Definition of Done §10, item 1.

### V0.3B — Structured Gap Reasoning

**Implemented on branch `claude/v0.3b-structured-gap-reasoning`, pending
merge.** See `docs/GAP_REASONING.md` for the concrete result
(`backend/gap_reasoning.py`) and ADR-030 for the decision it carries out.

Natural-language goal interpretation is inherently non-deterministic; the
architecture doesn't pretend otherwise. The flow is two stages with a hard
seam between them:

```text
user goal (natural language)
  -> model interpretation                      [non-deterministic]
  -> structured proposed capability requirements
  -> deterministic resolution against the installed registry/catalog   [deterministic]
```

Only the second stage — checking a structured requirement list against
what's actually registered — is deterministic and auditable. The first
stage is always an interpretation, and its output is always treated as a
proposal, never as fact.

Classify each goal into exactly one of:

- **already possible** — every required capability is installed
- **composable** — every required capability is installed and more than
  one is involved. This means the pieces exist, not that combining them
  has been proven achievable — V0.3B has no composition planner (see
  `docs/GAP_REASONING.md`); it is a candidate composition, never a
  verified executable plan
- **capability gap** — a real capability is missing but plausibly buildable
- **impossible / externally blocked** — the *model* judges this not
  achievable under current permissions, or not a MootOS-appropriate
  action at all; this is always a model interpretation, not something
  MootOS's registry verifies

**Gap reports are advisory, auditable artifacts.** They are logged (extend
the existing Run pattern — see `docs/TOOL_SYSTEM.md` §8) so a hallucinated
or wrong gap claim is visible and reviewable. A gap report can never itself
make anything executable — turning "capability gap" into a registered tool
always goes through V0.3E's human-approved build pipeline, never
automatically.

### V0.3C — Narrow Self-Awareness + World Awareness

Both are read-only and can ship in the same broad phase; neither depends on
the other.

**Self-awareness** is deliberately curated, not unrestricted repository
access:

- tool/capability catalog (from the registry itself)
- current version/commit
- architecture docs, roadmap, ADRs, `docs/TOOL_SYSTEM.md`
- selected source paths, only when a specific, justified need exists

Do not design "let the model browse the repo" as the first version — an
unrestricted surface produces a confidently wrong self-model, which is
worse than a narrow but accurate one.

**World awareness** adds one deliberate, logged web/current-information
search capability — the first meaningful external connector. It is the
concrete proof case for the Connector concept in §3: one real connector,
built because a real capability needs it, not a generalized framework built
in advance.

### V0.3D — Protected Core + Mechanical Release Gates

Safety rules become enforceable gates before any self-building work begins.

**Protected areas** (at minimum):

- auth/session enforcement
- Tool permission enforcement (`backend/tool_executor.py`'s risk/approval
  checks)
- the approval state machine (`backend/tool_operations.py`)
- secret/env handling
- production deployment configuration (e.g. `railway.toml`)
- production `main`
- core registration authority (`build_default_registry` and the explicit
  registration call path)

**Migrations get nuanced treatment, not a blanket block:** the migration
*machinery* (`backend/migrations.py`) and *existing* migrations are
protected — nothing automated may alter how migrations run or rewrite a
past migration. A **new, additive** migration proposed by an approved
capability change may pass through a *higher* review gate (stricter review,
still human-approved) rather than being unconditionally forbidden. The
distinction is: rewriting history is always blocked; adding new, reviewed,
additive schema is allowed under stricter scrutiny.

**Mechanical gates** (block automatically, no exceptions):

- tests pass
- contract/schema validity (a proposed tool's metadata conforms)
- required risk classification present and non-default
- protected-path check (a diff touching a protected area fails closed)
- secret scan
- migration safety check, where relevant, per the nuance above
- no execution outside the central Tool path
- no approval bypass
- exact branch/commit identity (a gate result is only valid for the exact
  commit it ran against)

AI review is advisory (§7–8). Human approval controls merge, install, and
deploy — always, with no exception carved out for this phase.

### V0.3E — Manual Capability-Build Pipeline

Before MootOS writes new capabilities itself, the process is proven by
hand, end to end:

```text
goal
  -> gap analysis
  -> proposed capability specification
  -> human approval to build
  -> isolated branch
  -> implementation
  -> automated gates
  -> distinct AI reviews
  -> fixes
  -> PR
  -> human merge approval
  -> live verification
  -> capability becomes installed/available
```

**At least two real capabilities must pass this pipeline before any part of
it is automated.** One success could be luck or an easy case; two
establishes the process actually generalizes.

**Recommended first proof capability:** live web/current-information
search (the V0.3C world-awareness connector) — low-risk, read-only, and
genuinely useful, so the first run of this pipeline proves the process on
something real rather than a toy.

### V0.4A — Capability Builder Automation

Only after the manual pipeline (V0.3E) has proven itself at least twice.

MootOS may generate, in an isolated build environment:

- proposed contracts
- implementation plans
- tool modules
- tests
- documentation
- registration changes

**It may not install into production itself.** Every artifact it produces
still goes through the same mechanical gates, distinct AI reviews, and
human merge/install approval as the manual pipeline — automation changes
who drafts the change, never who approves it.

**This is where a richer capability lifecycle becomes useful** (proposed →
specified → sandbox-implemented → tested → reviewed → approved → installed
→ deprecated → rolled back, or similar). Do not build that lifecycle
machinery before this phase — see §9.

### V0.4B — Local MootOS Node

Usage-gated by an actual capability gap surfaced through real V0.3B gap
reasoning, not built merely because the roadmap reaches this letter.

Starts strictly read-only:

- storage inspect
- file list
- file search
- metadata

No ambient shell. No root. No arbitrary command execution. No deletion.
Later, narrow writes (copy/move) may be added, and only behind the same
frozen-approval mechanism V0.2A already established for writes
(`docs/TOOL_SYSTEM.md` §9) — never a new, separate approval model.

### V0.4C — Codex Worker Bridge

Codex is already available as a manual local worker; `AGENTS.md` (merged on
`main`) already defines its boundaries — read-only `main`, dedicated
branch/worktree required, no secrets access, no destructive git operations,
no unauthorized commit/push/merge/PR. Automatic MootOS → Codex job dispatch
is later work on top of that existing manual boundary, not a redesign of
it.

When automatic dispatch does arrive, Codex remains just another controlled
worker:

- isolated checkout/worktree
- exact base commit
- an approved specification (from V0.3E/V0.4A's pipeline)
- allowed commands only
- no production secrets
- returns a diff/commit/tests/results, nothing more

**It gets no special merge or deploy authority** — Codex's output goes
through the same gates and human approval as any other capability-builder
output.

### V0.4D — Real Composition Mission

Prove the whole architecture on a real mission, e.g.:

> "Organize local storage and archive selected files to cloud without
> permanent deletion."

The point of this milestone is proving that a higher-level goal is
achieved by *composing existing capabilities* — file search/move, a cloud
archive connector, approval-gated writes — rather than by building one
large, single-purpose "computer cleaner" tool. If this mission ends up
needing one giant bespoke tool instead of composed smaller ones, that's a
signal the capability model in §3 needs revisiting, not that this mission
was the wrong test.

## 7. Review responsibilities

| Role | Responsibility |
| --- | --- |
| **Claude** | Implementation correctness and maintainability |
| **Grok** | Adversarial security, permissions, bypasses, unsafe edge cases |
| **ChatGPT** | Architecture, duplication, intent-vs-implementation, coordination |
| **Codex** | Local execution, test reproduction, concrete coding/testing work |
| **MootOS** | Goal/capability/build-state tracking |
| **Moot** | Final product/merge/deploy authority |

**No multiple agents edit the same working tree concurrently.** Isolation
(separate branch/worktree/checkout per agent) is a hard rule, not a
preference — it's what makes "distinct roles" meaningful instead of
theater; see §8.

## 8. Automated gates vs. advisory review

**Automated/mechanical gates may block.** Anything in V0.3D's gate list
(§6) is non-negotiable and enforced without a human in the loop for the
block itself — a failing gate stops the change regardless of who or what
produced it.

**AI reviews advise.** Every reviewer in §7 (Claude, Grok, ChatGPT, Codex
in its review capacity) produces findings a human reads. None of them can
merge, install, or deploy anything, individually or in combination.

**No model receives production approval authority.** This holds even if
every AI reviewer agrees a change is safe — agreement among models is not
the same thing as Moot's approval, and this architecture never treats it
as a substitute.

## 9. What NOT to build yet

Explicitly deferred, with the reasoning for each:

- **A second executable capability registry** — the Tool Registry already
  is the executable source of truth (§2); a second one only creates drift.
- **A generalized connector framework** — build connectors one at a time,
  concretely, as real tools need them (web search first, §6 V0.3C);
  generalize only once 2-3 concrete connectors exist to generalize from.
- **Arbitrary shell/root access** — never in scope for the Local Node
  (§6 V0.4B) or any connector.
- **Autonomous deployment** — V0.4A's builder may not install into
  production itself, full stop (§6).
- **Multiple builders/agents in one working tree** — always isolated
  branches/worktrees (§7).
- **A persistent workflow engine** — Workflow/Plan stays a runtime
  concept (§3) until recurring multi-step automation is a demonstrated
  real need.
- **A large dependency-graph engine** — a flat `depends_on` list on tool
  metadata (§6 V0.3A) is sufficient at current and near-term scale.
- **Capability self-installation** — every install requires explicit
  human approval, at every phase, with no planned exception.
- **Large lifecycle machinery before the builder exists** — the full
  proposed→...→rolled-back state machine belongs to V0.4A (§6), not
  V0.3A. Until then, a capability is just `available` or `gap`.

## 10. Definition of done for the foundation

1. MootOS can truthfully answer what it can currently do, from generated,
   current metadata (not hand-maintained prose).
2. It can produce a structured, logged gap report for a stated goal.
3. Model-selected writes still cannot bypass frozen approval — this must
   remain true through every change in this document.
4. Protected core is mechanically guarded (§6 V0.3D) before any builder
   automation (§6 V0.4A) exists.
5. New capabilities cannot become installed without human approval, at any
   phase, including after builder automation exists.
6. The Local Node, once present, cannot exceed its allow-list.
7. Adversarial attempts to invent capabilities or bypass controls fail
   closed.
8. Model-facing capability descriptions cannot drift from the executable
   registry, because they are generated from it (§5), not authored
   separately.

## 11. Related ADRs

- **ADR-028** — Capability is semantic grouping over the Tool Registry, not
  a parallel executable registry.
- **ADR-029** — The model-facing capability manifest/catalog is generated
  from installed registry metadata.
- **ADR-030** — Gap reports are structured, logged, advisory artifacts.
- **ADR-031** — Protected core is enforced mechanically before
  capability-builder automation.
- **ADR-032** — Multi-AI review is advisory with distinct roles; only
  mechanical gates and human approval control release.
- **ADR-033** — Local Companion and automatic Codex integration are
  usage-gated later capabilities, not V0.3A prerequisites.
- **ADR-034** — The capability-build pipeline is proven manually before any
  automation, and automation builds in isolation without self-install
  authority.
