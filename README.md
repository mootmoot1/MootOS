# MootOS

MootOS is Moot’s private, mobile-friendly personal AI foundation.

Version 0.1 provides persistent conversations, deliberate long-term-memory saves, reviewable memory correction, a recoverable forget-and-restore branch, project-focused context, private Railway access, hardened SQLite storage, and a replaceable model-provider boundary.

## Current status

**Version:** `0.1.0`  
**Production branch:** `main`  
**Current feature branch:** `feature/memory-forget-v0.1`  
**Deployment:** Railway, one service and one replica  
**Production database:** `/data/mootos.db`  
**Schema:** `2 — memory_lifecycle`  
**Model provider:** OpenAI through a replaceable interface

See [`docs/CURRENT_CHECKPOINT.md`](docs/CURRENT_CHECKPOINT.md) for the exact verified state.

## What works in production

- Private password login and signed browser sessions
- Mobile chat interface
- Persistent projects, conversations, and messages
- Explicit `remember` and `save` commands
- Atomic database-backed memory confirmation
- Cross-chat recall that survives Railway rebuilds
- Protected Memory page with All, Global, and project filters
- UI-selected memory correction with preserved history
- Active-only model context after correction
- Manual off-volume backup and isolated restore verification
- Centralized SQLite configuration, WAL mode, foreign keys, timeouts, and numbered migrations

## Current branch: recoverable forgetting

The Memory page adds:

- Active and Archived views
- **Forget** on active memories
- **Restore** on archived memories
- Explicit confirmation before either action

“Forget” means archive, not permanent delete. An archived memory stops appearing in normal lists and model context but remains available for restoration. Correction history stays intact.

The branch does **not** add natural-language forget, permanent-delete UI, bulk archive, retention rules, or search.

## Explicit memory saves

Use direct wording:

```text
Remember that my favorite tea is jasmine.
Save this to memory: I prefer plain explanations.
Save to long-term memory: Studio block sessions cost $50 per hour.
```

MootOS parses these commands deterministically, writes the memory to SQLite, and confirms only after the complete transaction commits. The external model is not called for this path.

## Memory lifecycle

Memory rows use these states:

- `active` — included in normal listing and recall
- `superseded` — preserved older version replaced by correction
- `archived` — recoverably forgotten and excluded from normal recall

Correction creates a new active row and preserves the old row as superseded. Forget changes only the latest active row to archived. Restore returns that same row to active.

## Project behavior

- Global memories are available across projects.
- Main/no-project chat can load all active saved memory.
- A project chat currently loads active global memory plus active memory assigned to that project.
- Projects are focus lenses, not permanent secrecy walls.
- Cross-project relevance ranking belongs to the later retrieval branch.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
python -m uvicorn backend.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/chat
http://127.0.0.1:8000/memory
```

Run tests:

```bash
python -m pytest
```

Tests use fake model providers and do not require paid model calls.

## Environment variables

| Variable | Purpose |
|---|---|
| `AI_PROVIDER` | Current supported value: `openai` |
| `OPENAI_API_KEY` | Required only for real normal-chat responses |
| `OPENAI_MODEL` | Model name; defaults to `gpt-5-mini` |
| `MOOTOS_PASSWORD` | Private deployment password |
| `MOOTOS_SESSION_SECRET` | Signed-session secret |
| `MOOTOS_ALLOW_PUBLIC` | Explicit high-risk Railway public override |
| `MOOTOS_SECURE_COOKIES` | Secure-cookie override |
| `MOOTOS_DATABASE_PATH` | Exact SQLite path override |
| `RAILWAY_VOLUME_MOUNT_PATH` | Railway volume path |
| `PORT` | Railway server port |

Never commit `.env`, credentials, production databases, or memory contents.

## Repository layout

```text
backend/        FastAPI, auth, SQLite, migrations, memory, chat, providers
frontend/       Mobile chat and memory interfaces
tests/          Automated behavior and safety coverage
docs/           Current truth, ADRs, operations, and verification records
railway.toml    Railway start and health configuration
```

## Development workflow

1. Start from current `main`.
2. Create one focused branch.
3. Add behavior and regression tests.
4. Update documentation in the same PR.
5. Open a draft PR.
6. Wait for CI.
7. Complete internal and external read-only review.
8. Explain the result in plain language.
9. Merge only after Moot explicitly approves the exact PR.
10. Verify Railway and existing data after deployment.

## Current limitations

- Single user
- Text chat only
- One external provider implemented
- One SQLite replica
- No automatic encrypted backup or retention
- No natural-language correction or forget
- No keyword or semantic retrieval
- No runtime tools, local model, or multi-agent system

## Core rule

MootOS should become more capable without becoming less understandable, less secure, or less controllable.
