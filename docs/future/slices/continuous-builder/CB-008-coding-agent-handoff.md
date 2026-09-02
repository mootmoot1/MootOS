# CB-008 — Coding-Agent Handoff

**Status:** Designing

## Purpose
Give an approved slice to the existing coding system with only the context required to execute safely.

## Handoff packet
Purpose, approved scope, acceptance criteria, relevant architecture, dependencies, tests, protected/out-of-scope boundaries, current base, and expected evidence.

## Rules
- Tiny directly-related cleanup may be allowed only within explicit budget/policy.
- Unrelated improvements become separate proposals/slices.
- Every handoff records who/what initiated it, why, input spec version, worker identity, and resulting artifact references.

## Acceptance
The same slice can be handed to replaceable workers using a provider-neutral contract and produces an auditable execution record.
