# ADR-034 — The capability-build pipeline is proven manually before any automation, and automation builds in isolation without self-install authority

## Status

Accepted. Recorded August 9, 2026, as part of the V0.3/V0.4 architecture
lock. See `docs/CAPABILITY_ARCHITECTURE.md` §6 (V0.3E, V0.4A).

## Context

The long-term vision includes MootOS building missing capabilities itself,
in isolation, then presenting them for installation after review. Building
that automation before the underlying process (goal → gap → spec → build →
review → merge → install) has ever been run successfully risks automating
a process nobody has confirmed actually works — the automation would be
optimizing and repeating whatever mistakes the untested process contains,
at machine speed.

## Decision

**Before MootOS writes new capabilities itself, the full pipeline is proven
by hand:**

```text
goal -> gap analysis -> proposed capability specification -> human approval
to build -> isolated branch -> implementation -> automated gates ->
distinct AI reviews -> fixes -> PR -> human merge approval -> live
verification -> capability becomes installed/available
```

At least **two** real capabilities must pass this pipeline before any part
of it is automated — one success could be a lucky or unusually easy case;
two establishes the process generalizes. The recommended first proof
capability is live web/current-information search (the V0.3C
world-awareness connector): low-risk, read-only, genuinely useful, and a
real test of every pipeline stage.

**Only after that** does V0.4A (Capability Builder Automation) begin.
Automation may generate proposed contracts, implementation plans, tool
modules, tests, documentation, and registration changes — but only inside
an isolated build environment, and it **may not install into production
itself**. Every artifact it produces goes through the identical mechanical
gates (ADR-031), distinct AI review (ADR-032), and human merge/install
approval that the manual pipeline used — automation changes who drafts a
change, never who approves or installs it.

The richer capability lifecycle state machine (proposed → specified →
sandbox-implemented → tested → reviewed → approved → installed →
deprecated → rolled back, or similar) is deferred to this phase. Building
it before V0.4A exists would be state machinery with nothing yet requiring
that many states — V0.3A only needs a two-state `available`/`gap`
distinction (ADR-028).

## Consequences

### Positive

- Prevents automating an unproven process — the single highest-leverage
  ordering decision in this whole architecture, matching the shared
  instinct behind both the original review request and Grok's review.
- Gives V0.4A a real, working reference process to automate against
  instead of a theoretical one, which should make the automation itself
  simpler to build correctly.
- "May not install into production itself" is a durable, simple rule that
  remains true no matter how sophisticated the builder becomes later —
  it doesn't need to be re-derived or re-approved as automation improves.

### Tradeoffs

- Two full manual passes through the pipeline is real, non-automatable
  work before any capability-builder automation exists. This is the
  intended cost of this decision, not an oversight.
- This ADR does not specify what happens if the two manual proof runs
  reveal the pipeline itself needs redesign — in that case, redesign
  happens (via a new ADR if the design changes materially) and the
  two-pass proof requirement restarts against the corrected pipeline.

## Follow-on direction

See `docs/CAPABILITY_ARCHITECTURE.md` §6 (V0.3E, V0.4A) and §9 ("large
lifecycle machinery before the builder exists" is explicitly listed as
deferred).
