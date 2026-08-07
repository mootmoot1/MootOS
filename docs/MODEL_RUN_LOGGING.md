# Model Run Logging v0.1

## Goal

Record one structured execution row for every normal AI model generation without changing the visible chat experience or duplicating private chat content.

## Current implementation

The branch includes:

- schema migration 003 for `runs`
- dedicated `backend/runs.py` storage helpers
- normal `/chat` model-generation integration
- success/failure lifecycle and integration tests
- privacy tests proving the table has no prompt/response/content columns
- a closed `data_exposure` classification set
- explicit terminal-state protection and non-negative metric validation
- ADR-025 documenting the Run/Task/Approval architecture boundary

## Model-call flow

```text
prepare chat turn
    -> identify configured provider/model
    -> create Run(status=started)
       if Run creation fails: stop; do not call provider
    -> call model provider
        -> provider failure:
             best-effort finalize Run(status=failed, sanitized error class)
             do not save chat turn
        -> provider success:
             atomically save user + assistant chat messages
             if chat persistence fails:
                 best-effort finalize Run(status=failed, ChatStorageError)
                 return storage error
             if chat persistence succeeds:
                 finalize Run(status=succeeded, link saved message IDs)
                 if finalization itself fails:
                     return the already-saved chat normally
                     leave the Run in started for later inspection/repair
    -> return existing chat response
```

The current chat guarantee remains unchanged: provider failure must not save a new user/assistant turn.

## Privacy boundary

Run storage is metadata storage, not another conversation store.

Do not write these into `runs`:

- raw prompt text
- raw assistant response text
- complete model instructions
- retrieved long-term-memory context
- API keys
- cookies
- auth headers
- provider exception messages

Use conversation/message IDs to locate normal conversation content when an authenticated user later asks to inspect a run.

## Run fields

| Field | Meaning |
| --- | --- |
| `id` | Stable UUID for one attempt |
| `run_type` | `model` now; `tool` reserved for future executor |
| `status` | `started`, `succeeded`, or `failed` |
| `conversation_id` | Conversation associated with the attempt when known |
| `user_message_id` | Saved user message after successful commit |
| `assistant_message_id` | Saved assistant message after successful commit |
| `provider` | Selected model provider |
| `model` | Selected model name |
| `started_at` | UTC start time |
| `finished_at` | UTC terminal time |
| `duration_ms` | End-to-end run duration measured by MootOS |
| `error_class` | Sanitized exception class on failure |
| `input_tokens` | Provider-reported input tokens when available |
| `output_tokens` | Provider-reported output tokens when available |
| `cost_usd` | Provider-reported or reliably calculated cost only when available |
| `data_exposure` | Closed broad classification: `local`, `model_provider`, or `tool_external` |

`input_tokens`, `output_tokens`, and `cost_usd` remain nullable. A finalizer call that has no new metric value must not erase a previously recorded value.

## Failure behavior

### Provider/configuration failure

If execution has started and the provider fails, finalize the Run as failed when possible. Do not store the raw provider exception message. A secondary failure while finalizing the Run must not replace the original provider error returned to the caller.

### Run-start storage failure

MootOS fails closed. If the Run cannot be created, return a safe service error before calling the model. No unlogged provider request is allowed on the normal chat path.

### Chat-commit failure after model success

The model may return successfully but the conversation turn may fail to commit. The Run must not claim the overall chat execution succeeded. The integration finalizes the Run as failed with a sanitized storage exception class when possible, then preserves the existing chat storage error behavior.

### Run finalization failure after chat success

Once the user and assistant messages are durably committed, an audit-finalization failure must not force the user to resend the same message and risk duplicating the conversation. MootOS returns the saved chat normally and leaves the Run in `started`. That incomplete Run is intentionally detectable and can be repaired by a later operational recovery feature.

### Stuck `started` runs

A process crash, hard termination, or post-commit finalization failure can leave a Run in `started`. That row is evidence that an attempt began but no terminal outcome was recorded. In v0.1, operators should inspect old rows with `status = 'started'` during production verification. A later recovery/sweeper feature may mark abandoned attempts, but this PR does not invent that lifecycle yet.

## Data-exposure classification

The v0.1 closed set is:

- `local` — execution remains within MootOS/local infrastructure
- `model_provider` — request context is sent to the configured model provider
- `tool_external` — reserved for a future external tool executor

These values are classifications only. They must never contain prompt text, recipient addresses, filenames, secrets, or other private payload data.

## Production verification plan

After merge and Railway migration:

1. `/ready` reports ready at schema version 3.
2. Normal chat still works.
3. A successful model request creates exactly one succeeded Run.
4. The Run references the saved conversation/user/assistant message IDs.
5. Provider failure creates one failed Run without saving the failed chat turn.
6. A forced chat-storage failure after model success leaves the Run failed, never succeeded.
7. Run-start failure prevents the model provider call entirely.
8. Run rows contain no raw prompt/response text.
9. No old `started` rows remain after ordinary successful test traffic.
10. Existing memory/profile/retrieval behavior remains unchanged.

## Not in v0.1

- run review UI
- automatic memory extraction
- reminders/tasks
- external tool execution
- approvals
- operation-spec hashing
- inbound observations/webhooks
- abandoned-run sweeper
- cost estimation when provider usage is unavailable

Those should build on this spine rather than being mixed into this PR.
