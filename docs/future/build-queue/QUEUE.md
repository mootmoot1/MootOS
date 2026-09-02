# MootOS Build Queue

**Purpose:** machine-readable-in-spirit source of truth for future build ordering. This file is planning only until the Continuous Builder exists.

## States

`idea`, `researching`, `designing`, `ready`, `scheduled`, `building`, `blocked`, `reviewing`, `changes_requested`, `staging`, `testing`, `ready_for_main`, `done`, `paused`, `superseded`, `retired`, `cancelled`.

Every queue item must store a reason for its state.

## Bootstrap queue

Current code work remains governed by the existing V0.4 pipeline. The future queue begins after the current V0.4C checkpoint is reconciled.

| Future slice | State | Priority | Reason |
| --- | --- | --- | --- |
| CB-001 Chief Builder Foundation | designing | P0 | Foundation for all later continuous orchestration |
| CB-002 Project State Engine | designing | P0 | Gives the Chief Builder durable work-state truth |
| CB-003 Dependency Graph Engine | designing | P0 | Prevents naive linear builds and enables safe parallelism |
| CB-004 Priority Engine | designing | P0 | Chooses highest-value Ready work |
| CB-005 Outcome Feedback Loop | designing | P1 | Turns shipped outcomes into future decisions |
| CB-006 Parallel Work/Conflict Engine | designing | P0 | Allows safe specialist concurrency |
| CB-007 Human Approval/Review Experience | designing | P0 | Keeps Moot in control without raw-code overload |
| CB-008 Coding-Agent Handoff | designing | P0 | Connects Chief Builder to existing coding machinery |
| CB-009 Change Proposal System | designing | P1 | Prevents silent architecture changes |
| CB-010 Rollback Framework | designing | P0 | Required before increasing autonomy |
| CB-011 Builder Health Center | designing | P1 | Visibility without micromanagement |
| CB-012 Execution Supervisor | designing | P1 | Intervene by exception |
| CB-013 Build Progress Intelligence | designing | P2 | ETA/stall/confidence visibility |
| CB-014 Engineering Learning Engine | designing | P1 | Living engineering playbook |
| CB-015 Specialist Evaluation/Evolution | designing | P1 | Evidence-based model/tool replacement |
| CB-016 Relationship Capability Prototype | designing | P2 | Early external-service proving ground |
| CB-017 Technology Intelligence | designing | P2 | Weekly top-five opportunity briefing |
| CB-018 Strategic Self-Improvement | designing | P1 | Bottleneck/debt/gap detection |
| CB-019 Portfolio/Multi-Project Strategy | designing | P1 | Global project prioritization |
| CB-020 Decision Intelligence/Simulation | designing | P1 | What-if, challenge, rehearsal, counterfactuals |

## Ready-queue policy

Long term, target roughly 30–40 genuinely Ready slices at a time. Hundreds may exist farther out, but only dependency-clean, sufficiently specified work should be Ready.
