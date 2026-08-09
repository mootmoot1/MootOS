# MootOS Structured Gap Reasoning (V0.3B)

**Status:** Implemented on branch `claude/v0.3b-structured-gap-reasoning`.
Not merged to `main`. Not yet production-verified.
**Schema:** unchanged (`5 — tool_system`) — V0.3B added no migration.
**Applies to:** the gap-reasoning layer added in V0.3B on top of the
merged V0.3A Capability-Aware Tool System.

This document describes what Structured Gap Reasoning *is*, how the model
interpretation / deterministic verification boundary is enforced, and how
it's audited. It complements — and does not replace — `docs/TOOL_SYSTEM.md`
(the Tool System gap reasoning reads from) and
`docs/CAPABILITY_ARCHITECTURE.md` (the overall plan this implements, §6
V0.3B; decision record ADR-030).

## 1. What problem this solves

V0.3A let MootOS truthfully describe what it currently has. V0.3B lets it
take a natural-language goal and produce a structured, auditable answer to
"can you do this?" — without executing anything, installing anything, or
letting the model's own claims about installed state be trusted:

```text
user goal
  -> model interpretation (proposed capability requirements)   [non-deterministic]
  -> deterministic resolution against the live V0.3A capability index
  -> GapReport
```

This is reasoning only. A `GapReport` can never become executable — see
§5.

## 2. Module map

| Module | Responsibility |
| --- | --- |
| `backend/gap_reasoning.py` | Everything described in this document: the model-facing contract, strict validation, deterministic resolution, classification, and the audited `analyze_goal` entry point. |
| `backend/model_router.py` (extended) | `ModelRouter.generate_standalone` — a narrow model call with no chat-oriented instruction injection (§4). |
| `backend/capability_catalog.py` (unchanged) | `build_capability_index` is the only source of "what's installed" this module reads. |
| `backend/runs.py` (unchanged) | Reused as-is for auditing (§6) — no new Run type, no new column. |

## 3. The model interpretation / deterministic verification boundary

This is the one rule this whole module exists to enforce:

**The model may propose what a goal appears to need. It may never decide
whether a proposed capability is actually installed.**

Concretely:

