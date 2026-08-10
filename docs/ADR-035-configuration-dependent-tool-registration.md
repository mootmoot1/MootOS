# ADR-035 — A tool that cannot run in this deployment is not registered

## Status

Accepted; implemented on branch
`claude/v0.3c-self-inspection-web-awareness` as part of V0.3C
(`backend/tools_web.py`, `backend/web_connector.py`), pending merge.
Recorded August 2026. See `docs/WEB_AWARENESS.md` §4.

## Context

Every tool registered before V0.3C operated purely on MootOS's own local
state, so "implemented" and "able to run" were the same thing. `web.search`
is the first tool whose ability to function depends on **deployment
configuration** — it needs an external search service credential
(`MOOTOS_SEARCH_API_KEY`) that a given MootOS deployment may simply not
have.

That creates a case the existing rules did not cover. ADR-028/ADR-029 and
`docs/CAPABILITY_ARCHITECTURE.md` §6 establish that the Tool Registry is
the single source of truth for what MootOS can do, and that missing
capabilities must never be represented as registered tools. But they were
written about capabilities that *do not exist in code*. A capability that
exists in code yet cannot execute in this environment is a third state.

Two options:

1. **Always register; fail at call time.** The generated V0.3A manifest
   would tell the model "you can search the web," V0.3B would resolve
   `web.current_information` as installed, and the user would be told the
   goal is already possible — and then every actual attempt would fail.
2. **Register only when configured.**

Option 1 reintroduces exactly the class of dishonesty this architecture
exists to eliminate, just relocated: instead of hand-written prose
overclaiming (the ADR-029 problem), the registry itself would overclaim.

## Decision

**A tool whose external dependency is not configured in this deployment is
not registered.**

`backend/tools_web.py`'s `register_v03c_tools` registers `web.search` only
when `backend.web_connector.is_configured()` is true. Self-inspection
tools, which depend only on in-process state and documents that ship with
MootOS, always register.

Consequences follow automatically from the existing architecture, with no
new bookkeeping:

- the V0.3A catalog, generated manifest, and
  `describe_installed_abilities()` omit it;
- V0.3B's `analyze_goal()` resolves `web.current_information` as
  **missing**, correctly classifying a current-information goal as a
  `capability_gap`;
- self-inspection's `self.state` reports it as not installed.

Registration remains explicit and by direct reference. This is a
compile-time-known tool with a runtime-evaluated *condition* — it is not
plugin discovery, filesystem scanning, or any mechanism by which a model
or request could cause a tool to be registered.

## Consequences

### Positive

- MootOS never advertises a capability that would fail on first use. The
  registry stays a truthful description of what can *actually happen*, not
  merely what has been coded.
- The honest answer arrives at the right layer: gap reasoning reports a
  genuine `capability_gap` (with a real, closeable cause — "configure a
  search service") rather than the model discovering the problem by
  failing mid-task.
- Costs nothing to maintain: every downstream surface derives from the
  registry, so both configurations are correct by construction.

### Tradeoffs

- The registry's contents are now environment-dependent, so "what tools
  exist?" has a per-deployment answer. Tests must assert both
  configurations rather than one fixed set —
  `tests/test_tool_registry.py` does exactly that, checking the exact
  expected set with and without a key so an accidentally registered tool
  still fails.
- A misconfigured deployment (key present but invalid) still registers the
  tool and fails at call time, sanitized. Distinguishing "configured" from
  "working" would require a live probe at startup, which is not worth the
  startup dependency for a private single-user system; the failure path is
  already safe and honest.
- This ADR governs external-dependency configuration only. It is not a
  license to make registration conditional on arbitrary runtime state —
  each future case needs the same explicit justification.

## Follow-on direction

`docs/WEB_AWARENESS.md` §4 documents the concrete behavior. If MootOS
later gains several externally-dependent connectors, the shared
`is_configured()`-style check may be worth factoring — but per
`docs/CAPABILITY_ARCHITECTURE.md` §9, not before 2-3 concrete connectors
exist to generalize from.
