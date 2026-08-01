# Backup and Restore Verification — August 1, 2026

**Purpose:** Record the completed manual safety gate before migration 2 changes the memory lifecycle schema.

This record contains no database file, conversation content, memory content, secret, or private local path.

## Production snapshot

- Deployed application commit: `78806da6c9d4ba33f956b65b17c3dbb549031f83`
- Production database: `/data/mootos.db`
- Snapshot method: Python standard-library SQLite online backup API
- Snapshot UTC timestamp: `2026-08-01T02:24:51Z`
- Backup filename: `mootos-20260801T022451Z.db`
- SHA-256: `b055b4315acbec122fba3093c714839b3e734b8a95a074e5676f370fe40b8e34`
- `PRAGMA integrity_check`: `ok`
- Schema: `1 — initial_schema`
- Projects: `5`
- Conversations: `15`
- Messages: `58`
- Memories: `2`

The snapshot was created on the Railway volume during a quiet period. Production remained online and the live database was not replaced or modified by the verification process.

## Off-volume verification

- The generated database snapshot was downloaded from Railway to a private Mac.
- SHA-256 was recalculated after download.
- The downloaded digest matched the Railway digest exactly.
- The backup remained private and was not committed to GitHub.

## Non-production restore drill

- A separate working copy was created from the downloaded backup.
- The original downloaded backup remained untouched.
- The working copy passed `PRAGMA integrity_check` with `ok`.
- MootOS was started in an isolated environment with `MOOTOS_DATABASE_PATH` pointing to the working copy.
- The application returned health HTTP `200`.
- The memory interface loaded.
- All five projects and all fifteen conversations were readable.
- A known conversation opened with stored messages.
- Both known memories were readable.
- The original backup's SHA-256 remained unchanged after the drill.

The isolated environment did not have the OpenAI package available. An import-only stand-in was used so the FastAPI application could start. No model request was made, and the stand-in did not participate in database, API, conversation, or memory verification.

## Result

Stages 1–3 of `docs/MANUAL_BACKUP_AND_RESTORE.md` are complete. The manual pre-migration safety gate is cleared for migration 2 development.

This does **not** mean automated encrypted backups, retention, scheduled restore testing, disaster recovery, or point-in-time recovery are implemented. Those remain future work.
