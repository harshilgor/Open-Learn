# Shared context compiler

Compile authorized, purpose-specific context for teaching, quizzes, readiness, and planning from the same memory services.

Status: planned. Source: section 11 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Stable concepts and course mappings](05_stable_concepts.md)
- [Unified learner state and retention](06_learner_state_and_retention.md)
- [Source evidence and derived memory](08_source_memory.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/context_engine.py](../backend/app/context_engine.py)
- [backend/app/context_service.py](../backend/app/context_service.py)
- [backend/app/assessment_context_planner.py](../backend/app/assessment_context_planner.py)
- [backend/app/journey_service.py](../backend/app/journey_service.py)
- [backend/app/automatic_note_context.py](../backend/app/automatic_note_context.py)
- [backend/app/context_provenance.py](../backend/app/context_provenance.py)

## Implementation sequence

1. Define compile_context inputs and a typed packet with included revisions, source spans, warnings, omissions, and token accounting.
2. Consolidate teaching and assessment retrieval into shared scope resolution, structured-state loading, source diversification, and budget selection.
3. Preserve required premises and rubrics; reserve output overhead and ask for narrower scope when required context cannot fit.
4. Use consistent snapshots and revision-keyed caches. Recheck source access and event watermarks before generating a decision.
5. Integrate lecture/week retrieval into Quiz and prove cross-session continuity through manifests and complete workflows.

## Detailed feature requirements

### Contract and value

Create compile_context with purpose, authenticated principal, course, target concepts, session, activity snapshot, required source IDs, token budget, and expected state revisions. Its return contains a typed context packet, a manifest of included spans and state records, omitted items with reason codes, budget usage, and source-quality warnings.

Ask, Learn, Quiz, readiness, and planning call the same compiler. Purpose controls selection: Quiz receives private planning context but no future answer leakage; teaching receives relevant learning history and intervention constraints; readiness receives scope and capability evidence; planning receives academic goals, availability, and actionable gaps. Sharing memory does not mean sending the identical prompt to every model call.

### Retrieval and selection sequence

Authorize the principal and resolve course and concept scope. Read structured learner state, course facts, explicit preferences, and activity snapshots first. Traverse only relevant reviewed prerequisites. Retrieve source blocks through lexical and optional vector search. Rank candidates by purpose and concept relevance, source validity, directness, and freshness appropriate to the fact type.

Group duplicate origins and diversify sources so five chunks from one generated note do not crowd out a primary assignment. Required context includes the actual task, active response constraints, target concepts, and necessary question rubric or source material. Optional background is reduced or omitted under the budget. Reserve output and protocol overhead before computing available input tokens.

If required context cannot fit, narrow source scope or ask for a useful clarification before generation. Do not silently truncate a rubric or omit the premise that determines a correct answer. Log omissions and selected revision IDs. Provider-specific tokenizers and safety margins are configuration, tested against actual request shapes.

### Snapshots and consistency

An active quiz freezes its scope, presented questions, sources, and content revisions for reproducibility. Each next-question decision can use the learner's newly accepted evidence while keeping the stated quiz scope stable. A corrected source can invalidate an item; it cannot invisibly rewrite a completed attempt. A newly added lecture is available to a new quiz or an explicitly expanded scope.

Read learner and academic projections from a consistent short database snapshot. Store their revisions in the context manifest. External indexes may lag; recheck candidate ownership and source revision before admission. A recent source not yet embedded can still be found by metadata and text search. Projection lag must be surfaced to the caller rather than interpreted as absence of evidence.

Cache by owner, purpose, target scope, source revisions, learner state revision, academic revision, graph revision, and policy revision. Never reuse a packet across accounts or after a source has been revoked. Logs store manifests and safe metadata by default; access to full prompts is restricted and retention-limited.

### Completion requirements

Test cross-workflow continuity, budget exhaustion, course ambiguity, stale vectors, source removal, contradictory sources, and revision races. A quiz requested about this week's lectures must retrieve those lecture blocks automatically. Completion requires a decision trace to show exactly which information shaped the generated question or explanation.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
