# ADR-022: Deterministic model-input budgets and capability manifest

## Status

Accepted for Version 0.1 Hardening Pass #2.

## Context

Before this change, one provider request could include up to 20 recent messages at
20,000 characters each plus 20 memories at 10,000 characters each. The effective
request size depended on the data and provider rather than a MootOS-owned limit.

Conversation guidance also told the model to be honest about capabilities, but the
running system did not provide one concise, code-owned list of what MootOS can and
cannot actually do. Production testing showed that general guidance was not enough:
the model could still imply that it could coordinate with people or make a
reservation.

## Decision

MootOS prepares every provider request through `backend/model_input.py`.

The current Version 0.1 character budgets are:

- 120,000 characters for the complete provider request
- 64,000 characters for earlier conversation history
- 32,000 characters for ranked long-term-memory entries

These are deterministic character limits. They do not depend on a provider
tokenizer and do not require an extra model call.

The latest supplied message is treated as the current user request and is never
truncated by the budgeter. The fixed identity, capability manifest, conversation
rules, and conversation-state hint are also never truncated.

When optional context must be reduced:

1. recent history is selected from newest to oldest
2. selected history is restored to chronological order
3. lowest-priority old history is removed first
4. memories retain the highest-ranked prefix returned by memory retrieval
5. lowest-ranked memories are removed first

The capability manifest is code-owned and provider-independent. It distinguishes:

- helping plan or draft an action
- actually having access to the relevant service
- truthfully reporting that an action completed

The manifest lists the capabilities available in Version 0.1 and explicitly names
unavailable web, business lookup, messaging, reservation, purchase, calendar,
deployment, external-tool, and background-work capabilities.

Budget diagnostics contain counts and character totals only. They do not log
message text, memory text, project names, IDs, search terms, or provider payloads.

## Consequences

### Benefits

- Provider requests have a predictable upper bound.
- The current request and fixed safety/capability rules are preserved.
- Recent context is preferred over stale context.
- Ranked memory order remains meaningful under pressure.
- Capability honesty is based on the running application, not provider personality.
- The design remains provider-independent and works for future local models.

### Limitations

- Character counts are only an approximate proxy for provider tokens.
- The application still retrieves at most 20 active memories before budgeting.
- A selected history window can begin with an assistant message when the oldest
  user message falls outside the budget.
- The manifest describes current Version 0.1 capabilities; future tool work must
  update code, tests, and documentation together.
- This decision does not add tools, browsing, idempotency, multi-replica support,
  a tokenizer dependency, or an extra summarization model call.

## Verification

Tests must verify that:

- the current message is preserved fully
- oldest history drops first and remaining history is chronological
- lowest-ranked memories drop first
- fixed identity, capability, and conversation rules remain present
- total prepared input stays within the configured character budget
- diagnostics expose only counts and totals
- the router sends the prepared request unchanged to the selected provider
