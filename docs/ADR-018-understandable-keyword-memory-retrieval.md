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

Memory search terms may themselves be private. Putting them in a URL query string could expose them in browser history, proxy logs, or ordinary access logs, so browser search should submit them in a protected request body.

## Decision

MootOS adds a pure-Python keyword retrieval layer in `backend/memory_retrieval.py`.

It introduces no schema migration and does not change stored memory rows.

### Query normalization

The retrieval layer:

1. Case-folds the current request.
2. Extracts letters and numbers.
3. Removes a small documented set of common English stop words.
4. Applies intentionally limited plural normalization, including `cars` → `car`, `codes` → `code`, and `memories` → `memory`.
5. Keeps at most 40 unique query keywords after duplicate removal.

Stored memory content is scanned completely; the 40-keyword limit applies only to the user's query.

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

For a no-project conversation, scope does not receive a ranking bonus. Match strength and recency decide among active memories from all projects. Remaining context slots may be filled from all active memories.

This makes projects focus lenses rather than permanent walls while preserving predictable fallback behavior.

### Lifecycle boundary

Only `active` rows are eligible for model context.

- `superseded` rows remain available through correction history.
- `archived` rows remain available through the Archived browser view and restoration workflow.
- Neither status can enter keyword-ranked model context.

### Context limit

At most 20 active memories are supplied to a model request. Keyword matches come before safe fallback memories.

### Memory-page search

The protected browser submits read-only searches to:

```text
POST /memories/search
```

Request body:

```json
{
  "query": "keyword phrase",
  "status": "active",
  "project": "Cars"
}
```

Rules:

- `query` is required, trimmed, and limited to 500 characters.
- `status` must be `active` or `archived`.
- `project` is optional and must be one exact existing project when supplied.
- Superseded rows are never returned.
- The endpoint performs no database mutation.
- Search terms stay out of the request URL and ordinary URL logs.

`GET /memories` remains the unsearched active-or-archived listing endpoint.

The protected Memory page adds an explicit Search form and Clear control. Search text, stored content, and project values continue to render through `textContent`.

The browser adds no memory `DELETE`, `PATCH`, or `PUT` request.

## Why this decision

The algorithm is small enough to inspect in one file, deterministic enough to test exactly, and useful enough to improve older-memory recall and cross-project relevance.

It also gives Moot a visible search tool using the same basic keyword rules as conversational retrieval while keeping private search text out of URL-based logs.

No database migration means deployment and rollback risk are lower than a first FTS or vector-search implementation.

## Consequences

### Positive

- Relevant older memories can outrank newer unrelated memories.
- Project chats can use clearly relevant cross-project memory.
- Archived and superseded rows remain excluded from normal recall.
- The ranking order is deterministic and testable.
- Search works across active or archived normal listings.
- Private search terms are sent in a protected request body rather than the URL.
- No provider call or additional model credit is required for retrieval.
- No new database or background service is introduced.

### Tradeoffs

- Synonyms do not match unless another keyword or project name overlaps.
- Typographical errors are not corrected.
- The application reads the eligible memory listing and ranks it in Python, which is appropriate for the current personal dataset but not an unbounded multi-user scale design.
- Stop-word and plural rules are English-oriented and deliberately limited.
- Keyword overlap can still produce imperfect relevance.
- The search route uses POST for a read-only operation specifically to protect search terms from URL logging; it does not mutate state.

## Alternatives considered

### Keep newest-first retrieval only

Rejected because an older relevant fact can be pushed out by newer unrelated memories.

### Strictly isolate projects

Rejected because Moot defined projects as focus lenses, not secrecy walls. Explicitly saved long-term memory should remain available when relevant.

### Use `GET /memories?q=...` for search

Rejected because private memory search terms could appear in browser history and infrastructure access logs.

### Add SQLite FTS5 immediately

Deferred. FTS5 could improve scale and ranking later, but it would add schema and deployment considerations before the simple behavior is proven.

### Add embeddings or a vector database

Rejected for this version. The added provider cost, indexing lifecycle, privacy questions, and debugging complexity are not justified yet.

### Ask the model to select memories

Rejected because it would spend model credits, make retrieval less deterministic, and complicate testing.

## Verification requirements

Automated coverage must prove:

- Case, punctuation, repeated terms, and simple plurals normalize predictably.
- Repeated query terms do not hide later unique keywords.
- Complete stored memory content is searched, including terms after the first 40 words.
- A relevant older memory outranks a newer unrelated memory.
- No-project ranking uses match strength rather than preferring global scope.
- Project matches rank before global matches, which rank before relevant other-project matches.
- Unrelated other-project memories are not used as project fallback.
- Stop-word-only requests preserve the safe existing fallback behavior.
- Archived and superseded rows never enter context.
- Restoration makes the active row eligible again.
- Active and archived browser searches remain separated.
- Exact project search is respected.
- Blank, oversized, and unsupported-status searches are rejected.
- The search endpoint requires authentication.
- Search terms are sent in the request body, not as a URL query parameter.
- Model instructions receive the current user request as the retrieval query.
- Search rendering remains XSS-safe and introduces no permanent-delete browser request.

GitHub Actions, external read-only review, explicit merge approval, Railway deployment, and production recall verification remain required.
