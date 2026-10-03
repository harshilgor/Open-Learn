# Adaptive quiz planning and question generation

Choose a measurable objective before authoring each question and adapt practice within the learner’s agreed scope.

Status: Implemented with stable task-scope mapping and QuestionPlan traces; course-level prerequisite selection and supported numeric symbolic validation still need acceptance. See [verified coverage and remaining acceptance](LEARNING_WORKFLOWS_IMPLEMENTATION_STATUS.md). Source: section 13 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Unified learner state and retention](06_learner_state_and_retention.md)
- [Misconception hypotheses and diagnostic checks](07_misconception_hypotheses.md)
- [Shared context compiler](09_shared_context_compiler.md)
- [Learning control plane and workflow integration](10_learning_control_plane.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/quiz_service.py](../backend/app/quiz_service.py)
- [backend/app/assessment_models.py](../backend/app/assessment_models.py)
- [backend/app/assessment_context_planner.py](../backend/app/assessment_context_planner.py)
- [backend/app/assessment_generation.py](../backend/app/assessment_generation.py)
- [web/components/quiz-workspace.tsx](../web/components/quiz-workspace.tsx)

## Implementation sequence

1. Introduce QuestionPlan with capability, target, diagnostic distinction, source revisions, response type, family constraints, and acceptance criteria.
2. Implement bounded objective selection for diagnostics, independent verification, due retrieval, missing coverage, and extension practice.
3. Track coverage quotas and remaining items; preserve scope snapshots while reading newly accepted learner evidence.
4. Feed plans into the existing author/checker pipeline with source, family, rubric, and deterministic validation.
5. Reuse response components and expose scope, progress, hints, skip, challenge, and short objective explanations.

## Detailed feature requirements

### Objective before wording

The adaptive planner selects what capability to measure and why before calling the existing author. It receives quiz scope, course expectations, learner state, hypothesis candidates, retention schedule, previous families, time limits, and current activity progress. Its output is a QuestionPlan, not an authored question.

A QuestionPlan includes target concepts and capability, objective, relevant prerequisite, requested complexity, response type, source revisions, assistance rules, diagnostic distinction if any, estimated duration, family constraints, and acceptance criteria. Estimated duration is a planning aid, not an ability inference from speed.

### Selection policy

Honor the learner's explicit scope first. Reject invalid targets and prerequisites outside the agreed course level. Resolve question-quality failures before interpreting them as learner failures. Among eligible objectives, prioritize a necessary prerequisite diagnostic when credible distinct failures suggest a blocking issue, then a distinguishing check for a consequential unresolved misconception, then independent verification after assisted performance, then due retrieval, missing capability evidence, and suitable extension practice.

This order is a policy with reason codes, not an unconditional chain of if statements. Limit consecutive diagnostics so the quiz still covers its requested topic. Add coverage quotas and avoid repeating a recently tested family. A known strong prerequisite does not need another check merely because it appears in the graph. When all selected capabilities have adequate recent evidence, offer transfer or finish rather than manufacture more uncertainty.

For a fixed-length quiz, track remaining items and reserve enough coverage to avoid spending every question on one weakness. For an open practice session, stop according to the student's time or objective and give a concise result. Do not inflate the score by replacing difficult unanswered items with easy retries.

### Authoring and checking

Pass the validated QuestionPlan and context packet into the existing generation pipeline. The author returns structured content, private key, solution, rubric criteria, progressive hints, target mappings, source references, family metadata, and the predicted distinguishing outcomes for a diagnostic.

Apply deterministic schema and ownership checks, duplicate-option checks, answer-leakage checks, source-span validation, and rubric completeness checks. Where appropriate, use controlled numerical or symbolic verification for supported problem types. Do not execute arbitrary model-generated code. A separate checker solves without the author's key, then compares its result and reasoning with the author under a structured verifier.

The current three-authoring-attempt ceiling can remain a bounded configuration. Record repair reasons. If attempts are exhausted, show a retryable generation failure and retain quiz progress. Never show an unchecked item merely to finish the requested count. Same-model checking reduces some mistakes but has correlated failure risk; source and deterministic checks remain necessary.

### Sources and freshness

Prefer primary course materials for course-specific claims. If only a generated lesson is available, label the question basis appropriately and restrict strong evidence admission until validity is sufficiently established. An author/checker agreement on an incorrect generated lesson cannot independently verify that lesson.

Question family assignment examines reasoning structure and supplied solution, not just surface wording. A numerical substitution belongs to the same family; a materially different transfer context may form another. Store requested complexity separately from any later observed item difficulty. Learner data must never be used to label an item's difficulty during evaluation without recording the method and population.

### Interface and completion requirements

Retain the existing single-choice, multiple-choice, and written response components. Show the quiz's scope, progress, hint affordance, skip, I do not know, and challenge controls. A short explanation such as checking independent recall can appear without exposing an answer. Test this week's lecture scope, assisted-to-independent follow-up, prerequisite isolation, coverage quotas, repeated families, and source failure. Completion requires each question's objective to be recoverable from its decision trace.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
