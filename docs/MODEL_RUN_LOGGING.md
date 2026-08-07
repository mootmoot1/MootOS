# Model Run Logging v0.1

## Goal

Record one structured execution row for every normal AI model generation without changing the visible chat experience or duplicating private chat content.

## Current implementation slice

The branch currently includes:

- schema migration 003 for `runs`
- dedicated `backend/runs.py` storage helpers
- success/failure lifecycle tests
- privacy tests proving the table has no prompt/response/content columns
- ADR-025 documenting the Run/Task/Approval architecture boundary

The next slice wires the existing `/chat` model-generation path into these helpers.

## Intended model-call flow

```text
prepare chat turn
    -> identify configured provider/model
    -> create Run(status=started)
    -> call model provider
        -> provider failure:
             finalize Run(status=failed, sanitized error class)
             do not save chat turn
        -> provider success:
             atomically save user + assistant chat messages
             finalize Run(status=succeeded, link saved message IDs)
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
| `data_exposure` | Broad exposure category; v0.1 model runs use `model_provider` |

## Failure behavior

### Provider/configuration failure

If execution has started and the provider fails, finalize the Run as failed. Do not store the raw provider exception message.

### Run-start storage failure

Once chat is wired to Runs, MootOS should not silently make an unlogged provider call if the Run cannot be created. Return a safe service error before calling the model.

### Chat-commit failure after model success

This is the important edge case for the integration slice. The model may return successfully but the conversation turn may fail to commit. The Run must not claim the overall chat execution succeeded. Finalize it as failed with a sanitized storage error class or otherwise use a clearly documented terminal state. The implementation and tests must make that behavior explicit before merge.

## Production verification plan

After merge and Railway migration:

1. `/ready` reports ready at the new schema version.
2. Normal chat still works.
3. A successful model request creates one succeeded Run.
4. The Run references the saved conversation/user/assistant message IDs.
5. A controlled mocked provider failure creates one failed Run in tests without saving messages.
6. Run rows contain no raw prompt/response text.
7. Existing memory/profile/retrieval behavior remains unchanged.

## Not in v0.1

- run review UI
- automatic memory extraction
- reminders/tasks
- external tool execution
- approvals
- operation-spec hashing
- inbound observations/webhooks
- cost estimation when provider usage is unavailable

Those should build on this spine rather than being mixed into this PR.