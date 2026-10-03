# Evidence ledger and reversible observations

Record one normalized history of observations across teaching, quizzes, review, and lecture coverage while preserving original attempts.

Status: planned. Source: section 6 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Shared data contracts and architecture decisions](02_shared_data_contracts.md)
- [Identity authorization and device synchronization](03_identity_and_device_sync.md)
- [Stable concepts and course mappings](05_stable_concepts.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/assessment_lifecycle.py](../backend/app/assessment_lifecycle.py)
- [backend/app/state_service.py](../backend/app/state_service.py)
- [backend/app/state_models.py](../backend/app/state_models.py)
- [backend/app/workflow_store.py](../backend/app/workflow_store.py)
- [backend/app/review/session_service.py](../backend/app/review/session_service.py)

## Implementation sequence

1. Add the shared record_learning_event service with event identity, concept-capability links, source references, admission reasons, and deduplication keys.
2. Integrate it into the short answer-commit transaction together with the attempt, accepted evaluation, projection update, and quiz progress.
3. Emit exposure, assistance, coverage, and self-report events separately from scored evidence. Backfill legacy events with deterministic migration keys.
4. Implement correction and retraction events, deterministic replay, event watermarks, and concept history UI. Verify late events and duplicate delivery produce the same effective state.

## Detailed feature requirements

### What changes and why

Existing attempts and review records contain useful evidence, but different workflows interpret them separately. The ledger provides one durable account of what happened and why it affects state. It lets Learn use a result from Quiz and lets readiness explain the observations behind its categories.

Add a record_learning_event service above existing storage. Quiz attempts remain the original observations. The ledger links to them and stores a normalized interpretation rather than copying every field into a second competing attempt table. Teaching, review, recording, and course ingestion emit different observation types with distinct admission rules.

### Event structure and admission

Every event includes event ID, owner, course if known, session or activity, type, occurrence and receipt times, source revision, observation payload, schema revision, origin command, and deduplication key. Concept links specify the measured capability, whether the concept is the main target or a prerequisite, and the attribution basis.

QUIZ_RESPONSE and REVIEW_RESPONSE can support understanding when validly graded. HINT_REQUESTED, ANSWER_EXPOSED, and RETRY_SUBMITTED describe assistance. CONCEPT_TAUGHT and LESSON_VIEWED describe exposure. LECTURE_CONCEPT_OBSERVED describes coverage. SOURCE_CORRECTED and EVIDENCE_RETRACTED change validity. A skip records workflow behavior but supplies no correctness observation. Self-reported confidence is preserved separately from demonstrated performance.

Require a matching presented question, rubric, and assistance record before admitting an assessment event. Exclude challenged items, ambiguous grading, corrupt sources, and incomplete evaluations from mastery updates until resolved. Preserve the exclusion reason so the student can see why an attempt is awaiting evaluation.

### Atomic write path

For an answer command, verify identity and current question state, resolve its idempotency key, validate the response, and grade outside a long-running database transaction. Commit the attempt, accepted evaluation, assistance attribution, learning event, learner projection update, and quiz progress in one short transaction using the expected activity revision.

If another command changes the activity meanwhile, reconcile against the immutable attempt identity and current activity state. Never grade a student's response against a newly generated replacement question. If the provider call times out after evaluation, a retry must reuse the durable evaluation if already saved rather than create another learning observation.

### Corrections and replay

A challenge can invalidate a question or change an evaluation. Append a correction referencing the prior evaluation and recompute affected concept projections from the effective event set. Recalculate review due dates, readiness, and pending plan recommendations. Notify the learner when a correction changes their result. Preserve the original presentation and evaluation for explanation.

Replay orders events by meaningful occurrence time with a stable event-ID tie-breaker, while projection checkpoints track accepted server sequence. Late-arriving offline evidence triggers recomputation for affected concepts. The reducer must produce the same result from the same effective events and policy revision regardless of arrival order.

### Interface and completion requirements

A concept detail view shows independent successes, assisted successes, failures, excluded attempts, dates, and links to the question or transcript. Test duplicate delivery, partial failure, challenge reversal, late offline events, and full projection rebuild. Ledger completion requires all selected workflows to emit the correct event category and a replay to reproduce the displayed state.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
