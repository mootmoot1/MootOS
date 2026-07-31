# MootOS Manual Backup and Restore Procedure

**Applies to:** Current single-user Railway deployment  
**Production database:** `/data/mootos.db`  
**Current schema:** `1 — initial_schema`

This procedure is the safety checkpoint before the first production schema change after PR #12.

It documents how to create a consistent SQLite backup, move it off the Railway volume, and prove that the copy can be opened. It does not claim that automated backup, retention, encryption, or disaster recovery is implemented.

## Safety rules

- Keep one Railway replica.
- Do not copy only `mootos.db` with a normal filesystem command while the application is writing.
- Do not delete `mootos.db-wal` or `mootos.db-shm` while the application is running.
- Use SQLite's backup API to create a consistent snapshot.
- A copy stored only under `/data` is not an off-volume disaster-recovery backup.
- Never overwrite the production database during a restore drill.
- Do not edit `schema_migrations` to make a backup appear compatible.
- Production restore requires explicit approval and a maintenance window.

## Stage 1 — Create a consistent snapshot on the Railway volume

Run the following inside the MootOS Railway service environment. It uses Python's standard-library SQLite backup API, so no separate SQLite command-line program is required.

```bash
python - <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3

source = Path("/data/mootos.db")
backup_dir = Path("/data/backups")
backup_dir.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
destination = backup_dir / f"mootos-{timestamp}.db"

if not source.exists():
    raise SystemExit(f"Production database not found: {source}")

with sqlite3.connect(source) as source_connection:
    with sqlite3.connect(destination) as backup_connection:
        source_connection.backup(backup_connection)

with sqlite3.connect(destination) as verification_connection:
    integrity = verification_connection.execute("PRAGMA integrity_check").fetchone()[0]
    schema_rows = verification_connection.execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    conversation_count = verification_connection.execute(
        "SELECT COUNT(*) FROM conversations"
    ).fetchone()[0]
    memory_count = verification_connection.execute(
        "SELECT COUNT(*) FROM memories"
    ).fetchone()[0]

if integrity != "ok":
    destination.unlink(missing_ok=True)
    raise SystemExit(f"Backup integrity check failed: {integrity}")

digest = sha256(destination.read_bytes()).hexdigest()

print(f"backup_path={destination}")
print(f"sha256={digest}")
print(f"integrity={integrity}")
print(f"schema_migrations={schema_rows}")
print(f"conversation_count={conversation_count}")
print(f"memory_count={memory_count}")
PY
```

Record:

- Backup filename
- UTC timestamp
- SHA-256 digest
- Integrity result
- Migration rows
- Conversation count
- Memory count
- Application commit deployed at the time

This snapshot protects against a bad migration only while the Railway volume itself remains available. Continue to Stage 2.

## Stage 2 — Move the snapshot off the Railway volume

Use Railway's currently supported file-transfer method to download the generated backup to an approved private location outside the production volume.

The exact Railway interface or command may change. The safety requirements do not:

1. Transfer the generated `.db` file without modifying it.
2. Keep it private; the database may contain personal memories and conversation history.
3. Recalculate SHA-256 after transfer.
4. Confirm it matches the digest printed during Stage 1.
5. Store the recorded metadata beside the backup.
6. Do not commit the database, hash record containing private paths, or backup contents to GitHub.

A backup is not considered off-volume until the transferred copy has a matching digest.

## Stage 3 — Non-production restore drill

Perform this drill on a local machine or isolated non-production service. Do not restore over production.

1. Make a working copy of the downloaded backup.
2. Verify its SHA-256 digest.
3. Run the following integrity and schema check:

```bash
python - <<'PY'
from pathlib import Path
import sqlite3
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: python verify_backup.py /path/to/mootos-backup.db")

path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(f"Backup not found: {path}")

with sqlite3.connect(path) as connection:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    migrations = connection.execute(
        "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    projects = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    conversations = connection.execute(
        "SELECT COUNT(*) FROM conversations"
    ).fetchone()[0]
    messages = connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    memories = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

print(f"integrity={integrity}")
print(f"schema_migrations={migrations}")
print(f"projects={projects}")
print(f"conversations={conversations}")
print(f"messages={messages}")
print(f"memories={memories}")

if integrity != "ok":
    raise SystemExit(1)
PY
```

For direct use, save that snippet as `verify_backup.py`, then run:

```bash
python verify_backup.py /path/to/mootos-backup.db
```

4. Start MootOS locally or in isolation with `MOOTOS_DATABASE_PATH` pointing to the working copy.
5. Confirm startup accepts the recorded schema.
6. Confirm at least one known conversation opens.
7. Confirm at least one known memory is listed or recalled.
8. Do not write test data into the original downloaded backup; use only the working copy.

The restore drill is complete only after the application reads the restored copy successfully.

## Production restore outline

A real production restore is a high-risk operation. Use this only after diagnosis, explicit approval, and a verified backup.

1. Stop normal writes and establish a maintenance window.
2. Record the currently deployed commit, schema version, volume, and database path.
3. Create one final backup of the current database when possible, even if it may be damaged.
4. Preserve the current database under a different filename instead of deleting it.
5. Verify the selected restore file's digest and `PRAGMA integrity_check` result.
6. Confirm the deployed code supports the backup's schema version.
7. With the application stopped, place the verified database at `/data/mootos.db`.
8. Start one replica.
9. Confirm health and login.
10. Confirm known conversations and memories.
11. Create one new test record and verify it persists through a restart.
12. Record the incident, backup used, hashes, timestamps, and outcome.

Do not restore an older database merely to fix a code bug. Prefer a code rollback when the current data is valid and the deployed code is the problem.

## Current verification status

- PR #12 memory persistence through a Railway rebuild is production-verified.
- This manual procedure is documented.
- A consistent off-volume backup has not yet been recorded in the repository documentation.
- A non-production restore drill has not yet been recorded.
- Automated encrypted backups, retention, and point-in-time recovery are not implemented.

Before migration 2 changes the memory lifecycle schema, record completion of Stages 1–3 without committing private backup data.