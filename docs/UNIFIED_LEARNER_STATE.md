# Unified learner state and retention

Migration `0033_unified_learner_state` stores one projection per owner, stable concept and capability. `UnifiedLearnerState` is the canonical service for context compilation and user-facing capability summaries. `reduce_capability` is a pure reducer with a frozen revisioned policy. Knowledge, evidence strength and retention are separate outputs.

## Policy and evidence

Effective ledger observations are ordered by occurrence time and ID after corrections. Reviewed stable mappings resolve historical concept IDs without rewriting events. Unresolved links remain visible but cannot establish independent capability performance. The shared taxonomy stays recall/explain/apply/transfer; recognition is not silently treated as transfer.

The proposed demonstration rule requires two families, two sessions, delayed confirmation, and no recent credible contradiction. It is deliberately in shadow mode (`capability-v1-shadow`): `demonstrationCandidate` reports the result, but promotion requires an explicit reviewed policy revision after labeled-history evaluation. There is no manufactured mastery probability or blanket reliability increase. Historical confidence fields remain legacy data.

Assisted success indicates progress; unknown assistance/attribution requests an independent check. Skips and self-report do not become correctness. Same family/session repetitions cannot extend retrieval intervals. Delayed independent retrieval extends the interval within a bounded rule; assisted or failed measurable performance shortens it. Due and stale are views at an explicit `asOf` time and do not erase demonstrated knowledge.

## Integration

Ledger commits rebuild projections in the authoritative transaction with owner fencing and receipt-sequence locking. Corrections and late evidence therefore update history/state/schedules together. Stable concept edits trigger the same rebuild. Context consumers in Ask/Learn/Quiz use `canonical_evidence` backed by this service. The concept detail UI displays capability conditions and uncertainty.

The state service mirrors compatibility labels and review schedule rows from canonical projections, and existing confidence submission cannot independently multiply review intervals once canonical evidence exists. The detailed capability record owns its single due date; old concept-level views aggregate this information. Explicit rebuild and capability-state APIs are owner scoped. Backfill remains conservative and does not mass-promote old successes.

## Remaining rollout gates

No labeled-history calibration or runtime tests were authorized/run. The demonstration gate is intentionally closed until that evidence exists. Feature 12 supplies verified cross-session assistance and reviewed grading admission; legacy Review items without validated rubric lineage are retained as excluded observations. Future readiness/planning must consume this same service rather than invent separate status labels. Hosted concurrency, browser UI and migration application require execution verification before rollout.
