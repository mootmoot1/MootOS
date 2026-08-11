# MootOS Protected Core + Mechanical Release Gates (V0.3D)

**Status:** Implemented on branch `claude/v0.3d-protected-core-gates`,
pending merge. See `docs/CAPABILITY_ARCHITECTURE.md` §6 (V0.3D) and
ADR-031 for the decision this document carries out.
**Applies to:** `scripts/gates/`, `tests/test_gates_*.py`, and the
`protected-core-gates` job in `.github/workflows/python-package.yml`.

This document describes what the V0.3D gates actually check, how they run,
and — just as importantly — what they do **not** prove. It is written so a
future reader (human or model) can decide whether to trust a green gate
result without re-reading the source.

## 1. Why this exists

ADR-031's premise: once something other than a person directly reviewing a
diff can propose changes to MootOS (a future capability builder, V0.4A),
"the docs say don't touch auth" stops being enough. It has to become "a
diff touching auth cannot pass," mechanically, before that day arrives.
V0.3D builds that mechanism — nothing else. No capability builder, local
node, Codex bridge, external write tool, workflow persistence, or
self-installation exists yet or is enabled by this work.

## 2. What is protected, and why

`scripts/gates/policy.py` is the single source of truth for the protected
path list (`DENIED_PATHS`). As of this writing it protects:

- `backend/tool_executor.py` — the central executor; the only place a
  tool's `executor` callable is meant to be invoked (risk/approval
  enforcement lives here)
- `backend/tool_operations.py` — the frozen approval state machine
- `backend/tool_conversation.py`, `backend/tool_budget.py`,
  `backend/tool_types.py`, `backend/tool_validation.py`,
  `backend/tool_registry.py` — the rest of the Tool System's enforcement
  and contract machinery, including the authoritative
  `build_default_registry` registration path
- `backend/auth.py` — session/auth enforcement
- `backend/main.py`, `backend/application.py`, `backend/tool_routes.py` —
  production routing, including `/chat` and the tool-operations HTTP
  surface
- `railway.toml` — production deployment configuration
- `.github/workflows/` — CI itself, including the gates below
- `scripts/gates/` — the gate policy and implementation (see §5)

Deliberately **not** protected: `backend/tools_reference.py`,
`backend/tools_web.py`, `backend/migrations.py`, and any future
`backend/tools_*.py` module. Those are exactly where legitimate new tool
modules and additive schema changes belong; blocking them outright would
make V0.3E/V0.4A's eventual "add a tool module + tests + docs +
registration entry" workflow impossible by construction. `migrations.py`
gets its own dedicated, nuanced gate instead of a blanket block — see §4.

A failing protected-path result is not a claim that the change is wrong.
It is a mechanical signal that the change needs the elevated, explicit
human review those files always required (ADR-031); the gate cannot grant
that review, only a person can.

## 3. The gates, one by one

All five live in `scripts/gates/` and are orchestrated by
`scripts/gates/run_gates.py`. Every gate is deterministic: none of them
calls a model, and a passing result is not merge authority (§7).

### 3.1 Protected-path gate (`protected_paths.py`)

