# Memory Forget and Restore Production Verification — August 1, 2026

**Purpose:** Record production verification of PR #16 before keyword-retrieval work begins.

This record contains no conversation content, memory content, secret, database file, or private path.

## Deployment

- PR #16 was squash-merged into `main`.
- Merged commit: `efd970336ed03535c2704bba2c8dc5655aa63b10`
- Railway deployed the merged application successfully.
- Private login and the protected Memory page remained available.
- Existing active memories remained visible after deployment.
- No new schema migration was required; the feature reused schema 2.

## Recoverable forget verification

- Moot selected one active test memory through the protected Memory page.
- MootOS confirmed that the memory moved to Archived and was removed from normal recall.
- The unrelated active memory remained visible and unchanged.
- The selected row appeared in the Archived view with its content, scope, project, source, correction-version label, archived status, and Restore control intact.

## Recall exclusion verification

- A brand-new conversation with no project selected was opened while the test memory was archived.
- MootOS did not recall the archived value and instead reported insufficient context.
- This verified that archived rows were excluded from normal model context in production.

## Restore verification

- Moot restored the same archived row through the protected Memory page.
- MootOS confirmed that the memory returned to active recall.
- The Archived view became empty for that row.
- The Active view again showed both expected active memories.
- A brand-new conversation recalled the restored value again.

## Rebuild persistence verification

- Railway completed another rebuild after restoration.
- A new conversation still recalled the restored active value.
- The restored lifecycle state therefore persisted through the rebuild on the Railway volume.

## Result

PR #16 is production-verified for:

- UI-selected recoverable forgetting
- Archived-view visibility
- Exclusion of archived memory from normal recall
- Restoration of the same stored row
- Return of restored memory to normal recall
- Preservation of unrelated memories
- Persistence through a Railway rebuild

Permanent deletion, secure erasure, natural-language forget commands, bulk lifecycle actions, automatic retention, and keyword retrieval remain outside PR #16.
