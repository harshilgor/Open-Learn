# Grading assistance and disputed questions

Evaluate answers fairly, preserve assistance history across workflows, and repair every dependent decision after a question correction.

Status: planned. Source: section 14 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Evidence ledger and reversible observations](04_evidence_ledger.md)
- [Unified learner state and retention](06_learner_state_and_retention.md)
- [Source evidence and derived memory](08_source_memory.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/assessment_lifecycle.py](../backend/app/assessment_lifecycle.py)
- [backend/app/assessment_generation.py](../backend/app/assessment_generation.py)
- [backend/app/assessment_models.py](../backend/app/assessment_models.py)
- [backend/app/quiz_service.py](../backend/app/quiz_service.py)
- [web/components/assessment-card.tsx](../web/components/assessment-card.tsx)

## Implementation sequence

1. Extend written evaluation with rubric outcomes, valid response spans, uncertainty, and capability attribution; retain private answer keys.
2. Record hint levels, answer reveals, worked solutions, retries, and exposure lineage across sessions.
3. Implement challenge suspension and adjudication outcomes: uphold, regrade, invalidate, or replace.
4. Append corrections and rebuild affected state, schedules, readiness, and eligible plan tasks; show resolution to the learner.

## Detailed feature requirements

### Reliable evaluation

Choice responses use the validated private key. Written responses use explicit weighted rubric criteria, acceptable equivalent reasoning, and evidence spans in the student response. Supported numerical equivalence can use deterministic validators. Open-ended grading returns criterion outcomes, a score only when justified, uncertainty, feedback, and concept attribution.

Reject a grader output that cites nonexistent text or contradicts its own rubric. If the answer is ambiguous or the model cannot resolve equivalence, use an uncertain evaluation and request clarification or adjudication. Preserve the attempt without admitting definitive learning evidence. A provider failure must not become an incorrect answer.

### Assistance and exposure lineage

Track hint level, answer reveal, worked examples, feedback exposure, retries, and closely repeated items. Distinguish independent submission from an answer reconstructed after feedback. A retry can show progress but cannot erase the original failure or supply another independent observation for the same exposed item.

Shared exposure records prevent a question seen with its answer in Learn from later appearing as a clean independent quiz check. External help cannot always be detected; allow learner disclosure and report the limits of observed independence without claiming surveillance-based certainty.

### Challenges and repair

A challenge immediately suspends scoring and learner-state impact for the contested item. Revalidate against sources, rubric, deterministic checks, and independent adjudication. The result can uphold, regrade, invalidate, or replace. Replacement questions are separate presentations; retain the challenged history and preserve user effort.

When an item is invalidated, append correction events and recompute affected state, review scheduling, readiness, and unstarted plan tasks. Notify the student of the result in ordinary language. Do not require the student to repeat an invalid question for their evidence to be repaired.

### Completion requirements

Test alternate valid written solutions, uncertain grading, hints before submission, feedback-assisted retry, solution exposure across sessions, and challenge reversal. Completion means a disputed question can be resolved without leaving incorrect mastery or review state behind.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
