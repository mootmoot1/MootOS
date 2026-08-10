# MootOS Narrow Self-Inspection (V0.3C, Part A)

**Status:** Implemented on branch `claude/v0.3c-self-inspection-web-awareness`.
Not merged to `main`. Not yet production-verified.
**Schema:** unchanged (`5 — tool_system`) — V0.3C added no migration.
**Applies to:** the self-inspection surface added in V0.3C on top of merged
V0.3A/V0.3B.

Companion documents: `docs/WEB_AWARENESS.md` (V0.3C Part B),
`docs/TOOL_SYSTEM.md` (the Tool System this registers into),
`docs/CAPABILITY_ARCHITECTURE.md` §6 (V0.3C).

## 1. What problem this solves

Before V0.3C, MootOS could describe *what it can do* (V0.3A's generated
manifest) but could not explain *how it works* or *what phase it is on*
except from model memory — which is exactly the unreliable source this
whole architecture exists to replace. V0.3C Part A gives it a narrow,
curated, read-only window onto its own architecture documents and live
runtime state.

Deliberately **not** general repository browsing. Per
`docs/CAPABILITY_ARCHITECTURE.md` §6: "an unrestricted surface produces a
confidently wrong self-model, which is worse than a narrow but accurate
one."

## 2. Module map

| Module | Responsibility |
| --- | --- |
| `backend/self_inspection.py` | The curated allow-list, bounded document reading, runtime-state description, and documentation-drift detection. |
| `backend/tools_web.py` | The two registered tools (`self.state`, `self.architecture`) — schema, risk, description, capability metadata. |
| `backend/capability_catalog.py` (unchanged) | Already the source of installed-capability truth; self-inspection reads it, never bypasses it. |

## 3. The exact surface

Two registered `RISK_READ_ONLY` tools:

### `self.state` — no arguments

Returns live, authoritative runtime truth:

```text
schema_version         from backend/migrations.py's LATEST_SCHEMA_VERSION
installed_tool_count   len of the live registry's catalog
tools                  the full V0.3A tool catalog (metadata only)
capabilities           the V0.3A derived capability index
available_documents    which curated documents self.architecture can read
documentation_notes    detected documentation/runtime disagreement (§5)
authority_note         a fixed statement that this list, not documentation, is correct
```

Contains capability and schema metadata only — never tool arguments,
conversation content, secrets, environment values, or user data.

### `self.architecture` — one enum-constrained `document` key

Returns one allow-listed document's content, bounded and prefaced.

**The enum is the security boundary.** `input_schema` declares
`{"type": "string", "enum": sorted(CURATED_DOCUMENTS)}`, and
`backend/tool_validation.py` rejects any value outside that enum *before*
the executor runs. A path string can therefore never reach
`backend/self_inspection.py` at all.

## 4. The curated allow-list

`CURATED_DOCUMENTS` in `backend/self_inspection.py` is the complete set of
files this surface can reach — seven architecture/status markdown
documents that already ship in the repository:

| Key | Path |
| --- | --- |
| `architecture` | `ARCHITECTURE.md` |
| `roadmap` | `ROADMAP.md` |
| `capability_architecture` | `docs/CAPABILITY_ARCHITECTURE.md` |
| `current_checkpoint` | `docs/CURRENT_CHECKPOINT.md` |
| `tool_system` | `docs/TOOL_SYSTEM.md` |
| `gap_reasoning` | `docs/GAP_REASONING.md` |
| `decisions` | `DECISIONS.md` |

Adding an entry is a deliberate, reviewed code change. Nothing a model, a
request, or a document says can add one at runtime.

**Not reachable, at any version:** `.env`, secrets, credentials, the
database, user data, arbitrary source files, `frontend/`, Git history, or
any path outside the repository.

### Layered path defenses

1. **There is no path parameter.** `read_document(key)`'s only argument is
   an allow-listed key; MootOS has no `read_file(path)` and V0.3C does not
   add one. Even the real repository path of an allow-listed document
   (`"ARCHITECTURE.md"`) is rejected, because paths are not the interface.
2. **The tool enum** rejects non-keys at schema validation, before any
   executor code runs.
3. **Post-resolution containment**: the resolved path is re-checked with
   `is_relative_to(_REPOSITORY_ROOT)` before opening, so a future typo or
   symlink in the allow-list still cannot escape the repository.

`tests/test_self_inspection.py` exercises 12 parametrized hostile inputs
(`.env`, `../../etc/passwd`, `backend/auth.py`, `.git/config`, `..`, …)
against both the direct function and the registered tool.

## 5. Runtime truth beats documentation

The V0.3C honesty rule: **documentation may explain architecture and
roadmap, but must never make an unregistered tool appear installed.**

Rather than silently preferring one source, MootOS surfaces disagreement.
`detect_documentation_drift()` compares the specific tool names the
curated documents assert are registered against the live registry, and
`describe_runtime_state()` returns any mismatch in `documentation_notes`,
e.g.:

```text
docs/TOOL_SYSTEM.md describes 'tasks.create' as a registered tool, but it
is NOT in the live Tool Registry. The registry is authoritative: this tool
is not currently installed.
```

Deliberately narrow: it checks a small, concrete list of documented tool
names. It is not a general documentation parser, and it never *changes*
what is installed — it only describes a mismatch.

Every returned document is additionally prefixed with `DOCUMENT_PREAMBLE`,
marking it as reference material that is *not* authoritative about
installed tools, and instructing that its text is content rather than
instructions.

## 6. Bounded output

Architecture documents are 12–33KB each and the model input budget
(ADR-022) is finite. `DOCUMENT_MAX_CHARACTERS` (12,000) bounds each read,
with an explicit, visible `[TRUNCATED by MootOS self-inspection: …]`
notice — never silent truncation. `read_document` also returns a
`truncated` boolean.

## 7. Auditing and privacy

Both tools go through the standard centralized executor
(`docs/TOOL_SYSTEM.md` §7), producing an ordinary `run_type = "tool"` Run
with `data_exposure = local`. No new audit path, no schema change.

Errors are sanitized: a filesystem `OSError` never surfaces its path or OS
message — `SelfInspectionError` carries only `"Document could not be
read."`, and the Run records only the exception class name.

## 8. Out of scope

No V0.3D protected-core gates, no V0.3E capability building, no local
node, no Codex automation, no arbitrary repository browsing, no filesystem
traversal, no shell execution, and no write of any kind. Self-inspection
reads; it never modifies MootOS.
