# CB-002 — Project State Engine

**Status:** Designing

## Purpose
Give Chief Builder durable, auditable truth about where every slice/project sits in its lifecycle.

## Required state
Store state, reason, actor, entered-at time, blockers, expected next transition, and append-only transition history.

## Lifecycle
idea, researching, designing, ready, scheduled, building, blocked, reviewing, changes_requested, staging, testing, ready_for_main, done, paused, superseded, retired, cancelled.

## Rules
- Every transition requires an explicit reason.
- Invalid skips fail closed.
- Human-required states cannot be silently bypassed.
- Historical state is preserved.

## Acceptance
State can be replayed from history; malformed transitions are rejected; reason/actor are never omitted.
