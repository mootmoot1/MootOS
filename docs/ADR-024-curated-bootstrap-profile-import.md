# ADR-024: Curated bootstrap profile import

## Status

Proposed for MootOS Version 0.1.

## Date

August 3, 2026.

## Context

MootOS can already save, review, search, correct, archive, restore, and retrieve long-term memories. Conversation handling, provider-input boundaries, Railway storage, and the private HTTP boundary have also been hardened.

The next Version 0.1 product step is a curated Moot bootstrap profile: a small set of high-confidence facts and preferences that Moot explicitly reviews before they enter long-term memory.

Several risks must be controlled:

- the GitHub repository is public and must never contain Moot's real private profile
- a raw conversation-history dump would import stale, low-confidence, repetitive, or sensitive material
- automatic model extraction could silently decide what becomes permanent memory
- repeated imports could create duplicate memories
- an import must not recreate a memory that Moot previously corrected or archived
- partial batch writes would leave the profile in an unclear state

## Decision

MootOS will add a protected, user-controlled bootstrap-profile import workflow.

### Private input boundary

Real profile entries will never be committed to the repository. Moot will provide a private Version 1 JSON manifest through the authenticated application by pasting JSON or selecting a local file.

The repository may contain only a placeholder example with fictional or generic text.

### Manifest format

The first supported manifest shape is:

```json
{
  "version": 1,
  "entries": [
    {
      "content": "A reviewed fact or preference.",
      "project": null
    },
    {
      "content": "A reviewed project-specific fact.",
      "project": "Studio"
    }
  ]
}
```

`project: null` means global memory. A named project must already exist.

### Preview before import

The protected workflow will provide a read-only preview before any write. The preview will classify every entry as:

- ready to import
- already present as an equivalent active memory
- blocked because an equivalent archived or superseded memory exists

The preview must not call the model provider or change database state.

### Validation and limits

The server owns validation even when the browser performs convenience checks.

Version 0.1 limits:

- manifest version must equal `1`
- 1 to 50 entries per import
- each content value is trimmed, nonblank, and at most 10,000 characters
- each project is either null or an existing project name
- duplicate entries inside one manifest are rejected
- imported rows use the fixed memory type `bootstrap_profile`

The client cannot choose an arbitrary memory type.

### Duplicate and lifecycle behavior

Equivalent content is compared using trimmed, collapsed-whitespace, case-folded text inside the same global or project scope.

- an equivalent active memory is skipped, making a repeated successful import a safe no-op
- an equivalent archived or superseded memory blocks the batch so import cannot silently undo a prior forget or correction
- broader semantic duplicate detection remains out of scope

### Atomic import

Import will revalidate the complete manifest inside one `BEGIN IMMEDIATE` transaction.

If any entry is invalid or lifecycle-blocked, no new row is written. If validation succeeds, all ready entries are inserted as active memories and committed together. A database failure rolls back the full batch.

### Existing memory controls remain authoritative

Imported entries become ordinary active memory rows. They appear on the existing Memory page and can be searched, corrected, archived, restored, and retrieved using the same lifecycle rules as other memories.

No new schema migration is required.

### Provider and logging boundary

Preview and import are deterministic application operations:

- no OpenAI or other model-provider call
- no extra model credits
- no automatic extraction from conversations
- no profile content written to application logs
- no profile manifest stored as a repository file

## Consequences

### Positive

- Moot reviews the exact permanent profile before import
- private facts stay out of public source control
- the import is understandable, repeatable, and atomic
- prior correction and archive decisions are respected
- imported facts immediately use existing review and lifecycle controls
- no schema migration or new storage system is required

### Negative

- Moot must prepare and review a small JSON manifest
- literal normalization cannot detect paraphrased duplicates
- the first version does not maintain a separate profile document or batch history
- a blocked archived or superseded match requires Moot to resolve the existing memory through normal controls

## Alternatives considered

### Commit Moot's profile as a source file

Rejected because the repository is public and profile facts may be private or sensitive.

### Import all prior conversations automatically

Rejected because conversation history contains noise, outdated statements, transient notes, and information that was never approved for permanent memory.

### Ask the model to extract the profile automatically

Rejected for Version 0.1 because model judgment would make permanent writes less deterministic and harder to audit.

### Add a new profile table

Deferred. Existing memory rows already provide scope, retrieval, review, correction, archival, restoration, and persistence. A separate profile model should be added only if real usage proves that memories are insufficient.

### Allow partial imports

Rejected because partial success makes it harder to know which profile state is authoritative. Atomic all-or-nothing writes are easier to verify and recover.

## Reversal

The feature can be removed without a schema rollback. Imported rows remain ordinary memories and can be archived or corrected through existing controls. The profile import routes and interface can be removed independently of stored memory data.
