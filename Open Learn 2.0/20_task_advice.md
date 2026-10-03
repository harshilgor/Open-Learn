# Task advice and priority selection

Rank feasible tasks and explain useful next actions from current goals, evidence, deadlines, and learner preferences.

Status: planned. Source: section 21 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Unified learner state and retention](06_learner_state_and_retention.md)
- [Academic model and course fact reconciliation](16_academic_model.md)
- [Executable study task generation](19_task_generation.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/recommendation_service.py](../backend/app/recommendation_service.py)
- [backend/app/recommendation_models.py](../backend/app/recommendation_models.py)
- [backend/app/immediate_adaptation_policy.py](../backend/app/immediate_adaptation_policy.py)
- [web/components/course-home.tsx](../web/components/course-home.tsx)

## Implementation sequence

1. Filter candidate tasks by access, scope, required materials, prerequisite availability, time constraints, and current task state.
2. Implement bounded additive priority contributions for urgency, known importance, gaps, diagnostics, retention, and prerequisite benefit, with repetition and switching penalties.
3. Record reason codes and contribution values; retain uncertainty for unknown importance and distinguish untested capability from observed difficulty.
4. Add dismiss cooldowns and stale-recommendation checks. Hand selected tasks to the control plane and planner without creating another learner-state store.

## Detailed feature requirements

### Division of responsibility

Study planning combines academic obligations, learner needs, and available time. Task generation converts a validated need into an executable activity specification. Task advice ranks eligible activities and explains what is useful next. All three consume the same state; they should not maintain separate copies of learner knowledge or ask models to invent deadlines.

The planner owns schedule feasibility and revisions. The task generator owns concrete activity specifications. The advisor owns priority and recommendation reasons. The control plane launches the selected teaching, quiz, review, or assignment workflow. This division keeps task advice focused while allowing one shared implementation of evidence and context.

### Eligibility and priority

First enforce hard constraints: access, valid scope, prerequisite availability, deadline, user availability, required materials, and active task state. Block tasks whose needed source or connection is unavailable, with a repair action. Do not rank infeasible tasks as immediate recommendations.

Use an interpretable additive score for eligible tasks, with bounded terms for deadline urgency, assessment importance when known, credible gap, uncertainty worth resolving, retention due status, prerequisite benefit, and user preference. Subtract switching cost, recent repetition, and excessive estimated effort. Store each contribution and policy revision. We will not use the earlier multiplicative formula because a zero or unknown factor could erase an otherwise important obligation.

Unknown exam importance uses a neutral documented default and an uncertainty flag. Untested capability can justify a diagnostic, while credible difficulty can justify repair; they should not be the same gap score. Attendance or note presence never fills in a mastery term. Fixed assignments remain obligations even if concept state is strong.

### Replanning and learner control

Trigger a replan after accepted assessment evidence, changed academic facts, completed or skipped tasks, availability edits, or an explicit request. Coalesce rapid events and replan only the affected horizon. Lock the active task and preserve explicitly pinned tasks. Do not move the current lesson halfway through because an unrelated assignment was imported.

Keep a plan revision and a human-readable difference. Automatic adjustment is permitted for unstarted unpinned suggestions under the learner's selected setting. Larger calendar changes or pinned conflicts appear as proposed changes. A dismissed recommendation receives a cooldown; the advisor should not repeat it on every screen.

### Example and completion requirements

A student has 90 minutes before an exam. The advisor recommends a short eigenvector diagnostic because evidence is old. The learner succeeds independently on a distinct family. The generator cancels redundant unstarted eigenvector repair and proposes transfer practice on diagonalization. The planner fits that task alongside a due assignment and explains the revision. The assignment remains scheduled because demonstrated concept ability does not complete the submission.

Test insufficient time, daylight-saving changes, date-only deadlines, active and pinned tasks, skipped practice, changed exams, duplicate events, stale recommendations, and corrected evidence. Completion requires a recommended task to launch the correct workflow, record its outcome, and produce a feasible updated schedule with an understandable reason.

The complete shared planning contract is preserved in [Study planning](21_study_planning.md). Apply its scheduling and completion boundaries when integrating this component.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
