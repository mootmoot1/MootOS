# MootOS API Reference

**Version:** 0.1  
**Base URL:** The Railway service domain in production or `http://127.0.0.1:8000` locally

This reference documents the current FastAPI routes. It does not describe planned endpoints.

## Authentication behavior

When `MOOTOS_PASSWORD` and `MOOTOS_SESSION_SECRET` are configured, most routes require the signed `mootos_session` cookie.

Browser requests for protected HTML routes are redirected to `/login`.

Protected JSON API requests without a valid session return:

```json
{
  "detail": "Authentication required"
}
```

with HTTP `401`.

During local development, authentication is disabled when both auth variables are absent.

## Common response pattern

Most application APIs return:

```json
{
  "success": true,
  "data": {}
}
```

FastAPI validation errors use FastAPI's normal HTTP `422` response format.

## Interface and health

### `GET /`

Redirects to `/chat` with HTTP `307`.

### `GET /chat`

Serves the main chat interface.

Authentication: protected when auth is enabled.

### `GET /login`

Serves the private login page.

When authentication is disabled or the request is already authenticated, redirects to `/chat`.

### `GET /manifest.webmanifest`

Returns the web-app manifest used for phone Home Screen installation.

### `GET /health`

Public Railway health check.

Response:

```json
{
  "status": "healthy"
}
```

This endpoint intentionally does not expose the database path, secrets, provider configuration, or private data.

## Authentication

### `POST /auth/login`

Creates a signed browser session after a correct password.

Request:

```json
{
  "password": "your private password"
}
```

Validation:

- Minimum length: 1
- Maximum length: 1,000

Successful response:

```json
{
  "success": true
}
```

The response sets the `mootos_session` cookie when auth is enabled.

Incorrect password:

- HTTP `401`

```json
{
  "detail": "Incorrect password"
}
```

### `POST /auth/logout`

Deletes the session cookie and redirects to `/login` with HTTP `303`.

## Projects

### Project object

```json
{
  "id": "uuid",
  "name": "Studio",
  "description": "Studio sessions, clients, engineering work, and business operations.",
  "created_at": "2026-07-31T00:00:00+00:00"
}
```

### `GET /projects`

Lists all projects alphabetically.

Successful response:

```json
{
  "success": true,
  "data": [
    {
      "id": "uuid",
      "name": "Cars",
      "description": "Vehicle maintenance, repairs, and automotive projects.",
      "created_at": "2026-07-31T00:00:00+00:00"
    }
  ]
}
```

### `POST /projects`

Creates a project.

Request:

```json
{
  "name": "New Project",
  "description": "Optional description"
}
```

Validation:

- `name`: required, 1–100 characters
- `description`: optional, maximum 500 characters
- Project names are unique case-insensitively

Successful response:

- HTTP `201`

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "name": "New Project",
    "description": "Optional description",
    "created_at": "2026-07-31T00:00:00+00:00"
  }
}
```

Duplicate project:

- HTTP `409`

```json
{
  "detail": "Project already exists"
}
```

Current limitation: There are no project rename, update, or delete endpoints.

## Memories

### Memory object

```json
{
  "id": "uuid",
  "content": "Studio block sessions cost $50 per hour.",
  "project": "Studio",
  "memory_type": "project",
  "created_at": "2026-07-31T00:00:00+00:00"
}
```

### `POST /memories`

Creates a memory.

Request:

```json
{
  "content": "Studio block sessions cost $50 per hour.",
  "project": "Studio",
  "memory_type": "project"
}
```

Fields:

- `content`: required, 1–10,000 characters
- `project`: optional; must match an existing project, case-insensitively
- `memory_type`: optional free-text category

Successful response:

- HTTP `201`

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "content": "Studio block sessions cost $50 per hour.",
    "project": "Studio",
    "memory_type": "project",
    "created_at": "2026-07-31T00:00:00+00:00"
  }
}
```

Unknown project:

- HTTP `422`

```json
{
  "detail": "Project does not exist"
}
```

### `GET /memories`

Lists memories newest first.

Optional query parameter:

```text
project=Studio
```

Examples:

```text
GET /memories
GET /memories?project=Studio
```

Successful response:

```json
{
  "success": true,
  "data": [
    {
      "id": "uuid",
      "content": "Studio block sessions cost $50 per hour.",
      "project": "Studio",
      "memory_type": "project",
      "created_at": "2026-07-31T00:00:00+00:00"
    }
  ]
}
```

Unknown project filter:

- HTTP `404`

```json
{
  "detail": "Project does not exist"
}
```

Current limitation: The endpoint does not yet support full-text search, pagination, tags, confidence, or semantic ranking.

### `GET /memories/{memory_id}`

Returns one memory.

Successful response:

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "content": "Saved memory",
    "project": "Personal",
    "memory_type": "preference",
    "created_at": "2026-07-31T00:00:00+00:00"
  }
}
```

Missing memory:

- HTTP `404`

```json
{
  "detail": "Memory not found"
}
```

### `DELETE /memories/{memory_id}`

Deletes one memory.

Successful response:

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "status": "deleted"
  }
}
```

