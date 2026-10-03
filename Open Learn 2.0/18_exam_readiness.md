# Exam readiness and evidence reports

Explain readiness for a defined assessment scope using capability evidence, retention, and uncertainty.

Status: planned. Source: section 20 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Unified learner state and retention](06_learner_state_and_retention.md)
- [Shared context compiler](09_shared_context_compiler.md)
- [Academic model and course fact reconciliation](16_academic_model.md)
- [Adaptive quiz planning and question generation](11_adaptive_quiz_planning.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/recommendation_service.py](../backend/app/recommendation_service.py)
- [backend/app/course_routes.py](../backend/app/course_routes.py)
- [backend/app/state_service.py](../backend/app/state_service.py)
- [web/components/course-home.tsx](../web/components/course-home.tsx)

## Implementation sequence

1. Create immutable readiness snapshots tied to assessment scope, learner projection, and source revisions.
2. Classify capability evidence as strong, developing, assisted-only, untested, stale, or conflicting without implying a predicted grade.
3. Select a small set of useful diagnostics and expose supporting attempts and uncertain scope.
4. Connect diagnostic launches and accepted outcomes to refreshed readiness and planning.

## Detailed feature requirements

### Purpose and inputs

Readiness compares assessment scope with the learner's measured capabilities. It is an evidence report, not a predicted exam grade. Inputs are the assessment scope and its certainty, required course outcomes, learner projections, rubric and question validity, retention dates, and unresolved hypotheses.

The service builds a ReadinessSnapshot with assessment revision, scope basis, concept-capability coverage, evidence category, source references, unknown scope, and recommended diagnostics. This snapshot is immutable for explanation; a new result or changed scope creates a newer snapshot.

### Classification

Use categories with clear meanings. Strong evidence requires appropriate independent capability evidence. Developing has valid evidence of partial ability or difficulty. Assisted only means success has not yet been independently verified. Untested means no suitable observation exists. Stale means formerly useful evidence needs retrieval confirmation. Conflicting means credible observations disagree.

These are dimensions, not necessarily mutually exclusive labels. A concept may be procedurally demonstrated with stale recall and untested transfer. Show the capability that matters for the assessment format. Do not assign transfer readiness from recognition evidence. Inferred exam topics remain visibly separate from confirmed scope.

### Recommendations and UI

Select a small set of checks that addresses high-impact unknowns or stale evidence. A diagnostic on diagonalization may be more useful than another routine determinant problem if determinants already have recent independent evidence. Explain the choice with a brief source-backed reason.

The report shows scope, evidence categories, supporting attempts, what has not been tested, and uncertainty about the exam itself. Let the learner update scope and launch a diagnostic. If the syllabus is missing, the result must describe readiness for the supplied topics rather than readiness for the entire exam.

### Completion requirements

Test strong procedural but absent transfer evidence, unknown scope, stale recall, assisted-only history, corrected questions, and changed exam dates. Completion requires a readiness recommendation to launch an assessment, update shared evidence, and refresh the report and study plan.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
