# Learning control plane and workflow integration

Coordinate learner intent, shared context, policy decisions, generation, and resulting evidence across Ask, Learn, and Quiz.

Status: planned. Source: section 12 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Unified learner state and retention](06_learner_state_and_retention.md)
- [Shared context compiler](09_shared_context_compiler.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/generation_service.py](../backend/app/generation_service.py)
- [backend/app/journey_service.py](../backend/app/journey_service.py)
- [backend/app/mode_transition_service.py](../backend/app/mode_transition_service.py)
- [backend/app/recommendation_service.py](../backend/app/recommendation_service.py)
- [web/components/learn-chat.tsx](../web/components/learn-chat.tsx)
- [web/components/learning-workspace.tsx](../web/components/learning-workspace.tsx)

## Implementation sequence

1. Create typed teaching and assessment decision records with reason codes, source/state revisions, constraints, and optional confirmation.
2. Route existing workflows through shared decisions while retaining separate workflow and teaching-gear controls.
3. Integrate policy preparation with the existing streaming lifecycle; publish assessments only after validation and checking.
4. Preserve cancellation, reconnect, note approval, and canonical completion semantics. Expose concise reasons and honor declined diagnostics.

## Detailed feature requirements

### Responsibility

The control plane coordinates the request, context, selected action, execution, and resulting evidence. It is an ordinary service with typed decisions, not a collection of autonomous teacher and quiz agents. It never owns a competing learner state.

A TeachingDecision or AssessmentDecision stores target, selected action, reason codes, scope, required context, constraints, evidence basis, optional learner confirmation, and revision references. Policies choose the action; the model generates content within that action. Explicit learner requests retain priority. A student asking for a direct explanation can decline a suggested prerequisite diagnostic.

### Ask Learn Quiz and teaching gear

Keep Ask, Learn, and Quiz as product workflows. Keep Quick, Guided, and Deep as explanation controls. Depth affects presentation and limits; it does not automatically increase quiz difficulty or require a longer answer. The existing classification suggestion remains a proposal to switch workflow, with a clear accept and cancel interaction. Classification of intent is separate from assessment of knowledge.

Ask answers the requested question while retrieving relevant shared context. Learn maintains a route and lesson note, chooses a useful intervention, and records what was delivered. Quiz maintains immutable questions and attempt state while adapting each next objective. A check embedded in Learn uses the same assessment contracts and evidence rules as a standalone Quiz.

### Streaming and cancellation

Preserve the generation lifecycle from queued through preparing, streaming, finalizing, and completed, with failure, cancellation, and interruption states. Preparing resolves authorized context and the selected intervention. Streaming emits readable content promptly through the provider-neutral adapter. Finalization validates structured output where required, persists canonical content, and emits completion.

Stream teaching prose to the learner. Publish a quiz item only after its structured content and checking pass. A partial question must not be answerable before the private key and rubric are validated. Interrupted teaching is stored as interrupted exposure, not lesson completion or successful learning. Cancellation stops downstream checks and note updates that depend on completed output.

Respect existing note policies and revision checks. A model response can be completed while note insertion awaits the learner's approval; these are separate statuses. Reconnect uses durable canonical results and replay where available. Provider replay events are transport data, while completed turns, interventions, and attempts are authoritative product records.

### Completion requirements

Test a mode suggestion declined by the learner, explicit explanation despite prerequisite uncertainty, embedded assessment, interruption after partial teaching, and reconnect during finalization. Completion requires a result observed in Quiz to shape Learn in another session without creating a second independent state system.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
