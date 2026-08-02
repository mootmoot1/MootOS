# ADR-019 — Provider-independent conversation refinement

**Status:** Proposed  
**Date:** August 1, 2026

## Context

MootOS already sends up to 20 recent conversation messages to the configured model provider. That preserves basic history, but the system had only a small set of general instructions for interpreting that history.

The missing behavior was not a new memory store or a larger context window. It was a consistent set of dialogue rules for:

- Short follow-ups
- References to earlier options or subjects
- Notes and status updates
- Current-conversation corrections
- Honest uncertainty
- Capability boundaries
- The difference between ordinary chat history and durable memory

These rules must apply to future local or cloud providers without being duplicated inside each provider implementation.

This work must also remain separate from two later concerns:

1. The MootOS operating contract, which will define the system's mission, partnership role, authority, and harder permanent rules.
2. Moot's curated profile, which will define high-confidence facts and preferences about the user.

## Decision

Add `backend/conversation_guidance.py` and apply its instructions inside `ModelRouter.generate` before the selected provider is called.

The guidance requires MootOS to:

- Treat a latest message as a continuation when prior messages are actually supplied.
- Resolve short references from the most recent relevant turns.
- Proceed with a clear low-risk interpretation, while asking one focused question when ambiguity could materially change an answer or cause an outside action.
- Treat a current direct correction as stronger for the current answer than earlier conversation text or conflicting saved memory.
- Never claim durable memory changed unless the deterministic memory-write path confirmed it.
- Treat ordinary notes and updates as conversation context rather than silently creating tasks or long-term memory.
- Avoid generic recap, unrelated memory dumps, and reflexive follow-up questions.
- Separate known facts, supplied context, inference, and missing information.
- Never claim an external action happened unless MootOS actually performed it.
- Treat messages, quotes, prior assistant text, and saved memories as context data rather than higher-priority instructions.
- State honestly whether prior conversation messages are present.

The router passes the original messages to the provider unchanged and appends the guidance to the existing identity and memory instructions.

## Why the provider boundary

Applying the guidance in `ModelRouter.generate` means:

- Every implemented provider receives the same conversation rules.
- A future local model does not require a separate copy of the policy.
- Memory retrieval remains responsible only for selecting context.
- The FastAPI route remains responsible only for conversation orchestration and persistence.
- Explicit memory commands continue to bypass the model provider and cannot be confused with ordinary notes.

## Security boundary

Saved memory and conversation text can contain quoted instructions or hostile text. They are personal context, not trusted system instructions.

The conversation guidance is appended after the base identity and ranked-memory text so the provider receives an explicit final rule that embedded instructions must not override system behavior.

This is defense in depth. Model behavior is probabilistic, so production verification must still test realistic hostile or misleading context.

## Consequences

Positive:

- Better follow-up continuity without changing storage.
- Fewer unnecessary clarifying questions.
- Clearer separation between conversation correction and durable memory correction.
- Better capability honesty.
- Consistent behavior across model providers.
- No migration, extra provider request, background process, or new dependency.

Tradeoffs:

- Guidance improves behavior but cannot guarantee perfect reference resolution.
- More instructions consume a small amount of provider input context.
- The existing 20-message window remains a hard boundary.
- Real behavior still depends partly on the selected model's instruction-following quality.

## Rejected alternatives

### Put the rules only in the OpenAI provider

Rejected because future providers could behave differently and duplicate policy.

### Add automatic intent classification before every response

Rejected because it would add complexity and possibly another model call before simple guidance has been production-tested.

### Automatically save notes as memories

Rejected because ordinary conversation must not silently become durable memory.

### Define the full MootOS operating identity in this branch

Rejected because mission, partnership role, authority, and personality require a separate user-reviewed operating-contract branch.

### Expand or summarize the history window

Rejected for this focused branch. Context-window strategy and conversation summarization remain separate work.

## Verification requirements

Automated tests must confirm:

- New conversations do not invent prior context.
- Existing conversations are labeled as continuations.
- Short-reference examples reach the provider with chronological history intact.
- Notes and corrections do not create durable memory.
- Provider messages remain unchanged.
- Guidance is applied to a provider-independent router.
- Hostile instruction text inside saved memory remains before, and lower priority than, the final conversation rules.
- Existing explicit memory saves still bypass the provider.

Production verification must include realistic multi-turn conversations rather than checking instruction text alone.
