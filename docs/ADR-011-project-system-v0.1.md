# ADR-011: Minimal Project System for Version 0.1

## Status

Proposed

## Date

July 2026

## Context

MootOS Version 0.1 requires memories to be organized into projects, while the
longer roadmap reserves full project management for Version 0.2. The current
memory API accepts any project name as unvalidated text, which allows spelling
variations and nonexistent projects to fragment memory retrieval.

## Decision

Version 0.1 will include a minimal persistent project catalog.

The database will seed these five default projects:

- MootOS
- Studio
- Social Media
- Cars
- Personal

The API will allow projects to be listed and new projects to be created.
Memories may remain unassigned, but any supplied project must already exist.
Memories may be filtered by project.

Version 0.1 will not include project deletion, renaming, tasks, files, goals,
deadlines, permissions, or project activity history.

## Consequences

- Project names remain consistent across saved memories.
- The initial project organization requirement is satisfied without building
  the full Version 0.2 project-management system.
- Project deletion and renaming are intentionally deferred because they require
  explicit rules for existing memories.
- Memories continue storing the canonical project name as text for now. A
  future migration may replace it with a project ID foreign key if necessary.
