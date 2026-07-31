# MootOS API Reference

**Version:** 0.1  
**Base URL:** Railway service domain in production or `http://127.0.0.1:8000` locally

This reference documents current FastAPI behavior. Planned endpoints are not included.

## Authentication behavior

When `MOOTOS_PASSWORD` and `MOOTOS_SESSION_SECRET` are configured, application routes require the signed `mootos_session` cookie.

Unauthenticated protected JSON requests return HTTP `401`:

```json
{
  "detail": "Authentication required"
}
```

Browser requests for protected HTML redirect to `/login`.

Railway refuses to start without private auth unless `MOOTOS_ALLOW_PUBLIC=true` is deliberately configured.

## Common response pattern

Most application APIs return:

```json
{
  "success": true,
  "data": {}
}
```

FastAPI request validation errors normally return HTTP `422`.

## Interface and health

### `GET /`

Redirects to `/chat` with HTTP `307`.

### `GET /chat`

Serves the main chat interface.

### `GET /login`

Serves the private login page. Redirects to `/chat` when auth is disabled or the request is already authenticated.

### `GET /manifest.webmanifest`

Returns the phone Home Screen web-app manifest.

### `GET /health`

Public Railway health check.

```json
{
  "status": "healthy"
}
```

The health response intentionally excludes secrets, database paths, provider settings, and private content.

## Authentication

### `POST /auth/login`

Request:

```json
{
  "password": "your private password"
}
```

Validation:

- Minimum: 1 character
- Maximum: 1,000 characters

Success:

```json
{
  "success": true
}
```

Incorrect password returns HTTP `401`:

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
  "description": "Studio sessions and business operations.",
  "created_at": "2026-07-31T00:00:00+00:00"
}
```

### `GET /projects`

Lists projects alphabetically.

### `POST /projects`

Request:

```json
{
  "name": "New Project",
  "description": "Optional description"
}
```

Validation:

- `name`: 1–100 characters
- `description`: optional, maximum 500 characters
- Names are unique case-insensitively

Success: HTTP `201`.

Duplicate project: HTTP `409`.

```json
{
  "detail": "Project already exists"
}
```

There are no project update, rename, or delete endpoints.

## Memories

### Memory object

```json
{
  "id": "uuid",
  "content": "My favorite tea is jasmine.",
  "project": "Personal",
  "memory_type": "explicit_chat",
  "created_at": "2026-07-31T00:00:00+00:00"
}
```

`project: null` means the memory is global.

### `POST /memories`

Creates a memory directly through the API.

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
- `project`: optional existing project
- `memory_type`: optional free-text category

Success: HTTP `201`.

Unknown project: HTTP `422`.

```json
{
  "detail": "Project does not exist"
}
```

### `GET /memories`

Lists all memories newest first.

Optional filter:

```text
GET /memories?project=Studio
```

The project filter returns only memories assigned to that project. It does not include global memories.

Unknown project filter returns HTTP `404`.

### `GET /memories/{memory_id}`

Returns one memory. Missing records return HTTP `404`.

### `DELETE /memories/{memory_id}`

Deletes one memory.

Success:

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "status": "deleted"
  }
}
```

There is no memory update endpoint yet.

## Conversations

### Conversation object

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

Verified internal memory confirmations use:

```text
provider = mootos
model = memory-command-v1
```

### `POST /conversations`

Creates an empty conversation.

```json
{
  "project": "MootOS",
  "title": "Build session"
}
```

- `project`: optional existing project
- `title`: optional, 1–100 characters; defaults to `New conversation`

Success: HTTP `201`.

### `GET /conversations`

Lists conversations newest first by `updated_at`.

Optional filter:

```text
GET /conversations?project=MootOS
```

### `GET /conversations/{conversation_id}`

Returns one conversation with its complete message history.

Missing conversation returns HTTP `404`:

```json
{
  "detail": "Conversation not found"
}
```

## Chat

### `POST /chat`

Handles either normal model conversation or an explicit long-term-memory save command.

New conversation request:

```json
{
  "message": "What should we work on next?",
  "project": "MootOS"
}
```

Existing conversation request:

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

When both `conversation_id` and `project` are supplied, the project must match the existing conversation.

### Normal conversation behavior

When the message is not an explicit save command:

1. The provider configuration is checked.
2. The conversation is validated or created.
3. The user message is stored.
4. Up to 20 recent messages are loaded.
5. Relevant global and matching-project memories are added to instructions.
6. The configured model provider generates a response.
7. The assistant response is stored and returned.

Missing provider configuration returns HTTP `503` before a new normal conversation is created.

Provider request failure returns HTTP `502`.

### Explicit memory-save behavior

Recognized command families include:

```text
Remember that <memory>
Remember <memory>
Save this <memory>
Save this to memory: <memory>
Save to long-term memory: <memory>
```

The parser is case-insensitive and requires the command at the beginning of the message. Ordinary questions such as `Do you remember that session?` are not treated as writes.

For a recognized save command:

1. The memory content is extracted.
2. Content over 10,000 characters is rejected with HTTP `422`.
3. The conversation is validated or created.
4. The original user command is stored as a message.
5. The extracted content is inserted into the `memories` table.
6. The conversation project is used when present; otherwise the memory is global.
7. `memory_type` is set to `explicit_chat`.
8. A confirmation is stored and returned only after the database write succeeds.

This path does not call OpenAI.

Example request:

```json
{
  "message": "Remember that my favorite tea is jasmine.",
  "project": "Personal"
}
```

Example response fields:

```json
{
  "success": true,
  "data": {
    "conversation_id": "uuid",
    "project": "Personal",
    "user_message": {
      "role": "user",
      "content": "Remember that my favorite tea is jasmine."
    },
    "assistant_message": {
      "role": "assistant",
      "content": "Saved to Personal long-term memory: my favorite tea is jasmine.",
      "provider": "mootos",
      "model": "memory-command-v1"
    },
    "provider": "mootos",
    "model": "memory-command-v1"
  }
}
```

### Cross-chat recall rules

- Global memories are supplied to all project conversations.
- Project memories are supplied only to their matching project.
- A conversation without a project can load all memories.
- At most 20 newest relevant memories are supplied.

### Standard successful chat response

```json
{
  "success": true,
  "data": {
    "conversation_id": "uuid",
    "project": "MootOS",
    "user_message": {},
    "assistant_message": {},
    "provider": "openai",
    "model": "gpt-5-mini"
  }
}
```

### Chat errors

Missing conversation: HTTP `404`.

Project mismatch: HTTP `409`.

```json
{
  "detail": "The requested project does not match this conversation"
}
```

Oversized extracted memory: HTTP `422`.

```json
{
  "detail": "Memory content must be 10,000 characters or fewer"
}
```

## Current memory-command limitations

Not implemented:

- `Forget that ...`
- `Update that ...`
- Automatic memory extraction from normal conversation
- Duplicate detection
- Conflict resolution
- Keyword or semantic search
- Memory review UI

## FastAPI-generated documentation

When authentication is enabled, `/docs` and `/redoc` are protected.

Repository documentation remains the source of truth.

## API stability

The API is Version 0.1 and may evolve.

Before changing routes, request fields, response fields, auth requirements, or status codes:

- Update tests
- Update this reference
- Explain compatibility impact
- Use a focused pull request
- Add an ADR for a major API redesign