- The model's output (`requirements: [{capability, reason,
  externally_blocked}, ...]`) is parsed and strictly validated
  (§4) into plain, inert data — never executed, never trusted as fact.
- `resolve_requirements()` (§5) is the *only* place that decides
  `installed`/`tools` for each requirement, and it does so by looking the
  model's proposed `capability` string up in
  `backend.capability_catalog.build_capability_index(registry)` — the same
  derived, registry-backed view V0.3A already built. A capability id the
  model invents that the index doesn't contain always resolves
  `installed=False`, no matter how confidently the model's `reason` text
  asserts otherwise (`tests/test_gap_reasoning.py::
  test_model_asserting_installed_via_reason_text_does_not_verify_it`).
- The proposal schema has **no field** the model could use to assert
  installation, verification, or backing tools — an attempt to add one
  (e.g. `"installed": true`) is an unrecognized key and fails the entire
  payload closed (§4), rather than being silently accepted or ignored.
- `GapReport.classification` (§5) is computed here, deterministically,
  from the resolved per-requirement `installed`/`externally_blocked`
  flags — the model never states or influences the overall
  classification directly.

## 4. Model-facing contract

`_propose()` calls `ModelRouter.generate_standalone(messages, instructions)`
— a single message (the goal text) with a fixed, self-contained
instructions string built by `_build_instructions()`, which lists the
live capability index (`id: label` only — no tool descriptions, arguments,
or internals) as reference vocabulary, and requires:

```json
{"requirements": [{"capability": "<dotted.id>", "reason": "<short text>", "externally_blocked": <true|false>}]}
```

with nothing else in the response — no prose, no markdown, no code fence.

**Why `generate_standalone`, not `generate`.** `ModelRouter.generate()`
always routes through `prepare_model_input`, which unconditionally injects
the chat capability manifest and `CONVERSATION_RULES` (ADR-022). Those are
chat-behavior instructions ("ask a clarifying question," "do not repeat
the conversation") that would only work against a task whose entire job is
emitting one strict JSON object with no history or memory context.
`generate_standalone` calls the provider directly — same provider
selection, `ensure_ready()`, and sanitized `ModelProviderError` boundary as
`generate()`, just without the chat-pipeline injection.

**Strict validation, fail closed.** `_parse_and_validate_proposal()`:

1. Strips a whole-response ```` ``` ````/```` ```json ```` fence if present
   (defensive — models often add one despite instructions). Leading prose
   before a fence is *not* extracted from; that response still fails
   parsing.
2. `json.loads` — any parse failure raises `GapAnalysisError`.
3. The parsed value must be exactly `{"requirements": [...]}` — no missing
   key, no extra key, wrong type, or more than `MAX_REQUIREMENTS` (10)
   items all raise `GapAnalysisError`.
4. Each item must be exactly `{"capability": str, "reason"?: str,
   "externally_blocked"?: bool}` — no extra key. `capability` must match
   `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$` after
   lowercasing/stripping (case/whitespace normalization only — never
   fuzzy/semantic matching) and be ≤100 characters; `reason` is capped at
   300 characters.

There is no partial acceptance: if *any* item fails, the whole analysis
raises `GapAnalysisError` — never a malformed or partially-trusted
`GapReport`. Callers get one exception type to handle, with a safe, generic
message (never the raw model text).

## 5. Deterministic resolution and classification

`resolve_requirements(proposed, registry)` builds one `RequirementResolution`
per validated item:

```text
capability            the model-proposed id (model interpretation)
reason                the model's stated reason (model interpretation)
externally_blocked    the model's judgment (model interpretation)
installed              True iff capability appears in build_capability_index(registry)   (deterministic)
tools                  backing tool names if installed, else ()                          (deterministic)
```

`_classify()` computes the overall classification from those resolved
flags only:

```text
any requirement externally_blocked?          -> externally_blocked
else any requirement not installed?          -> capability_gap
else >= 2 distinct installed capabilities?   -> composable
else                                          -> already_possible
```

A capability being merely missing is never, by itself, `externally_blocked`
— only an explicit model-asserted flag produces that classification
(`tests/test_gap_reasoning.py::test_missing_capability_alone_is_not_externally_blocked`),
matching ADR-030/`docs/CAPABILITY_ARCHITECTURE.md`'s explicit warning
against treating a missing connector as permanent impossibility. When any
requirement *is* flagged, the overall goal is classified
`externally_blocked` even if other parts are available/composable — part
of a goal being genuinely blocked means the whole goal isn't achievable as
stated, and `notes` (a deterministic, templated string — never free model
prose) lists what's blocked, what's missing, and what's already installed
separately.

### Two framing limits that must stay explicit

**`composable` does not mean composition is proven.** It means every
proposed capability the goal needs is installed and more than one
distinct capability is involved — nothing more. V0.3B has no composition
planner: it never checks whether those capabilities can actually be
combined to accomplish the goal (that stays deferred — see
`docs/CAPABILITY_ARCHITECTURE.md` §9's "persistent workflow engine"
non-goal). `notes` for a `composable` report always reads along the lines
of *"Multiple required capabilities are installed (...); composition
feasibility has not been proven in V0.3B. This is a candidate composition,
not a verified executable plan."* — never wording like "achievable by
combining," which would overclaim. `tests/test_gap_reasoning.py::
test_composable_notes_never_claim_achievability_or_proof` guards this
wording so it cannot regress.

**`externally_blocked` is a model interpretation, not a registry-verified
fact.** Unlike `installed` (always checked against the Tool Registry),
nothing verifies whether a requirement is genuinely, permanently blocked
— that determination comes entirely from the model's own
`externally_blocked` flag. `notes` for a blocked report always attributes
the judgment explicitly — *"The model judged the following requirement(s)
externally blocked: ...; installed-state verification is separate."* — so
it reads as the model's claim, not MootOS's own verified conclusion.
`tests/test_gap_reasoning.py::test_externally_blocked_notes_attribute_the_judgment_to_the_model`
guards this wording.

No alias table, ontology, dependency graph, or fuzzy matcher exists or is
planned for V0.3B — matching `docs/CAPABILITY_ARCHITECTURE.md`'s explicit
"what NOT to build yet" list. If a real need for a minimal, explicit alias
ever appears, it belongs here as a small, reviewed addition, not a general
matching engine.

## 6. `GapReport` schema

```text
goal                              the (length-capped) user-supplied goal text
requirements                      tuple[RequirementResolution, ...] -- full per-item detail
available_capabilities            tuple[str, ...] -- installed, not externally_blocked, deduped+sorted
composable_capabilities           same as available_capabilities, but only populated when
                                   classification == "composable"; () otherwise. A candidate
                                   composition only -- composition feasibility is never checked.
