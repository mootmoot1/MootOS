# ADR-025: Model Run Logging v0.1

## Status

Accepted for implementation on `feature/model-run-logging-v0.1`.

## Context

MootOS can already hold persistent conversations, save and correct long-term memories, import a curated profile, retrieve relevant context, and route requests through a replaceable model provider.

The next architecture phase prepares MootOS for future tools, tasks, approvals, and automation. Before MootOS is allowed to perform more external actions, it needs a durable execution record that answers:

- what attempted to run
- which provider/model/tool handled it
- when it started and finished
- whether it succeeded or failed
- which conversation/messages caused or resulted from it
- what token/cost metadata is available
- what broad data-exposure class was involved

The architecture discussion established a durable distinction:

- **Task** = an intention or commitment that may persist over time.
- **Frozen operation specification** = the exact side effect proposed for later policy/approval checks.
- **Approval** = durable authorization bound to that exact frozen specification.
- **Run** = one actual execution attempt.

Version 0.1 implements only the Run spine for model generations. It does not implement Tasks, external Tools, Approval UI, Observations, Entities, or an Operation table.

## Decision

Add a versioned SQLite `runs` table and a dedicated run-storage module.

A model run record contains execution metadata only. It does **not** duplicate private prompts, retrieved memory context, or assistant response text. Conversation and message content remain in the existing conversation/message tables.

Model runs use these lifecycle states:

- `started`
- `succeeded`
- `failed`

A run is created before a provider request is made. A successful run is finalized after the corresponding chat turn is safely committed so the run can reference the saved user and assistant message IDs. A failed provider request is finalized even when a new conversation/message was never committed.

For that reason, Version 0.1 stores conversation/message identifiers as nullable references without foreign-key constraints. This is deliberate: a failed model call must remain auditable while preserving the existing rule that a failed model response does not save a new chat message.

Error logging stores only a sanitized exception class, not raw exception messages or provider response bodies.

Token and cost fields are nullable. MootOS records those values only when the selected provider actually exposes reliable values. It must not invent usage or cost estimates and label them as measured data.

The current `runs` schema anticipates future `tool` run types, but Version 0.1 does not provide a tool executor.

## Security and privacy rules

1. Run records must not contain API keys, credentials, cookies, raw authorization headers, or secrets.
2. Run records must not duplicate the raw user prompt, model instructions, retrieved private memory context, or raw assistant response.
3. Provider failures record a sanitized error class instead of the raw exception message.
4. Future external write tools must create a Run through the controlled executor path rather than bypassing the run/audit spine.
5. High-risk future operations will require policy evaluation and approval bound to an immutable operation specification before the Run begins.
6. A changed approved operation must require a new approval; mutable Task state must never silently inherit authorization for changed parameters.

## Schema

Version 0.1 adds:

- `id`
- `run_type`
- `status`
- `conversation_id`
- `user_message_id`
- `assistant_message_id`
- `provider`
- `model`
- `started_at`
- `finished_at`
- `duration_ms`
- `error_class`
- `input_tokens`
- `output_tokens`
- `cost_usd`
- `data_exposure`

Indexes support recent-run, conversation-run, and status-run queries.

## What stays unchanged

- projects
- conversations
- append-only messages
- memory active/superseded/archived lifecycle
- bootstrap-profile import
- deterministic semantic memory retrieval
- replaceable model-provider boundary
- authentication and private response headers
- Railway single-replica SQLite deployment

## Deferred concepts

Do not build yet:

- Task system
- Tool execution system
- Policy table/engine
- Approval interface
- dedicated Operation table
- Observation/Signal table
- Entity graph
- generic Relation table
- vector database
- multi-agent orchestration

## Consequences

### Positive

- Establishes an execution/audit spine before external tools exist.
- Makes failures inspectable without saving failed chat turns.
- Preserves provider/model replaceability.
- Avoids multiplying sensitive prompt/response copies in SQLite.
- Gives future Tasks, Tools, Policy, and Approval a stable execution target.

### Costs

- Adds one schema migration and one new lifecycle to maintain.
- Successful run/message linkage requires coordination with chat persistence.
- Version 0.1 does not yet provide a user-facing Run review screen.

## Next architecture steps

After Model Run Logging v0.1 is production-verified, the likely next primitive is Task v0.1. External write tools should not be introduced until the Tool/Policy/Approval/frozen-operation path is designed and implemented.