Computes `git diff --name-only base...head` (three-dot / merge-base
semantics, matching GitHub's PR "Files changed" tab) and fails if any
changed path matches `policy.DENIED_PATHS`. Matching is exact-path or
real-directory-prefix only — no substring matching, so
`backend/tool_executor.py.bak` or `not_backend/tool_executor.py` are not
confused with the real file. `policy.ALLOWED_EXCEPTIONS` exists as a
narrow, explicit, human-maintained escape hatch for a specific future
intentional permit; it is empty today, and nothing in it may live under
`scripts/gates/` itself (enforced by a direct test, not just convention).

### 3.2 Migration safety gate (`migration_safety.py`)

Parses both the base and head versions of `backend/migrations.py` with
Python's `ast` module and diffs at the function level, plus a second pass
over the `MIGRATIONS = (...)` tuple to catch a remap that doesn't touch
any function body. It classifies every change as one of:

- a **historical** migration function's body changed → violation
- a **machinery** function (anything not named `_migration_N_...`)
  changed → violation
- a historical migration function was **removed** → violation
- a `MIGRATIONS` tuple entry for a historical version changed or
  disappeared (rename, reorder, remap) → violation
- a **new** function matching `_migration_N_...` where `N` is higher than
  any existing version → **additive notice** (passes, but the summary
  says a human must still review it — this is the "higher review gate"
  ADR-031 calls for, not an automated approval)
- a new function reusing an **existing** version number → violation
  (blocks a function from silently shadowing a historical migration)
- any other new, unrelated function → neutral, ignored

An unparseable `MIGRATIONS` tuple shape, or source that doesn't parse as
Python at all, fails closed rather than being treated as "no violations
found."

### 3.3 Risk metadata gate (`risk_metadata.py`)

Two checks: (1) `backend/tool_types.py`'s `ToolDefinition.risk` field must
have **no default value** in its dataclass definition — a default would
let a future tool silently register at whatever the default happens to be
if the author forgets to pass `risk` explicitly, which is exactly the
regression this gate exists to catch. (2) every tool in the live
`build_default_registry()` output must have a `risk` value that is one of
`VALID_RISK_LEVELS` (`RISK_READ_ONLY` / `RISK_INTERNAL_WRITE` /
`RISK_HIGH_RISK` — semantics unchanged from V0.2A/ADR-027). This gate only
checks that classification is *present and valid*; it does not, and must
not, change how `backend/tool_executor.py` authorizes a call based on that
classification — metadata is descriptive here, never authoritative over
enforcement.

### 3.4 Registration authority gate (`registration_authority.py`)

A narrow, curated pattern scan over `backend/**/*.py` — not a static-
analysis compiler. Flags two shapes: (1) a short fixed list of dynamic-
import/plugin-discovery/dynamic-execution constructs
(`importlib.import_module`, `__import__`, `pkgutil.iter_modules`,
`pkg_resources`, `entry_points(`, bare `eval(`/`exec(`) appearing anywhere
in `backend/`, none of which MootOS's documented design needs
(`docs/TOOL_SYSTEM.md` §4: "no plugin discovery, no import-by-name"); (2)
a call shaped like `<something>.executor(...)` outside
`backend/tool_executor.py` (the one approved caller) and
`backend/tool_types.py` (which defines the field but never calls it) —
`docs/TOOL_SYSTEM.md` §7 names `tool_executor.py` as the only function
allowed to invoke a tool's executor callable.

### 3.5 Secret scan (`secret_scan.py`)

See §6 — kept separate below because its limitations need their own
explanation.

## 4. Migration nuance in practice

The distinction the gate enforces is: **rewriting migration history is
always blocked; adding new, reviewed, additive schema is allowed under
stricter scrutiny.** A brand-new migration function with the next
sequential version number passes the mechanical gate but is flagged with
an explicit notice that human migration review is still required — it is
never silently treated as pre-approved. `backend/migrations.py` itself is
excluded from the blanket protected-path list (§2) precisely because it
has this dedicated, nuanced gate instead; blocking the whole file outright
would have been simpler to build but would make every future legitimate
capability that needs schema impossible without a policy override.

V0.3D does not add a new migration. The gates need no storage of their
own — everything they check is either derived from a git diff, parsed
from source text, or read from the live in-memory registry.

## 5. Self-protection: how the policy protects itself

Two independent mechanisms, both required:

1. `scripts/gates/` (including `policy.py` itself) is listed in
   `policy.DENIED_PATHS`. Any diff that edits the policy — including one
   that tries to shrink `DENIED_PATHS` or add an exception under
   `scripts/gates/` — is itself a protected-path violation, caught by the
   same mechanism it would be trying to weaken. A dedicated test asserts
   `"scripts/gates/" in policy.DENIED_PATHS` directly (not just through
   behavior), and a second test asserts `ALLOWED_EXCEPTIONS` can never
   contain a `scripts/gates/` path.
2. **Trusted extraction in CI.** The `protected-core-gates` job does not
   run the gate code from the PR branch's own working tree. It extracts
   `scripts/` from the base ref via `git archive` and runs *that* copy
   (`PYTHONPATH` pointed at the extraction, not the checkout) against the
   PR's diff. Even in the hypothetical case where a diff's own copy of
   `scripts/gates/` was successfully modified to be permissive, that
   modified copy is never the code evaluating that same PR — only a
   future PR, after this one has already been merged by a human, would
   ever run under a changed policy. (The one exception is the PR that
   *introduces* `scripts/gates/` in the first place, where no trusted base
   copy exists yet; the workflow falls back to the branch's own copy for
   that bootstrap case only, with an explicit CI warning marking it as
   such.)

Together: a diff cannot both weaken this policy and have that weakened
policy apply to itself.

## 6. Secret scan: behavior and limitations

`scripts/gates/secret_scan.py` runs two independent, dependency-free
checks against the diff's changed paths:

- **Filename check.** Rejects `.env` (exact name — `.env.example`,
  `.env.sample`, `.env.template` are explicitly allowed template files),
  private-key extensions/prefixes (`.pem`, `.key`, `.p12`, `.pfx`,
  `id_rsa`/`id_ecdsa`/`id_ed25519`), and database files (`.db`, `.sqlite`,
  `.sqlite3`).
- **Content pattern check.** A short list of recognizable secret shapes —
  an AWS-style access key ID, an OpenAI-style `sk-...` key, a PEM private
  key header, or a long literal assigned to an obviously-named variable
  (`API_KEY = "..."`, `SESSION_SECRET = "..."`, etc.) — applied to text
  files under a 200KB cap.

**This is stated plainly, not hedged: this gate cannot prove the absence
of a secret.** It only recognizes shapes it was told to look for. A
bespoke internal token, a secret split across concatenated string
literals, a value assigned through indirection, or anything already
committed to history before this gate existed will not be caught. False
positives (a test fixture or documentation example that happens to match
a pattern) are an accepted, expected cost — the intended fix there is to
make the example clearly non-matching (e.g. `sk-EXAMPLE-NOT-REAL`), not to
weaken the pattern. No paid or third-party secret-scanning service is
used, per V0.3D's constraints; a stronger complementary product (e.g.
GitHub Advanced Security, if ever enabled) would sit alongside this, not
replace it.