missing_capabilities              tuple[str, ...] -- not installed, not externally_blocked, deduped+sorted
externally_blocked_capabilities   tuple[str, ...] -- model-flagged, deduped+sorted. A model
                                   interpretation, not a registry-verified fact.
classification                    already_possible | composable | capability_gap | externally_blocked
notes                             deterministic, templated summary string (never free model prose)
```

`GapReport.to_dict()` / `RequirementResolution.to_dict()` return plain,
JSON-serializable data — no executor, no callable, nothing that could be
used to run or install anything (`tests/test_gap_reasoning.py::
test_gap_report_and_resolution_objects_carry_no_executor`). Attempting to
execute a capability id directly (the only thing one could be used for)
fails exactly like any other unregistered tool name —
`backend.tool_executor.execute_tool` raises `ToolNotFoundError`
(`tests/test_gap_reasoning.py::test_a_proposed_capability_can_never_be_executed`).

## 7. Auditing

Every `analyze_goal()` call starts a `RUN_TYPE_MODEL` Run
(`backend.runs.start_model_run`) **before** validating the goal, so even a
rejected/empty-goal attempt is audited — matching the Tool System's own
"early rejections still get a Run" philosophy
(`docs/TOOL_SYSTEM.md` §7). It finishes `succeeded` (with the real
provider/model identity) once a valid `GapReport` is produced, or `failed`
(sanitized `error_class` only, via the existing `finish_model_run_failure`)
on any error — empty goal, provider failure, or malformed model output.

**No schema change, and no prompt/response dump is structurally possible.**
This reuses the existing `runs` table and `RUN_TYPE_MODEL` exactly as
already defined — no new run type, no new column. The table's fixed
column set (`docs/DATA_AND_PERSISTENCE.md`) has no field that could hold
the goal text, the model's raw output, or the `GapReport` body; only
identity (`provider`/`model`), status, and timing are ever recorded. This
is a structural guarantee, not a policy this module has to remember to
follow — `tests/test_gap_reasoning.py::
test_gap_analysis_run_stores_no_goal_or_model_text` and
`::test_failed_gap_analysis_run_stores_only_a_sanitized_error_class` prove
it directly. The full `GapReport` (including its classification) is
returned to the caller, exactly like a tool's `data` payload is returned
but never persisted into a Run row (`docs/TOOL_SYSTEM.md` §7).

## 8. Why an internal API, not a new HTTP route or chat integration

V0.3B ships `analyze_goal()` as a plain, directly testable Python function
— the same choice V0.3A made for `describe_installed_abilities()`
(`docs/TOOL_SYSTEM.md` §16) and for the same reasons: no new API surface
was explicitly requested, and adding one is a separate product decision
(how/when a user actually triggers gap analysis in the chat UI, what the
natural-language answer layer looks like) that belongs to a later,
deliberate integration pass — not something to fold into the reasoning
engine itself.

## 9. Out of scope for V0.3B

No web search, no repository self-inspection, no protected-core mechanical
gates, no capability building, no local node, no Codex bridge, and no
workflow persistence were added. No new registered tool, no new HTTP
route, and no database migration. See `docs/CAPABILITY_ARCHITECTURE.md`
§6 for where each of these is actually planned (V0.3C–V0.4D).
