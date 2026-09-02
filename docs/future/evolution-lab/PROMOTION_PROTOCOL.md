# Evolution Lab Promotion Protocol

## Goal

Turn genuinely strong lab discoveries into clean production work without importing lab chaos.

## Promotion classes

- **Promote now:** unusually high-value, validated, architecture-compatible discovery worth temporarily interrupting the roadmap.
- **Save for later:** useful but not worth current interruption.
- **Reject:** unreliable, redundant, architecturally poor, insecure, or too expensive.

## Promotion package

A harvest may bundle many related discoveries. Example: a 1,000-slice lab run discovers 50 production-worthy capabilities. The system should prepare one strategic package describing:

- capabilities discovered;
- why they matter;
- evidence from the lab;
- which are cleanly reusable versus should be reimplemented;
- dependencies;
- production risks;
- estimated production slice count/time;
- what current roadmap work would pause;
- exact resume point after promotion;
- recommendation.

## Human interrupt gate

The package does not alter production priority until Moot approves it.

After approval, Chief Builder finishes any unsafe-to-interrupt active work, inserts the promoted production slices, integrates/verifies them through normal production gates, then returns to the saved roadmap position.

## Interrupt threshold

Do not interrupt for minor novelty. A promotion should represent a major capability unlock, substantial reliability gain, large time/revenue advantage, or discovery that makes significant planned work obsolete.

## Code handling

Lab code is evidence, not automatically production code. The production builder may:

- cherry-pick a clean component after review;
- adapt it;
- or reimplement the capability cleanly using the lab's proven design.
