# Curated bootstrap profile import

This document defines the planned Version 0.1 workflow for importing a small, reviewed set of Moot facts and preferences into existing long-term memory.

The implementation belongs on:

```text
feature/moot-bootstrap-profile-v0.1
```

Until the branch is merged and production-verified, this document describes the approved target behavior rather than current production capability.

## Goal

Give MootOS a useful starting profile without:

- committing private facts to the public repository
- dumping old conversations into permanent memory
- allowing a model to decide silently what should be remembered
- creating duplicates on repeated imports
- undoing prior corrections or archived memories

## Private manifest format

The first format is Version 1 JSON:

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
- actual profile content must never be committed to GitHub

A safe placeholder example is stored in `docs/bootstrap-profile.example.json`. It contains no real Moot profile information.

## Planned user flow

1. Open the protected profile-import page.
2. Paste private JSON or select a local JSON file.
3. Press **Preview**.
4. Review every exact entry and its scope.
5. Resolve any invalid, duplicate, archived, or superseded conflicts.
6. Press **Import profile** only after the preview is correct.
7. Confirm the imported rows appear on the existing Memory page.
8. Use normal Correct, Forget, Restore, and Search controls afterward.

The browser must render profile content through `textContent`, not HTML.

## Preview behavior

Preview is read-only and returns three groups:

- `ready` — valid entries that would create new active memories
- `already_active` — equivalent active entries that would be skipped
- `blocked` — equivalent archived or superseded entries that prevent import

Equivalent means:

- same global or project scope
- content compared after trimming, collapsing whitespace, and case folding

Duplicate entries inside the submitted manifest are validation errors.

Preview does not:

- write memories
- call OpenAI
- spend model credits
- create a conversation
- store the submitted manifest as a file

## Import behavior

Import repeats server-side validation inside one `BEGIN IMMEDIATE` transaction.

- any invalid or blocked entry aborts the complete batch
- equivalent active entries are skipped
- every ready entry is inserted as an active memory
- all ready entries commit together or all roll back
- imported rows use `memory_type = bootstrap_profile`
- no schema migration is required

A repeated successful import becomes a safe no-op because the entries are already active.

## Privacy and security

- The page and APIs remain inside the existing private-session boundary.
- Responses receive the existing `Cache-Control: no-store` and browser-security headers.
- Profile content must not be printed to logs or error messages.
- The repository contains no real profile manifest.
- The browser sends profile JSON only to the authenticated MootOS backend.
- The backend does not send the manifest to the model provider.

## Error behavior

Expected failures should be specific without echoing private content:

- unsupported manifest version → `422`
- blank or oversized content → `422`
- too many or zero entries → `422`
- unknown project → `422`
- duplicate entries inside the manifest → `422`
- archived or superseded lifecycle conflict → `409`
- storage failure → fixed `503` response and complete rollback

## Automated verification target

Tests should prove:

- preview writes nothing
- import inserts all ready rows atomically
- a forced insert failure rolls back the complete batch
- repeated import skips equivalent active rows without duplicates
- archived and superseded matches block import
- manifest duplicates are rejected
- missing projects are rejected
- global and project scopes remain distinct
- memory type is forced to `bootstrap_profile`
- profile operations do not call the model provider
- profile routes require authentication
- private response headers remain active
- the browser uses safe text rendering
- no real profile facts appear in the repository

## Controlled production verification target

After merge and Railway deployment:

1. `/ready` and `/health` remain healthy.
2. Private login still works.
3. The profile page loads only after authentication.
4. A tiny disposable manifest previews correctly.
5. Import creates the expected active memories.
6. Repeating the same import creates no duplicates.
7. Imported rows appear on the Memory page with source `bootstrap_profile`.
8. One imported row can be corrected.
9. One imported row can be archived and restored.
10. A brand-new chat can recall a relevant imported active memory.
11. The result survives a Railway rebuild.

Production verification should use disposable generic entries before importing Moot's real curated profile.

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
