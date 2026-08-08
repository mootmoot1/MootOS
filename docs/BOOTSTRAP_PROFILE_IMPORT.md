# Curated Bootstrap Profile Import

**Status:** Implemented on `main`  
**Version:** MootOS 0.1

This document describes the current reviewed bootstrap-profile workflow for importing a small, deliberate set of facts and preferences into existing long-term memory.

The feature originally shipped through `feature/moot-bootstrap-profile-v0.1`, but the branch is historical; the capability is now part of the composed production application.

## Goal

Give MootOS a useful starting profile without:

- committing private facts to the public repository
- dumping old conversations into permanent memory
- allowing a model to silently decide what becomes durable memory
- creating duplicates on repeated imports
- undoing prior corrections or archived memories

## Private manifest format

Version 1 JSON:

```json
{
  "version": 1,
  "entries": [
    {
      "content": "A reviewed global fact or preference.",
      "project": null
    },
    {
      "content": "A reviewed Studio fact.",
      "project": "Studio"
    }
  ]
}
```

Rules:

- `version` must be `1`
- `entries` must contain 1 to 50 items
- `content` must be nonblank after trimming and at most 10,000 characters
- `project` is either `null` or an existing MootOS project name
- the server assigns `memory_type = bootstrap_profile`
- actual private profile content must never be committed to GitHub

A safe placeholder example lives in `docs/bootstrap-profile.example.json` and contains no real private profile information.

## Current user flow

1. Open authenticated `GET /profile`.
2. Paste private JSON or select a local `.json` file.
3. Press **Preview profile**.
4. The browser parses JSON locally and sends the manifest to protected `POST /profile/preview`.
5. Review every entry and scope under Ready, Already active, or Blocked.
6. Resolve invalid or blocked entries.
7. Press **Import reviewed profile** and confirm the batch summary.
8. The browser sends the same reviewed manifest to protected `POST /profile/import`.
9. Confirm imported rows on the Memory page.
10. Use normal Correct, Forget, Restore, and Search controls afterward.

The browser renders submitted values with `textContent`, not `innerHTML`.

## Application composition

`backend.application:app` is the production composition entrypoint. It composes the base FastAPI application with profile and Task routes plus the current chat Task interception layer.

Railway launches:

```text
python -m uvicorn backend.application:app --host 0.0.0.0 --port $PORT
```

Railway readiness remains `/ready`.

## Preview behavior

Preview is read-only and returns three groups:

- `ready` — valid entries that would create new active memories
- `already_active` — equivalent active entries that would be skipped
- `blocked` — equivalent archived or superseded entries that prevent import

Equivalent means the same global/project scope and content normalized by trimming, whitespace collapsing, and case folding.

Duplicate entries inside the submitted manifest are validation errors.

Preview does not:

- write memories
- call OpenAI or another model provider
- spend model credits
- create a conversation
- store the submitted manifest as a repository file

## Import behavior

Import repeats server-side validation inside one `BEGIN IMMEDIATE` transaction.

- any invalid or blocked entry aborts the complete batch
- equivalent active entries are skipped
- every ready entry is inserted as an active memory
- all ready entries commit together or all roll back
- imported rows use `memory_type = bootstrap_profile`
- no additional schema migration is required

Repeating a successful import is a safe no-op for equivalent active entries.

## Privacy and security

- The page and APIs remain inside existing private-session protections.
- HTML requests without a valid session redirect to login.
- API requests without a valid session return `401`.
- Dynamic/private responses inherit the current no-store/browser security headers.
- Profile content is not sent to the model provider by the preview/import path.
- The repository contains no real private profile manifest.
- Browser file selection remains local until Moot explicitly previews the content.

## Error behavior

Expected failures include:

- malformed browser JSON → local readable error
- unsupported manifest version → `422`
- blank or oversized content → `422`
- too many or zero entries → `422`
- unknown project → `422`
- duplicate entries inside the manifest → `422`
- archived/superseded lifecycle conflict → `409`
- storage failure → fixed `503` response with transaction rollback

## Automated coverage

Tests cover:

- preview writes nothing
- import inserts all ready rows atomically
- forced insert failure rolls back the batch
- repeated import skips equivalent active rows
- archived and superseded equivalents block import
- manifest duplicates are rejected
- missing projects are rejected
- global and project scopes remain distinct
- memory type is forced to `bootstrap_profile`
- API error mapping
- authentication
- browser safe rendering
- composed Railway entrypoint

## Production status language

The feature is **implemented and merged on `main`**. Do not confuse that with claiming every possible real-profile import has been production-smoke-tested. Dated production verification records should be used only when they exist and should not be invented retroactively.

## Explicitly out of scope

- committing Moot's real profile to GitHub
- automatic conversation-history import
- model-generated profile extraction
- semantic duplicate detection
- automatic conflict resolution
- importing contacts, files, email, calendar, or external-account data
- a separate profile database table
- multi-user profile ownership
- background imports