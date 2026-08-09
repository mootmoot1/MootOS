# ADR-033 — Local Companion and automatic Codex integration are usage-gated later capabilities, not V0.3A prerequisites

## Status

Accepted. Recorded August 9, 2026, as part of the V0.3/V0.4 architecture
lock. See `docs/CAPABILITY_ARCHITECTURE.md` §6 (V0.4B, V0.4C).

## Context

The original long-term discussion named a local MootOS companion node and
automatic Codex-worker dispatch as planned pieces, generally positioned
fairly early because they're part of the eventual vision. Both are new,
real trust boundaries: a local companion is a new process with device
access; automatic Codex dispatch is a new automated producer of code
changes. Building either speculatively — because the roadmap reaches that
point, not because a real goal needs it — adds ongoing maintenance and
attack surface before there's a concrete capability gap they close.

Codex already exists today as a manual local worker, with its boundaries
defined in `AGENTS.md` (merged on `main`): read-only `main`, dedicated
branch/worktree required before editing, no secrets access, no destructive
git operations, no commit/push/merge/PR without explicit authorization.
That manual boundary is sufficient for how Codex is used today.

## Decision

**Local Companion (V0.4B) and automatic Codex dispatch (V0.4C) are
usage-gated, not calendar/roadmap-position-gated.** Neither is built until
a real goal, surfaced through actual V0.3B gap reasoning against a genuine
user request, identifies a concrete need for it. The vision's own example
("organize my computer, archive old stuff...") is the kind of trigger that
should gate the Local Companion — not "the roadmap reached V0.4B."

When the Local Companion is built, it starts strictly read-only (storage
inspect, file list, file search, metadata), with no ambient shell, no root,
no arbitrary command execution, and no deletion. Narrow writes (copy/move)
come later, behind the existing frozen-approval mechanism (`docs/
TOOL_SYSTEM.md` §9) — not a new approval model invented for the local
node.

When automatic Codex dispatch is built, Codex remains just another
controlled worker under the existing `AGENTS.md` boundaries, extended with:
isolated checkout/worktree, exact base commit, an approved specification,
allowed commands only, no production secrets, and a return value limited to
diff/commit/tests/results. It gets no special merge or deploy authority —
its output goes through the same gates (ADR-031) and review (ADR-032) as
any other capability-builder output.

## Consequences

### Positive

- Avoids building two new trust boundaries speculatively, keeping V0.3's
  actual foundation work (registry metadata, gap reasoning, protected
  core) as the near-term focus.
- Keeps the vision's real motivating example as the acceptance test for
  when the Local Companion is worth building, rather than treating roadmap
  position as sufficient justification.
- Reuses the existing frozen-approval mechanism and `AGENTS.md` boundaries
  instead of inventing parallel ones for the local/Codex case.

### Tradeoffs

- This defers concrete design work on the Local Companion's transport and
  process model until it's actually needed, which means that design isn't
  available to review today. Accepted — designing it now would be
  speculative and likely wrong in ways only real usage would reveal.
- "Usage-gated" requires judgment about when a surfaced gap is real enough
  to justify building a new trust boundary; this ADR doesn't remove that
  judgment call, it just states that the call must be justified by an
  actual gap report (ADR-030), not by roadmap sequencing alone.

## Follow-on direction

See `docs/CAPABILITY_ARCHITECTURE.md` §6 (V0.4B, V0.4C) for scope, and
`AGENTS.md` for Codex's current, already-effective manual boundaries.
