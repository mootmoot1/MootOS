# ADR-021 — Atomic chat provider pipeline

**Status:** Proposed  
**Date:** August 2, 2026

## Context

Normal provider-backed chat previously stored the user message before calling the
model provider. If the provider timed out or failed, the database could retain an
unmatched user message. The browser also kept its optimistic user bubble, so a
manual retry could create a duplicate after an ambiguous failure.

The current MootOS deployment is one FastAPI process, one Railway replica, and one
SQLite database. Explicit long-term-memory commands already use their own atomic
storage path and must remain unchanged.

## Decision

Provider-backed chat will use a three-stage pipeline:

1. Load the existing conversation and recent history, or prepare a new conversation
   record in memory without writing it.
2. Append the current user message to the in-memory model input and call the model
   provider without holding a database transaction.
3. After a successful provider response, open one short SQLite transaction with
   `BEGIN IMMEDIATE` and atomically commit the optional new conversation, user
   message, assistant message, and conversation timestamp.

If the provider fails, no conversation or message is committed. If storage fails,
the entire message pair rolls back.

Existing conversations are serialized with an in-process per-conversation lock
across history loading, provider generation, and the final commit. This is correct
for the current one-process, one-replica deployment. It is not a multi-replica
coordination mechanism.

Provider requests use a 45-second total client timeout and zero automatic SDK
retries. MootOS does not retry empty output or provider failures automatically.
Public errors are fixed MootOS messages; raw provider and storage exception text is
kept only in exception chains.

The browser may render a temporary user bubble and typing indicator while waiting.
On failure it removes both, restores the exact composer text, keeps the current
conversation identity unchanged, and never auto-resends.

## Consequences

Positive:

- Provider failure leaves zero new messages.
- New-conversation failure leaves zero new conversations.
- Successful turns store both sides together.
- Storage failure cannot leave a half turn.
- Provider latency does not hold a SQLite write transaction.
- Browser retries are explicit and do not start from a misleading optimistic state.
- Raw upstream errors are not exposed to the user.

Tradeoffs:

- A provider may complete successfully just before the process crashes, causing a
  paid response to be lost before commit. This is preferable to storing an orphan.
- Concurrent turns for one conversation are serialized in one process.
- Multi-replica deployment would require a distributed coordination design.
- Zero automatic retries favors predictable writes over transparent recovery from
  transient transport failures.

## Explicit memory commands

Commands beginning with `remember` or `save this` continue through
`backend/chat_memory.py`. Their conversation, user message, memory row, and
confirmation remain one separate atomic transaction and do not call the provider.

## Rejected alternatives

### Save the user message first and delete it after provider failure

Rejected because cleanup can fail, exposes an intermediate orphan state, and makes
new-conversation rollback more complicated.

### Keep a SQLite transaction open during the provider call

Rejected because a network call can take many seconds and should not hold a write
lock on the production database.

### Automatically resend after a browser or provider error

Rejected because the provider may have processed a request even when the client did
not receive a response. Automatic replay can duplicate cost or behavior.

### Add Redis or a durable job queue

Rejected as unnecessary for the current single-user, one-replica Version 0.1
system.

## Verification requirements

Automated tests must prove:

- New-chat provider failure writes no conversation or messages.
- Existing-chat provider failure leaves history unchanged.
- The provider receives the current user message before that message is persisted.
- A successful turn commits one user and one assistant message.
- Assistant-message storage failure rolls back the complete pair.
- Public provider and storage errors contain no raw exception text.
- The provider client has a bounded timeout and zero automatic retries.
- The browser removes optimistic bubbles and restores composer text on failure.
- Explicit memory-command behavior remains covered by the existing atomic tests.
