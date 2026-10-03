# Unified learner state and retention

Give every workflow the same capability state, evidence strength, and retention status derived from accepted observations.

Status: Implemented in the workspace; demonstrated promotion remains gated pending labeled calibration and further grading integration acceptance. See [verified coverage and remaining acceptance](LEARNING_WORKFLOWS_IMPLEMENTATION_STATUS.md). Source: section 8 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Evidence ledger and reversible observations](04_evidence_ledger.md)
- [Stable concepts and course mappings](05_stable_concepts.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/state_service.py](../backend/app/state_service.py)
- [backend/app/context_service.py](../backend/app/context_service.py)
- [backend/app/review/memory.py](../backend/app/review/memory.py)
- [backend/app/review/scheduler.py](../backend/app/review/scheduler.py)
- [backend/app/review/scheduling_authority.py](../backend/app/review/scheduling_authority.py)

## Implementation sequence

1. Implement a pure revisioned reducer over the effective event set, grouping question families and exposure lineage across sessions.
2. Define separate capability, evidence-strength, and retention dimensions. Validate proposed demonstration rules against labeled histories before enabling them.
3. Replace the fixed reliability-threshold mismatch with meaningful validity and assistance admission rules; retain legacy uncertainty during migration.
4. Make review scheduling consume the shared projection and delayed independent recall. Prevent retries from multiplying intervals.
5. Expose contributing attempts and reasons in concept details, and compare shadow projections before switching all readers.

## Detailed feature requirements

### What we represent

Replace competing quiz, review, and teaching labels with one canonical projection over accepted evidence. Review scheduling reads that state and contributes new recall observations; it does not maintain a second definition of mastery. We will preserve useful historical counts while making every displayed category explainable.

Track capabilities such as recognition, recall, explanation, procedural execution, and transfer within each concept. These capabilities prevent an easy recognition question from becoming evidence of transfer. Store independent and assisted outcomes, distinct question families, observation dates, conflicting recent evidence, unresolved hypotheses, and a source-backed explanation of the current state.

Knowledge status, evidence strength, and retention are separate fields. Status can be unknown, developing, or demonstrated for the measured capability. Evidence strength can be insufficient, limited, supported, or conflicting. Retention can be unmeasured, recently recalled, review due, or stale. A demonstrated capability can still have stale retrieval evidence.

### Deterministic projection algorithm

First select effective events after corrections and exclusions. Group attempts by exposure lineage, question family, and session context. Mark independence conservatively when the answer or worked solution has already been revealed, including in an earlier session. Merely changing numbers does not create a new question family. Assistance policy determines which disclosed material compromises which capability.

Then summarize rubric-level outcomes for each capability. Use valid independent successes and failures as the primary signal. Assisted outcomes indicate progress and the need for an independent check. Exposure events supply teaching history only. An uncertain grade supplies an uncertainty flag until adjudicated.

Use an explicit rule table rather than the current latest-event shortcut. A proposed acceptance rule for demonstrated procedural capability requires successful independent outcomes on at least two materially distinct question families, at least one later-session confirmation, and no unresolved recent contradiction of comparable quality. These are operational policy conditions to validate with the evaluation harness, not a calibrated probability of knowledge. Recognition and transfer have their own evidence requirements.

Repeated credible independent failures can mark developing and create a repair need. A single ambiguous failure can set conflicting evidence and request diagnosis without erasing a substantial history of success. Store the contributing event IDs and reason codes. All thresholds, recent windows, and family requirements live in one revisioned configuration with tests. Changing them triggers an explicit rebuild and comparison.

### Evidence quality and current reliability mismatch

Do not fix the current 0.4 versus 0.5 mismatch by increasing every quiz reliability number. Replace that admission mismatch with meaningful quality checks: valid question, validated rubric, trustworthy source basis, determinate grading, recorded assistance, and measurable capability. Preserve legacy reliability and uncalibrated labels for historical interpretation.

Legacy successes can support a limited-evidence state until the new checks establish stronger evidence. Avoid mass-promoting users based on migrated labels. The interface can say that a concept has previous practice history but needs a fresh independent check. That is preferable to inventing precision during migration.

### Retention scheduling

Maintain one review schedule per learner, concept, and relevant capability. Store last independent retrieval, interval, due time, distinct retrieval count, and recent failure or assistance. Successful delayed independent retrieval extends an interval under a bounded rule; failed or assisted retrieval shortens it. Same-session retries do not multiply the interval. Skips do not become failures.

Use existing scheduling behavior as a measured baseline and express updated constants in one policy. Do not claim a fitted forgetting curve without data. Keep retention risk as a scheduling estimate and never automatically rewrite demonstrated status merely because a due date passed. When evidence is old, readiness reports staleness and the planner proposes a check.

### UI and completion requirements

Show what has been demonstrated, under what conditions, how recently, and what remains untested. Students can open the supporting attempts, request a diagnostic, or report incorrect attribution. Test repeated same-family answers, solution exposure in another session, mixed independent and assisted results, corrected grades, delayed recall, and out-of-order evidence. Ask, Learn, Quiz, review, readiness, and planning must return the same state for the same projection revision.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
