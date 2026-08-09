# ADR-032 — Multi-AI review is advisory with distinct roles; only mechanical gates and human approval control release

## Status

Accepted. Recorded August 9, 2026, as part of the V0.3/V0.4 architecture
lock. See `docs/CAPABILITY_ARCHITECTURE.md` §7–8.

## Context

The product vision calls for Claude, Codex, Grok, and ChatGPT review as
part of getting a new capability safely built and merged. Asking multiple
general-purpose AI reviewers the same generic "review this" question
produces redundant, low-signal output — agreement between three models
answering the same prompt is not independent verification, and disagreement
between them doesn't mechanically resolve anything on its own. That pattern
is review theater: it looks like scrutiny without functioning as a gate.

## Decision

Each reviewer role gets a distinct, non-overlapping responsibility instead
of duplicate general review:

| Role | Responsibility |
| --- | --- |
| Claude | Implementation correctness and maintainability |
| Grok | Adversarial security, permissions, bypasses, unsafe edge cases |
| ChatGPT | Architecture, duplication, intent-vs-implementation, coordination |
| Codex | Local execution, test reproduction, concrete coding/testing work |
| MootOS | Goal/capability/build-state tracking |
| Moot | Final product/merge/deploy authority |

**Automated/mechanical gates (ADR-031) may block a change. AI review may
never block or unblock a change by itself.** Every AI review — regardless
of role, and regardless of how many roles agree — produces findings a human
reads before deciding. No model receives production approval authority,
even collectively.

No multiple agents edit the same working tree concurrently — review and
implementation happen in isolated branches/worktrees/checkouts per agent
(ADR-034 covers this for the build pipeline specifically).

## Consequences

### Positive

- Each review pass has a specific job it can be checked for having done,
  instead of a vague "looks fine" that doesn't reveal what was actually
  scrutinized.
- Removes the failure mode where multiple models agreeing is mistaken for
  independent confirmation — they're each looking at something different,
  so agreement is more meaningful and disagreement is informative rather
  than just noise to average away.
- Keeps human approval as the one place release authority actually lives,
  which was already MootOS's stated design principle (`ARCHITECTURE.md`
  §2, "User control") — this ADR makes it concrete for the multi-AI case
  specifically.

### Tradeoffs

- Requires actually invoking different reviewers for different concerns
  rather than one blanket review pass, which costs more per change than a
  single generic review would. Accepted, because the alternative doesn't
  reliably catch anything a single pass wouldn't.
- Role names here map to specific external providers (Claude, Grok,
  ChatGPT, Codex) that may change over time; the responsibilities are the
  durable part of this decision, not the specific vendor mapping.

## Follow-on direction

See `docs/CAPABILITY_ARCHITECTURE.md` §7–8, and ADR-034 for how this plugs
into the actual build pipeline.
