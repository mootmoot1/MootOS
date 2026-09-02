# MootOS Evolution Lab / Jarvis Lab

## Purpose

Run serious, disposable autonomous-build experiments far ahead of production MootOS. This is not a toy demo. A lab run may receive hundreds to roughly 1,000 well-specified slices and be allowed to build/merge aggressively inside a disposable repo for days.

Candidate workers include Claude Code and Codex. The same blueprint may be run independently through multiple workers for comparison.

## Hard boundary

Nothing in an Evolution Lab repo is production authority. Lab success never directly changes `main`.

## Required lab evidence

Every run should preserve:

- starting blueprint version and base commit;
- ordered slice attempts;
- commits/merges;
- tests and regressions;
- architecture decisions;
- deviations from the blueprint;
- retries/workarounds;
- model/tool/provider usage;
- failure points;
- cost and elapsed time where available;
- checkpoints sufficient to resume after crashes/session limits.

## Questions the lab answers

- How far can an agent build before architecture drifts?
- Which slices work surprisingly well autonomously?
- Which abstractions fail under scale?
- Where does the worker begin patching around earlier mistakes?
- Which model/tool combination is strongest for which work?
- Which components or ideas deserve promotion into production planning?

## Multi-run comparison

A strong experiment runs the same blueprint independently through Claude and Codex, then compares correctness, test health, architectural cleanliness, cost, throughput, and intervention requirements.
