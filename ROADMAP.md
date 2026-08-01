# MootOS Roadmap

**Last reviewed:** August 1, 2026

## Direction

MootOS is becoming a dependable personal AI foundation: persistent conversations, deliberate long-term memory, reviewable changes, replaceable model providers, and controlled expansion into research and action systems.

Reliability and user control come before autonomy.

## Production-verified foundation

- Private Railway deployment with one service and replica
- Persistent SQLite on `/data`
- Signed-session authentication
- Persistent projects, conversations, messages, and memories
- Explicit chat memory saves
- Cross-chat recall through rebuilds
- Protected memory review and filtering
- Manual off-volume backup and isolated restore drill
- Migration 2 memory lifecycle
- UI-selected correction with preserved history
- Corrected active value recalled after another rebuild

## Current branch sequence

1. `feature/memory-review-ui-v0.1` — complete
2. `feature/memory-correction-v0.1` — complete and production-verified
3. `feature/memory-forget-v0.1` — current
4. `feature/memory-keyword-retrieval-v0.1`
5. `feature/conversation-refinement-v0.1`
6. `feature/moot-bootstrap-profile-v0.1`

## Current branch — recoverable forget

Goals:

- Archive one exact active memory after confirmation
- Exclude archived rows from normal recall
- Show archived memories separately
- Restore one exact archived memory
- Preserve correction history
- Protect archived rows from permanent deletion
- Reuse schema 2; no unnecessary migration

Out of scope:

- Natural-language forget
- Permanent-delete UI
- Bulk archive
- Automatic retention
- Keyword or semantic retrieval

## Retrieval next

After lifecycle controls are stable, add basic keyword retrieval before embeddings.

Desired ranking direction:

1. Matching-project memories
2. Global memories
3. Relevant other-project memories when useful

Projects are focus lenses rather than memory walls.

## Conversation refinement

Improve instruction quality, handling of uncertainty, follow-up behavior, memory use, and provider-failure behavior without turning MootOS into an uncontrolled autonomous agent.

## Bootstrap profile

Only after review, correction, forgetting, and retrieval are reliable, add a curated profile through the same controlled memory system. Do not dump raw prior conversations into long-term memory.

## Later directions

- Automatic encrypted backups, retention, and recurring restore tests
- Duplicate/conflict handling
- Voice input and long-form idea organization
- Research and scoring workflows
- Controlled coding operator using small reviewed PRs
- Runtime tools with permissions and activity history
- Local models and stronger provider independence
- Specialist advisory agents after the single-agent foundation is reliable
