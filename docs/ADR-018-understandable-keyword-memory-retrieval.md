# ADR-018 — Understandable Keyword Memory Retrieval

**Status:** Proposed  
**Date:** August 1, 2026

## Context

MootOS can deliberately save memories, review them, preserve corrections, and recoverably archive or restore them. Normal chat previously supplied the newest active memories according to a simple scope rule:

- A no-project conversation could load all active memories.
- A project conversation could load active global memory plus active memory from that exact project.

That rule is predictable, but it can miss an older relevant memory and treats projects more like retrieval walls than focus lenses. Moot's intended behavior is broader:

- Main or no-project chat should be able to use any relevant active memory.
- A selected project should focus and prioritize that project.
- Relevant memory from another project may still be used when the current request clearly matches it.
- Archived and superseded rows must never return to normal recall.

The first retrieval improvement must remain inspectable and easy to debug. Embeddings, vector databases, FTS migrations, background indexing, and model-based relevance scoring would add complexity before simple keyword retrieval has been tested in real use.

## Decision

MootOS adds a pure-Python keyword retrieval layer in `backend/memory_retrieval.py`.

It introduces no schema migration and does not change stored memory rows.

### Query normalization

The retrieval layer:

1. Case-folds the current request.
2. Extracts letters and numbers.
3. Removes a small documented set of common English stop words.
4. Applies intentionally limited plural normalization, including `cars` → `car`, `codes` → `code`, and `memories` → `memory`.
5. Keeps at most 40 unique query keywords.

It does not claim synonym, intent, entity, or semantic understanding.

### Match fields

Keywords can match:

- Memory content
- Project name
- Memory type or source

Content matches receive the strongest score. A contiguous multi-keyword content phrase receives an additional bonus. Project-name matches allow requests such as `What car do I have?` to find a memory stored under the `Cars` project even when the saved content says `Benz` rather than `car`.

### Project focus behavior

For a project conversation, keyword matches are ordered by focus:

1. Matching-project memories
2. Global memories
3. Relevant memories from other projects

After keyword matches, remaining context slots may be filled only with recent matching-project and global active memories. Unrelated other-project memories are not used as fallback.

For a no-project conversation, keyword matches may come from every project. Remaining context slots may be filled from all active memories.

This makes projects focus lenses rather than permanent walls while preserving predictable fallback behavior.

### Lifecycle boundary

Only `active` rows are eligible for model context.

- `superseded` rows remain available through correction history.
- `archived` rows remain available through the Archived browser view and restoration workflow.
- Neither status can enter keyword-ranked model context.

### Context limit

At most 20 active memories are supplied to a model request. Keyword matches come before safe fallback memories.

### Memory-page search

`GET /memories` accepts an optional `q` query parameter with a maximum length of 500 characters.

Search operates only inside the requested normal listing:

- `status=active` or `status=archived`
- Optional exact project filter
- No superseded rows

The protected Memory page adds an explicit Search form and Clear control. Search text, stored content, and project values continue to render through `textContent`.

The browser adds no memory `DELETE`, `PATCH`, or `PUT` request.

## Why this decision

The algorithm is small enough to inspect in one file, deterministic enough to test exactly, and useful enough to improve older-memory recall and cross-project relevance.

It also gives Moot a visible search tool using the same basic keyword rules as conversational retrieval.

No database migration means deployment and rollback risk are lower than a first FTS or vector-search implementation.

## Consequences

### Positive

- Relevant older memories can outrank newer unrelated memories.
- Project chats can use clearly relevant cross-project memory.
- Archived and superseded rows remain excluded.
- The ranking order is deterministic and testable.
- Search works across active or archived normal listings.
- No provider call or additional model credit is required for retrieval.
- No new database or background service is introduced.

### Tradeoffs

- Synonyms do not match unless another keyword or project name overlaps.
- Typographical errors are not corrected.
- The application reads the eligible memory listing and ranks it in Python, which is appropriate for the current personal dataset but not an unbounded multi-user scale design.
- Stop-word and plural rules are English-oriented and deliberately limited.
- Keyword overlap can still produce imperfect relevance.

## Alternatives considered

### Keep newest-first retrieval only

Rejected because an older relevant fact can be pushed out by newer unrelated memories.

### Strictly isolate projects

Rejected because Moot defined projects as focus lenses, not secrecy walls. Explicitly saved long-term memory should remain available when relevant.

### Add SQLite FTS5 immediately

Deferred. FTS5 could improve scale and ranking later, but it would add schema and deployment considerations before the simple behavior is proven.

### Add embeddings or a vector database

Rejected for this version. The added provider cost, indexing lifecycle, privacy questions, and debugging complexity are not justified yet.

### Ask the model to select memories

Rejected because it would spend model credits, make retrieval less deterministic, and complicate testing.

## Verification requirements

Automated coverage must prove:

- Case, punctuation, repeated terms, and simple plurals normalize predictably.
- A relevant older memory outranks a newer unrelated memory.
- Project matches rank before global matches, which rank before relevant other-project matches.
- Unrelated other-project memories are not used as project fallback.
- Stop-word-only requests preserve the safe existing fallback behavior.
- Archived and superseded rows never enter context.
- Restoration makes the active row eligible again.
- Active and archived browser searches remain separated.
- Oversized search queries are rejected.
- Model instructions receive the current user request as the retrieval query.
- Search rendering remains XSS-safe and introduces no permanent-delete browser request.

GitHub Actions, external read-only review, explicit merge approval, Railway deployment, and production recall verification remain required.