## 7. Mechanical gates vs. advisory review vs. human approval

This is a locked rule (ADR-032), and V0.3D does not change it:

- **Mechanical gates may block.** Everything in §3 runs automatically in
  CI and fails the `protected-core-gates` job (and therefore the PR's
  required checks) on a violation.
- **AI review is advisory only.** No model output — including a gate
  script's own text output, if it were ever routed through a model — is
  ever treated as approval. Gates here are plain deterministic scripts;
  none of them is a model call.
- **Only a human controls merge, install, and deploy.** A gate failing
  means "do not auto-merge, this needs a human," never "this can never be
  merged." A gate passing means "no known mechanical violation," never
  "approved."

## 8. What future capability work (V0.3E/V0.4A) can and cannot do here

V0.3D is deliberately built so that adding a new tool module, its tests,
its docs, and its explicit registration entry — the shape V0.3E's manual
pipeline and V0.4A's eventual automation will need — stays possible
without any gate change:

- a new `backend/tools_<name>.py` module — **not** a protected path
- new tests under `tests/` — **not** a protected path
- new docs under `docs/` — **not** a protected path
- a new, additive `backend/migrations.py` entry — passes the migration
  gate with a mandatory human-review notice, not a block

What it still cannot do, by design, without an explicit human-reviewed
change to `scripts/gates/policy.py` itself (which is, in turn, protected —
see §5): touch the executor, the approval state machine, auth, production
routing/deployment configuration, or `backend/tool_registry.py`'s
registration call path. That is intentional — "core registration
authority remains the existing explicit registry/build path" (ADR-031) —
and nothing in V0.3D automates an exception to it. Making that workflow
possible without loosening this boundary is future work (V0.3E onward),
not something this phase implements.

## 9. Enabling enforcement

The `protected-core-gates` CI job runs on every push/PR and reports a
pass/fail check, exactly like the existing `build` job. That alone makes
a failure **visible**; making it actually **block** the merge button is a
one-time GitHub repository setting (Settings → Branches → branch
protection rule for the default branch → "Require status checks to pass
before merging" → select `protected-core-gates`), which a repository
admin must configure — no workflow file can grant that on its own. Until
that setting is turned on, a red `protected-core-gates` check is still a
strong signal a human reviewer should not ignore, but is not yet a
mechanical hard block. This is a deliberate, minimal scope: V0.3D builds
the check; wiring it to branch protection is a one-click repository
administration action, not application code, and is left to whoever
administers `mootmoot1/MootOS`.

## 10. Running the gates locally

```sh
python scripts/gates/run_gates.py --base origin/main --head HEAD
```

Individual gates can also be run and imported directly (each module has
its own `main()`), which is how `tests/test_gates_*.py` exercises them —
mostly through the pure, filesystem-free functions
(`evaluate_changed_paths`, `evaluate_migration_diff`,
`evaluate_files`, etc.) rather than shelling out to git, for speed and
determinism; a smaller set of tests in each file exercises the real
git-backed/live-registry paths against this repository.
