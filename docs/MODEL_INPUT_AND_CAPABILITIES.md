# Model input budgets and capability honesty

This document describes the current provider-input boundary in MootOS Version 0.1.

## Why this boundary exists

Conversation history and long-term memory are useful only when they remain bounded,
relevant, and honest. MootOS therefore owns the final request preparation instead
of sending every available character to the provider.

The same boundary also gives every provider a fixed statement of what the running
application can actually do. This prevents personality or model wording from
quietly inventing access to services that MootOS does not have.

## Request preparation order

For normal provider-backed chat:

1. the chat pipeline loads recent history without writing
2. the current user message is appended in memory
3. memory retrieval returns up to 20 active memories in ranked order
4. `ModelRouter` calls `prepare_model_input`
5. fixed capability and conversation rules are added
6. character budgets remove optional old or low-ranked context
7. the bounded request is sent once to the configured provider
8. the atomic chat pipeline saves both sides only after provider success

No extra model call is used for trimming or summarization.

## Character budgets

Current constants in `backend/model_input.py`:

| Input area | Budget |
| --- | ---: |
| Instructions plus message role/content text | 120,000 characters |
| Earlier conversation history | 64,000 characters |
| Ranked memory context | 32,000 characters |

The total counts instruction text plus each selected message role and content. It is an application input-text budget, not the byte size of the serialized provider HTTP request.

The current user message is accepted by the existing API limit of 20,000
characters and is preserved in full. Fixed identity, capability rules,
conversation rules, and the conversation-state hint are also preserved in full.

## History selection

The final supplied message is the current request. All earlier supplied messages
are history.

MootOS walks history from newest to oldest until the history budget is full, then
restores the selected messages to chronological order. Under the total budget,
oldest selected messages are removed first.

This is deterministic. The same input produces the same selected history.

## Memory selection

`backend.memory_retrieval` still decides relevance and order. The budgeter does
not rescore memories.

Memory entries are kept as the highest-ranked contiguous prefix. When the memory
budget or total budget is reached, entries are removed from the lowest-ranked end.
Memory text is not partially truncated.

Normal multiline continuation text remains attached to its ranked entry. The
current handoff uses the existing rendered memory format, where each new entry
starts on a line beginning with `- [`. A memory deliberately containing a new line
that imitates that exact prefix can be counted as a separate budgeting unit. It
remains untrusted context and does not gain authority over fixed instructions.

Only active memories can enter normal model context. Archived and superseded
memory versions remain excluded by the existing retrieval layer.

## Capability manifest

The manifest is deterministic application-owned input. It distinguishes the running application's features from actions that the chat model can directly invoke. It does not claim to be a deterministic validator of every provider output.

**V0.3A: generated from the live Tool Registry, not hand-maintained.**
`backend/capability_catalog.py`'s `render_capability_manifest()` builds
this text fresh from `backend.tool_registry.get_tool_registry()` on every
call — replacing a previously hand-authored prose constant (ADR-022). The
tool-availability lines (which tools run automatically, which require
approval, and each write-capable tool's own argument rules, embedded
verbatim from that tool's registered `description`) can only ever name a
tool that is actually registered; there is no second, independently
maintained list of tool names that could drift from the registry. See
`docs/TOOL_SYSTEM.md` for the full module description and ADR-028/ADR-029
for the decision record.

Available to the current running application:

- text chat through the configured provider
- recent supplied conversation history as chat context
- ranked active long-term memory as chat context
- explicit `remember` and `save this` storage writes
- user-facing memory review, correction, recoverable archive, and restore

The chat model does not directly click or invoke the memory-management controls.
It may explain how Moot can use them, and may report a result only when the
application supplied a confirmed result.

Unavailable to the chat model in the current running version:

- live web search, browsing, or local-business lookup
- sending messages or contacting people
- reservations, purchases, payments, or ordering
- calendar access, scheduling, reminders, or changing appointments
- deployments, repository edits, shell commands, or infrastructure operations
- other external tools and services
- background work after the current response

MootOS may help plan, draft, compare, explain, or prepare steps for an outside
action. That is not the same as accessing the service or completing the action.

A provider response is instructed not to claim that an unavailable action started or completed. Long-term memory may be reported as saved only after the explicit storage path confirms the write.

Because the current boundary is prompt-based, representative tests and production prompts verify behavior but cannot mathematically guarantee every future response. A future response-policy layer may add stronger deterministic checks if concrete failures justify it.

## Diagnostics and privacy

When context is dropped, MootOS logs only:

- history messages kept and dropped
- memories kept and dropped
- final total character count

It does not log message content, memory content, IDs, projects, search terms,
private paths, or full provider payloads.

`ModelRouter.last_input_diagnostics` exposes the same count-only structure for
tests and in-process inspection. It is not returned by the public chat API.

## Failure behavior

If fixed instructions plus the current request ever exceed the complete budget,
the budgeter raises `ModelInputBudgetError` rather than truncating either one.

`ModelRouter` converts that internal exception to the existing fixed
`ModelProviderError` boundary. The normal `/chat` endpoint therefore returns its
generic provider-failure response and does not expose the private request,
instructions, configured limits, or exception text.

With the current API and constants, the 20,000-character request maximum leaves
ample room for the fixed core. The error exists as a fail-closed invariant for
future changes.

Provider and storage failure behavior remains defined by
`CHAT_PROVIDER_PIPELINE.md`.

## Change rules

Any future capability addition must update all of the following in the same PR:

1. actual application code that performs the action
2. the capability manifest (as of V0.3A: register the tool with truthful
   metadata -- the tool-naming portions of the manifest text update
   automatically; a genuinely new *category* of capability, such as a
   fixed "Available"/"Not available" bullet unrelated to any registered
   tool, still requires a manual edit to `render_capability_manifest`)
3. tests proving access and completion claims are truthful
4. this document and the relevant ADR

Do not update the manifest to advertise a planned feature before the running
application can actually perform it.

**V0.2A (merged to `main`, live-verified):**
the manifest named the exact four registered Tool System tools
(`docs/TOOL_SYSTEM.md`), stated that `tasks.create` never runs without
explicit approval, and instructed the model that it may not invent or
assume any other tool name exists -- all as hand-maintained prose at the
time. `tests/test_model_input.py` asserted this wording directly.

**V0.3A (implemented on branch `claude/v0.3a-capability-aware-tool-system`,
pending merge):** the same guarantees now hold by construction rather than
by hand-maintained wording -- see the "Capability manifest" section above.
