# MootOS Data and Persistence

**Applies to:** MootOS Version 0.1 as of July 31, 2026

This document explains where MootOS stores data, what the Railway volume protects, how to verify persistence, what redundancy means for the current system, and when the database design should change.

## 1. Current database choice

MootOS uses SQLite.

SQLite is a database engine stored in one file. It does not require a separate database server, account, network connection, or managed database service.

For the current single-user MootOS deployment, SQLite provides:

- Simple local development
- Low operational cost
- Fast reads and writes for a small personal workload
- Easy portability to a future local computer
- A database file that can be backed up and restored
- A small dependency footprint

SQLite is not being used because it is the newest database. It is being used because it matches the present workload and local-first direction.

## 2. What is stored

The SQLite file currently contains:

- Projects
- Long-term memory entries
- Conversations
- User messages
- Assistant messages
- Model-provider and model metadata for assistant messages

Frontend files, source code, secrets, and application configuration are not stored in SQLite.

## 3. Database path selection

MootOS selects the database path in this order:

### Priority 1 — Explicit override

When `MOOTOS_DATABASE_PATH` is set, MootOS uses that exact path.

Example:

```text
MOOTOS_DATABASE_PATH=/private/mootos/custom.db
```

This is useful for testing, recovery, controlled migration, or a future local installation.

### Priority 2 — Railway volume

When Railway attaches a volume, it supplies `RAILWAY_VOLUME_MOUNT_PATH`.

The approved production mount path is:

```text
/data
```

MootOS stores the production database at:

```text
/data/mootos.db
```

### Priority 3 — Local development

Without either environment variable, MootOS stores the database at:

```text
data/mootos.db
```

inside the repository working directory.

## 4. Verified production persistence

On July 31, 2026:

- A Railway volume named `mootos-volume` was attached to the MootOS service.
- The volume was mounted at `/data`.
- MootOS deployed successfully and returned online.
- A saved conversation and memory remained available after three consecutive Railway deployments.

This verifies that normal Railway rebuilds are using the persistent volume instead of the temporary application filesystem.

This test proves deployment persistence. It does not replace backups or prove recovery from database corruption.

## 5. One replica rule

Keep the Railway service at **one replica** while SQLite remains the live production database.

Reason:

- SQLite is one database file.
- Multiple application replicas can create confusing ownership and coordination problems around one file or separate files.
- The current application has not been designed or tested for multiple writers across replicas.

Do not increase replicas as a performance experiment. A move to multiple application replicas should be treated as a database architecture change and documented through a new ADR.

## 6. Redundancy versus double-writing

Redundancy is good. Writing every application change to two unrelated live databases at the same time is not the recommended Version 0.1 approach.

A dual-write system creates new failure questions:

- What happens when SQLite succeeds and the second database fails?
- Which database becomes the source of truth?
- How are differences detected?
- How are partial writes repaired?
- What happens when records receive different IDs or timestamps?
- Which database is trusted during restore?

For the current system, the recommended redundancy model is:

```text
One live SQLite database
        |
        v
Regular verified backup copies
        |
        v
Documented restore procedure
```

This gives MootOS one clear source of truth while protecting against accidental deletion, broken deployments, device failure, or database damage.

## 7. Current backup status

The Railway volume protects data from normal application redeployments.

The repository does **not** currently implement:

- Automatic scheduled database backups
- Encrypted off-platform backups
- Backup retention rules
- One-click restore
- Automated restore tests
- Point-in-time recovery

Until those features are built, the volume should not be treated as a complete disaster-recovery system.

## 8. Safe backup direction

A future backup feature should:

1. Create a consistent SQLite backup instead of copying a file during an active write.
2. Write the backup to a separate location from the live volume.
3. Encrypt backups containing private memories.
4. Record backup time, size, and checksum.
5. Keep more than one historical copy.
6. Test restore into a non-production environment.
7. Require explicit approval before replacing the live database.

Potential destinations may include:

- An encrypted local computer
- Encrypted object storage
- A second controlled storage provider
- A future self-hosted backup device

