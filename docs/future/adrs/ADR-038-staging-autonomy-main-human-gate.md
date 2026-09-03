# ADR-038 — Staging autonomy requires separate authorization; Main remains human-gated

## Status

Proposed. No staging or GitHub execution is enabled by this record.

## Decision

Publication and promotion are five distinct facts: verified artifact eligibility; recorded human decision; authorization of one exact external action; preparation of an inert action envelope; and a separately authorized executor's reported outcome, which remains unverified until independently reconciled.

V0.4C already demonstrates this separation offline for PR publication. Continuous Builder must preserve it for GitHub and Staging. “Approved” never means executed, and a reported external success never means independently verified truth.

The earlier proposal for promotion after roughly five hours of human inactivity is **not adopted or enabled**. Time alone grants no authority. Any future unattended Staging promotion requires a new ADR defining authenticated authorizers, repository and environment scope, credentials, executor, independent verification, uncertain-outcome reconciliation, rollback, and kill switches.

Main merge and production deployment remain explicit human actions. No inactivity window, model score, passing test suite, accumulated history, or Staging success may authorize them.

## Required future boundaries

- authorization binds repository, base/head identities, exact artifact digests, operation, environment, and explicit expiry, if any;
- preparation creates an inert, single-purpose envelope;
- execution owns narrowly scoped credentials and records request identity without claiming durable idempotency unless persistence proves it;
- verification independently reads external state and binds observed truth;
- uncertain outcomes stop automatic progress until reconciliation;
- rollback is a new authorized action, not an implicit executor privilege.

## Consequences

Continuous Builder may prepare review evidence before those boundaries exist. It may not push, open/edit/close/merge a PR, promote Staging, deploy, or retry an uncertain external action.
