# Executable study task generation

Convert a validated learning need or academic obligation into a concrete task with a launch destination and completion rule.

Status: planned. Source: section 21 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Shared data contracts and architecture decisions](02_shared_data_contracts.md)
- [Unified learner state and retention](06_learner_state_and_retention.md)
- [Learning control plane and workflow integration](10_learning_control_plane.md)
- [Academic model and course fact reconciliation](16_academic_model.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/recommendation_models.py](../backend/app/recommendation_models.py)
- [backend/app/recommendation_service.py](../backend/app/recommendation_service.py)
- [web/lib/learning-workflows.ts](../web/lib/learning-workflows.ts)
- [web/components/course-home.tsx](../web/components/course-home.tsx)

## Implementation sequence

1. Define TaskSpec with source need, course, target capabilities, action, duration range, prerequisites, completion criterion, launch descriptor, and state revision.
2. Create deterministic task templates for diagnostics, repair, retrieval, transfer, and assignment work; deduplicate by need and policy revision.
3. Implement allowed task transitions and link launch IDs to canonical activities. Observe their completion without inferring mastery from administrative completion.
4. Expose accept, launch, skip, cancel, and blocked-repair controls; consume corrected evidence to retire redundant unstarted tasks.

## Detailed feature requirements

### Division of responsibility

Study planning combines academic obligations, learner needs, and available time. Task generation converts a validated need into an executable activity specification. Task advice ranks eligible activities and explains what is useful next. All three consume the same state; they should not maintain separate copies of learner knowledge or ask models to invent deadlines.

The planner owns schedule feasibility and revisions. The task generator owns concrete activity specifications. The advisor owns priority and recommendation reasons. The control plane launches the selected teaching, quiz, review, or assignment workflow. This division keeps task advice focused while allowing one shared implementation of evidence and context.

### Task specification

A task stores owner, goal, course, assessment or assignment reference, target concepts and capability, action type, reason, source basis, estimated duration range, prerequisite task references, completion criterion, launch descriptor, and current status. Status is proposed, accepted, scheduled, active, completed, skipped, cancelled, or blocked.

Generate tasks such as an eight-minute independent eigenvector diagnostic, a worked example targeting null-space setup, a due retrieval check, or a time block for a specific assignment. The action must have a launch destination and completion criterion. A vague task such as study linear algebra is insufficient when the system can identify the actual need.

Task completion and demonstrated mastery remain distinct. Completing a lesson means the activity ended; its follow-up assessment determines learning evidence. For homework outside OpenLearn, explicit student completion can close the administrative task without asserting that every related concept was mastered.

### Example and completion requirements

A student has 90 minutes before an exam. The advisor recommends a short eigenvector diagnostic because evidence is old. The learner succeeds independently on a distinct family. The generator cancels redundant unstarted eigenvector repair and proposes transfer practice on diagonalization. The planner fits that task alongside a due assignment and explains the revision. The assignment remains scheduled because demonstrated concept ability does not complete the submission.

Test insufficient time, daylight-saving changes, date-only deadlines, active and pinned tasks, skipped practice, changed exams, duplicate events, stale recommendations, and corrected evidence. Completion requires a recommended task to launch the correct workflow, record its outcome, and produce a feasible updated schedule with an understandable reason.

The complete shared planning contract is preserved in [Study planning](21_study_planning.md). Apply its scheduling and completion boundaries when integrating this component.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
