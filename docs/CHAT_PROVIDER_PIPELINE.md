# Chat Provider Pipeline

## Purpose

This guide describes how normal provider-backed chat avoids orphan messages,
duplicate retries, unbounded provider waits, and raw upstream error leakage.

Explicit long-term-memory commands use a separate atomic path and are unchanged.

## Normal request flow

For a normal `/chat` request, MootOS:

1. Validates that the selected provider is configured.
2. Acquires the in-process lock for an existing conversation.
3. Loads the conversation and up to 20 recent messages without writing.
4. For a new chat, prepares the conversation ID, title, project, and timestamps only
   in memory.
5. Appends the current user message to the in-memory provider input.
6. Calls the provider with a 45-second client timeout and zero automatic retries.
7. On success, opens one short `BEGIN IMMEDIATE` transaction.
8. Atomically stores the optional new conversation, user message, assistant message,
   and updated conversation timestamp.
9. Returns the committed records to the browser.

No SQLite write transaction is held while waiting for the model provider.

## Failure behavior

### Provider configuration failure

The request returns HTTP `503` with:

```json
{"detail":"MootOS model provider is not configured"}
```

No conversation or message is written.

### Provider request, timeout, or empty-output failure

The request returns HTTP `502` with:

```json
{
  "detail": "MootOS could not get a model response. Your message was not saved."
}
```

No conversation or message is written. Raw SDK exceptions, endpoints, request IDs,
and provider response text are not returned to the browser.

### Storage failure after provider success

The request returns HTTP `503` with:

```json
{
  "detail": "MootOS could not save the conversation turn. Please retry."
}
```

The transaction rolls back the complete pair. A new conversation is also rolled
back when the failed turn would have created it.

A provider response may have incurred cost before a storage failure. MootOS does not
auto-resend.

## Browser behavior

While waiting, the browser displays a temporary user bubble and typing indicator.
If the request fails, it:

- removes both temporary bubbles
- restores the exact submitted text to the composer
- keeps the previous conversation ID and project state
- does not write a new conversation ID to local storage
- shows the generic server error
- does not automatically retry

The user decides whether and when to send again.

## Concurrency boundary

The current production architecture is one process and one Railway replica. An
in-process lock serializes provider turns for the same existing conversation so two
requests cannot both generate from the same old history.

Do not increase the service to multiple processes or replicas and assume this lock
still coordinates turns. A future multi-replica design needs distributed ordering or
an explicit durable turn state machine.

## Verification checklist

Before merging:

- Exact-head CI passes all supported Python versions.
- Provider failure creates zero new rows.
- Storage failure rolls back both messages and any new conversation.
- Successful chat stores exactly one user and one assistant message.
- The current user message appears in provider input before persistence.
- Raw provider and storage text does not appear in HTTP responses.
- OpenAI client construction uses `timeout=45.0` and `max_retries=0`.
- Frontend failure handling removes temporary bubbles and restores the composer.
- Existing explicit-memory transaction tests remain green.

After deployment:

1. Confirm `/ready` and `/health` pass.
2. Confirm an ordinary successful message stores both sides after refresh.
3. Use a controlled non-production provider failure or test configuration when
   available; do not intentionally break the live production API key.
4. Confirm no unmatched user message appears after a failed request.
5. Retry manually and confirm only one successful pair is stored.
6. Confirm explicit `remember` behavior still stores memory and confirmation once.

## Incident response

If unmatched user messages appear:

1. Stop repeated manual retries.
2. Record the deployment commit and conversation ID without copying private message
   content into public logs or issues.
3. Check whether production is still one process and one replica.
4. Check application logs for a storage failure after provider success.
5. Roll back to the last verified deployment if the atomic path is not active.
6. Do not delete database rows manually until a backup and exact repair plan exist.

If users see raw provider error text, treat it as a privacy and security regression,
roll back, and inspect every exception-to-HTTP boundary before redeploying.
