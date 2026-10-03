# Existing data migration and cutover

Bring existing learners and activities into the shared architecture without losing history or inventing stronger evidence.

Status: planned. Source: section 25 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Shared data contracts and architecture decisions](02_shared_data_contracts.md)
- [Identity authorization and device synchronization](03_identity_and_device_sync.md)
- [Evidence ledger and reversible observations](04_evidence_ledger.md)
- [Stable concepts and course mappings](05_stable_concepts.md)
- [Unified learner state and retention](06_learner_state_and_retention.md)
- [Source evidence and derived memory](08_source_memory.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/migrations](../backend/migrations)
- [backend/app/backup_service.py](../backend/app/backup_service.py)
- [backend/app/state_service.py](../backend/app/state_service.py)
- [backend/app/workflow_store.py](../backend/app/workflow_store.py)
- [backend/app/workspace_note_service.py](../backend/app/workspace_note_service.py)

## Implementation sequence

1. Inventory entities, ownership, hashes, and relationships; establish explicit account and legacy-concept mappings.
2. Backfill normalized events idempotently from authoritative attempts. Keep unknown assistance and missing rubrics conservative.
3. Run new projections in shadow mode, inspect differences, and reconcile record counts and source revisions.
4. Switch canonical writes and all workflow readers together at the defined gates; retain rollback compatibility and produce an operator-readable migration report.

## Detailed feature requirements

### Inventory and mapping

Create a migration report for courses, graph revisions, sessions, lessons, notes, quizzes, question presentations, attempts, review records, recordings, and local owner profiles. Count records and relationships before and after migration. Preserve original timestamps and source IDs wherever possible.

Add stable concept mappings and account ownership mappings before rebuilding learner projections. Use explicit per-record transformations with migration revision and provenance. A historical attempt with missing assistance metadata is independence unknown; do not assume independent because a hint field is absent. A historical score with no rubric remains limited evidence rather than being converted into a modern rubric evaluation.

### Backfill and comparison

Backfill ledger events from authoritative attempts with a deterministic migration key. Re-running the backfill must not duplicate events. Existing review histories can contribute recall observations only when their underlying event is sufficiently interpretable. Keep schedule metadata as historical scheduling information when it is not learning evidence.

Run new projections in shadow mode alongside existing reads. Compare state differences and inspect representative divergences, especially the reliability mismatch, repeated same-family practice, contested items, and assisted success. Shadow operation is an engineering migration safeguard, not a separate product version or permission to leave the feature incomplete.

### Cutover

Make the command path write the canonical attempt and ledger transaction together. If temporary compatibility fields must still be written, derive them from that canonical transaction rather than running two competing reducers. Switch Ask, Learn, Quiz, review, readiness, and planning readers to shared state only after reconciliation and regression tests pass.

Retain historical quiz snapshots and note revisions. Reindex source content with ownership and current revision filters. Invalid or ambiguous old mappings are surfaced for review or left conservatively unresolved. Do not force every old record into a more precise new category than its stored data supports.

### Completion requirements

Verify counts, foreign-key relationships, checksums, idempotent reruns, uninterrupted existing quizzes, note revision safety, recording recovery, and local account linking. Produce an operator-readable migration summary. Completion requires existing users to retain their histories and resume their activities while receiving the new shared behavior.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