Missing memory:

- HTTP `404`

```json
{
  "detail": "Memory not found"
}
```

Current limitation: There is no update endpoint. Correcting a memory currently requires deleting the old record and creating a new one through the API.

## Conversations

### Conversation summary object

```json
{
  "id": "uuid",
  "title": "Build session",
  "project": "MootOS",
  "created_at": "2026-07-31T00:00:00+00:00",
  "updated_at": "2026-07-31T00:05:00+00:00"
}
```

### Message object

```json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "role": "assistant",
  "content": "Response text",
  "provider": "openai",
  "model": "gpt-5-mini",
  "created_at": "2026-07-31T00:05:00+00:00"
}
```

User messages normally have `provider` and `model` set to `null`.

### `POST /conversations`

Creates an empty conversation.

Request:

```json
{
  "project": "MootOS",
  "title": "Build session"
}
```

Fields:

- `project`: optional; must match an existing project
- `title`: optional, 1–100 characters; defaults to `New conversation`

Successful response:

- HTTP `201`

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "title": "Build session",
    "project": "MootOS",
    "created_at": "2026-07-31T00:00:00+00:00",
    "updated_at": "2026-07-31T00:00:00+00:00"
  }
}
```

Unknown project:

- HTTP `422`

```json
{
  "detail": "Project does not exist"
}
```

### `GET /conversations`

Lists conversations newest first by `updated_at`.

Optional query parameter:

```text
project=MootOS
```

Successful response:

```json
{
  "success": true,
  "data": [
    {
      "id": "uuid",
      "title": "Build session",
      "project": "MootOS",
      "created_at": "2026-07-31T00:00:00+00:00",
      "updated_at": "2026-07-31T00:05:00+00:00"
    }
  ]
}
```

Unknown project filter:

- HTTP `404`

```json
{
  "detail": "Project does not exist"
}
```

### `GET /conversations/{conversation_id}`

Returns the conversation and complete message history.

Successful response:

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "title": "Build session",
    "project": "MootOS",
    "created_at": "2026-07-31T00:00:00+00:00",
    "updated_at": "2026-07-31T00:05:00+00:00",
    "messages": [
      {
        "id": "uuid",
        "conversation_id": "uuid",
        "role": "user",
        "content": "What are we building?",
        "provider": null,
        "model": null,
        "created_at": "2026-07-31T00:01:00+00:00"
      }
    ]
  }
}
```

Missing conversation:

- HTTP `404`

```json
{
  "detail": "Conversation not found"
}
```

## Chat

### `POST /chat`

Runs the current MootOS conversation loop.

Request for a new conversation:

```json
{
  "message": "What should we work on next?",
  "project": "MootOS"
}
```

Request for an existing conversation:

```json
{
  "message": "Continue that plan.",
  "conversation_id": "uuid"
}
```

Fields:

- `message`: required, 1–20,000 characters
- `conversation_id`: optional
- `project`: optional

New-conversation behavior:

- The model provider is checked before the new conversation is created.
- A conversation title is generated from the first 80 trimmed characters of the message.

Existing-conversation behavior:

- The conversation must exist.
- When `project` is supplied, it must match the existing conversation's project case-insensitively.

Successful response:

```json
{
  "success": true,
  "data": {
    "conversation_id": "uuid",
    "project": "MootOS",
    "user_message": {
      "id": "uuid",
      "conversation_id": "uuid",
      "role": "user",
      "content": "What should we work on next?",
      "provider": null,
      "model": null,
      "created_at": "2026-07-31T00:00:00+00:00"
    },
    "assistant_message": {
      "id": "uuid",
      "conversation_id": "uuid",
      "role": "assistant",
      "content": "Assistant response",
      "provider": "openai",
      "model": "gpt-5-mini",
      "created_at": "2026-07-31T00:00:02+00:00"
    },
    "provider": "openai",
    "model": "gpt-5-mini"
  }
}
```

Possible errors:

### Missing conversation

- HTTP `404`

```json
{
  "detail": "Conversation not found"
}
```

### Project mismatch

- HTTP `409`

```json
{
  "detail": "The requested project does not match this conversation"
}
```

### Provider not configured

- HTTP `503`

The detail explains the missing or unknown provider configuration.

### Provider request failed

- HTTP `502`

The detail contains the normalized model-provider error.

## FastAPI-generated documentation

When authentication is enabled, the standard FastAPI documentation routes are protected:

- `/docs`
- `/redoc`

These routes are useful during controlled development but should not be treated as the project documentation source of truth.

## API stability

The API is Version 0.1 and may evolve.

Before changing route names, request fields, response fields, authentication requirements, or status codes:

- Update tests
- Update this file
- Explain compatibility impact
- Use a focused pull request
- Add an ADR for a major public API redesign