No destination should be selected until privacy, cost, authentication, and restore behavior are documented.

## 9. Manual persistence verification

After a storage or deployment change:

1. Log in to the production MootOS interface.
2. Create a uniquely named test conversation.
3. Add a unique memory or message containing the current date.
4. Confirm it appears before deployment.
5. Deploy or redeploy the Railway service.
6. Wait until the service is online.
7. Log in again.
8. Reopen the conversation and verify the exact test content remains.
9. Repeat when validating a new storage architecture.

Do not delete an old database or detach a volume merely because a new deployment appears healthy.

## 10. Current schema limitations

The database schema is created with `CREATE TABLE IF NOT EXISTS`.

That works for creating missing tables but does not provide controlled schema evolution. It cannot safely document or sequence changes such as:

- Adding required columns
- Renaming columns
- Moving data between tables
- Creating new relationships
- Transforming existing values
- Rolling back an incompatible release

Before adding substantial new database-backed features, MootOS should receive a versioned migration system.

The recommended first migration system can remain lightweight:

- `schema_version` table
- Ordered migration files or Python migration functions
- Migration applied once in a transaction
- Tests for clean install and upgrade from the previous schema
- Recorded migration failures

Alembic is an option, but it is not mandatory for the current project size.

## 11. Current SQLite hardening gaps

The current implementation has not yet explicitly configured every SQLite connection for:

- Foreign-key enforcement
- Write-ahead logging (WAL)
- Busy timeout
- Deliberate synchronous mode
- Lock retry behavior

The current one-user, one-replica system has worked in production testing. These gaps should still be addressed in a focused foundation-hardening code PR before the workload or schema becomes significantly more complex.

This documentation PR does not change database behavior.

## 12. When to keep SQLite

Keep SQLite while most of the following remain true:

- Moot is the only user
- Railway remains at one replica
- The workload is mostly conversation and memory storage
- Writes are relatively low volume
- The database fits comfortably on one volume
- Local-first portability remains important
- Operational simplicity matters more than horizontal scaling

SQLite can support a serious personal application for a long time under those conditions.

## 13. When to consider PostgreSQL

Consider PostgreSQL when one or more of these become real requirements:

- Multiple independent user accounts
- Multiple application replicas
- Many simultaneous writers
- Strong server-side access controls
- Managed automated backups and point-in-time recovery
- Complex analytics and reporting
- Large relational workflows
- A commercial hosted product used by many studios or customers
- Cross-device synchronization requiring a central authoritative server

A move to PostgreSQL should be a planned migration, not a last-minute reaction. The application should first centralize database access and add schema migrations so the move is controlled.

## 14. DynamoDB and MongoDB

DynamoDB and MongoDB are valid databases, but “newer” or “larger scale” does not automatically mean “better for MootOS.”

### DynamoDB

Best suited to workloads designed around Amazon Web Services, known access patterns, high scale, and managed distributed storage. It adds cloud dependency and a different data-modeling style.

### MongoDB

Stores document-shaped records and can be useful when data varies heavily. MootOS currently has clear relationships between projects, memories, conversations, and messages, which fit a relational database naturally.

### PostgreSQL

The most likely future hosted-database upgrade for MootOS because it preserves relational modeling, transactions, constraints, and familiar SQL while supporting more users and concurrent application instances.

No database migration is currently justified solely because another database has newer branding or can support workloads MootOS does not yet have.

## 15. Source of truth

The live SQLite database on the mounted Railway volume is currently the production source of truth.

GitHub stores source code and documentation, not production conversations or memories.

OpenAI is used to generate model responses but is not configured as MootOS's conversation-history store. The application calls the Responses API with provider-side response storage disabled and keeps its own history in SQLite.

## 16. Rules before storage changes

Before changing any storage behavior:

- Create a focused branch and PR
- Explain the reason in plain language
- Identify the source of truth
- Define migration and rollback steps
- Protect the current production database
- Add automated migration tests
- Verify a backup exists
- Test restore separately
- Keep secrets out of GitHub
- Receive Moot's explicit approval before production migration
