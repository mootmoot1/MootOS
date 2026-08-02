# ADR-022: Deterministic model-input budgets and capability manifest

## Status

Accepted for Version 0.1 Hardening Pass #2.

## Context

Before this change, one provider request could include up to 20 stored history
messages, the current request, and 20 memories without one aggregate MootOS-owned
limit. Assistant output length is provider-controlled, so the actual request size
was not safely described by the user-message validation limit alone.

Conversation guidance also told the model to be honest about capabilities, but the
running system did not provide one concise, code-owned list of what MootOS can and
cannot actually do. Production testing showed that general guidance was not enough:
the model could still imply that it could coordinate with people or make a
reservation.

## Decision

MootOS prepares every provider request through `backend/model_input.py`.

The current Version 0.1 character budgets are:

- 120,000 MootOS-counted characters across instructions, message roles, and message content
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

If the fixed core plus current request cannot fit, request preparation fails closed.
`ModelRouter` converts that internal budget failure to the existing sanitized model
provider error boundary, so private content and implementation details do not reach
the browser.

The capability manifest is code-owned and provider-independent. It distinguishes:

- helping plan or draft an action
- an application feature existing in the running product
- the chat model actually having access to invoke that feature
- truthfully reporting that an action completed

The manifest lists the capabilities available in Version 0.1 and explicitly names
unavailable web, business lookup, messaging, reservation, purchase, calendar,
deployment, external-tool, and background-work capabilities. It also states that
the memory review interface exists but is not directly clicked or invoked by the
chat model.

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
- Internal budget failures remain behind a fixed public error response.
- Capability instructions are fixed and testable instead of being left to provider personality alone.

### Limitations

- Character counts are only an approximate proxy for provider tokens.
- The capability manifest is a fixed provider instruction, not a deterministic output validator. Representative tests and production checks can reduce false claims but cannot guarantee every future model response. A future response-policy layer could add stronger enforcement if needed.
- The application still retrieves at most 20 active memories before budgeting.
- A selected history window can begin with an assistant message when the oldest
  user message falls outside the budget.
- The budgeter reads the existing rendered memory block, whose normal entry
  boundary is a line beginning with `- [`. Multiline continuation text is kept
  with its entry, but a memory deliberately containing a new line that imitates
  that exact entry prefix can be counted as another budgeting unit. It remains
  untrusted context and gains no instruction priority. A future structured handoff
  can remove this formatting dependency.
- The manifest describes current Version 0.1 capabilities; future tool work must
  update code, tests, and documentation together.
- This decision does not add tools, browsing, idempotency, multi-replica support,
  a tokenizer dependency, or an extra summarization model call.

## Verification

Tests must verify that:

- the current message is preserved fully
- oldest history drops first and remaining history is chronological
- lowest-ranked memories drop first
- normal multiline memory continuation remains one ranked entry
- fixed identity, capability, and conversation rules remain present
- total prepared input stays within the configured character budget
- diagnostics expose only counts and totals
- internal budget failures are sanitized by the router
- the router sends the prepared request unchanged to the selected provider
