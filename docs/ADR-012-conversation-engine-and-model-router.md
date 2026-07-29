# ADR-012: Conversation Engine and Replaceable Model Router

- **Status:** Accepted
- **Date:** 2026-07-29
- **Decision owners:** Moot and MootOS

## Context

MootOS already has persistent memories and a minimal project catalog, but it cannot yet hold a real AI conversation. Version 0.1 requires a continuous conversation loop that saves message history, uses relevant long-term memories, and does not permanently lock the application to one AI provider.

The first implementation also needs to work in GitHub Codespaces without committing API keys or requiring a powerful local computer.

## Decision

MootOS will add a small conversation engine with these boundaries:

1. Conversations and messages are stored locally in the existing SQLite database.
2. The FastAPI application exposes conversation endpoints and a single `POST /chat` endpoint.
3. The conversation engine sends recent message history and relevant project memories to a model router.
4. The model router returns one normalized response shape regardless of provider.
5. OpenAI's Responses API is the first provider implementation.
6. Provider selection, API key, and model name come from environment variables.
7. OpenAI response storage is disabled in the request because MootOS keeps its own local conversation record.
8. No secret is stored in the repository.

## Initial API

- `POST /conversations`
- `GET /conversations`
- `GET /conversations/{conversation_id}`
- `POST /chat`

## Why this approach

This is the smallest design that creates a real conversation loop while preserving the long-term requirement that AI engines remain replaceable. SQLite keeps development simple and local-first. The provider interface prevents OpenAI-specific code from spreading throughout the application.

## Consequences

### Positive

- MootOS can create and continue persistent conversations.
- Recent messages and project memories can affect responses.
- Future local providers can implement the same provider interface.
- Model/provider metadata is saved with assistant messages for transparency.
- The first cloud integration can be tested from Codespaces.

### Negative

- The first provider still requires internet access and OpenAI API billing.
- Memory selection is initially simple and limited to the newest relevant records.
- The v0.1 endpoint is non-streaming.
- Authentication, budget enforcement, summarization, embeddings, and local models remain future work.

## Rejected alternatives

### Put OpenAI calls directly inside the `/chat` endpoint

Rejected because it would couple the entire conversation engine to one provider and make future local-model support harder.

### Use OpenAI-hosted conversation state as the main source of truth

Rejected because MootOS is local-first and should own its conversation history. The cloud model is an engine, not the operating system.

### Build a full agent framework now

Rejected because tools, autonomous agents, and complex orchestration are outside the v0.1 conversation milestone and would add unnecessary complexity.

## Follow-up work

- Add a mobile-friendly chat interface.
- Add automatic memory save/correction commands.
- Add better memory retrieval and conversation summaries.
- Add budget and usage logging.
- Add a local model provider, likely through Ollama.
