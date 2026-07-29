# ADR-013: Server-Rendered Mobile Chat Interface

- **Status:** Proposed
- **Date:** 2026-07-29
- **Decision owners:** Moot and MootOS

## Context

The conversation engine is working, but its only usable interface is Swagger's JSON testing page. That page is useful for developers and automated testing, but it is difficult to read and impractical for everyday conversation from a phone.

Version 0.1 needs the smallest interface that makes MootOS feel like a usable product without introducing a separate frontend build system before the foundation is stable.

## Decision

MootOS will add a phone-first chat interface with these boundaries:

1. FastAPI serves one plain HTML page at `GET /chat`.
2. Local CSS and JavaScript files are served from `/static`.
3. The interface calls the existing same-origin API endpoints.
4. `POST /chat` remains the conversation API; the same path can serve the page through `GET`.
5. The browser handles the active conversation ID automatically.
6. Conversation history and projects come from the existing SQLite-backed endpoints.
7. Version 0.1 will not use React, Node.js, a package bundler, external fonts, or external UI libraries.
8. The interface does not receive or display the OpenAI API key.
9. Authentication remains required before this interface is exposed outside a private development environment.

## Initial interface

- Message bubbles
- Text composer
- New Chat button
- Project selector
- Conversation history
- Loading indicator
- Clear error messages
- Responsive phone and desktop layouts
- Same-origin server health indicator

## Why this approach

A plain HTML, CSS, and JavaScript interface is enough to validate the complete MootOS conversation experience. It runs inside the existing FastAPI process, avoids another dependency stack, and can be opened directly from a Codespaces forwarded port.

The existing API remains the stable boundary. A more advanced frontend can replace this interface later without rebuilding the conversation, memory, or project systems.

## Consequences

### Positive

- Moot can talk to MootOS without reading or editing JSON.
- The interface works from a phone browser.
- Conversation IDs are managed automatically.
- No frontend compilation step is required.
- No new service or deployment target is required.
- The interface remains provider-independent because it only calls MootOS APIs.

### Negative

- The first interface is intentionally simple.
- Responses are still non-streaming.
- There is no login screen yet.
- The active Codespace and FastAPI server must remain running.
- A richer frontend may eventually replace these files.

## Rejected alternatives

### Continue using Swagger as the main interface

Rejected because Swagger is an API development tool, not a practical chat experience.

### Build React or another full frontend framework now

Rejected because it would add Node.js, package management, build tooling, and more failure points before v0.1 needs them.

### Call OpenAI directly from browser JavaScript

Rejected because it would expose the API key and bypass MootOS memory, projects, logs, and the replaceable model router.

## Follow-up work

- Add authentication before public deployment.
- Add streaming responses.
- Add memory review and correction controls.
- Add basic settings and cloud-budget visibility.
- Consider a richer frontend only after the v0.1 workflow is stable.
