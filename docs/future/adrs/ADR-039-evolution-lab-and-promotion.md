# ADR-039 — Evolution Lab is disposable; discoveries enter production through an explicit promotion path

## Status
Proposed future decision; not implemented.

## Decision
Create disposable Evolution/Jarvis Lab repos where coding agents may aggressively implement hundreds to ~1,000 slices and merge freely inside the lab. Preserve tests, checkpoints, architecture notes, and failure evidence.

Lab output never directly becomes production authority. A Lab Promotion Engine classifies discoveries as promote now/save later/reject, packages high-value discoveries, and requires Moot approval before temporarily reprioritizing production work.

After promoted slices are integrated through normal production gates, the Chief Builder resumes the saved roadmap position.
