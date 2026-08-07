# Task v0.1 Review Checklist

Use this checklist for internal/external review before merge.

## Core behavior

- schema upgrades from 3 to 4 without rewriting existing data
- global and project-scoped Tasks are supported
- project casing is canonicalized
- due times require timezone information and are stored in UTC
- `open -> completed` works
- `open -> cancelled` works
- terminal Tasks reject further terminal transitions
- scheduled Tasks sort before unscheduled Tasks

## HTTP boundary

- all `/tasks` routes remain behind existing authentication middleware
- create/list/get/complete/cancel return stable sanitized responses
- unknown projects and malformed inputs fail safely
- task routes use existing no-store private-response behavior

## Security architecture

- Task remains intention only
- no external side effect is executable from Task fields
- no Tool/Approval/Operation logic is smuggled into this PR
- future approvals must bind to frozen operation specs, not mutable Tasks

## Regression boundaries

- memory lifecycle unchanged
- profile import unchanged
- semantic retrieval unchanged
- model Run logging unchanged
- conversation/chat behavior unchanged
- Railway entrypoint remains `backend.application:app`

## Production verification

- `/ready` after schema 4 migration
- normal chat + Run logging still work
- create/read/complete one disposable Task
- verify Task does not create a Memory
- verify terminal conflict returns 409
