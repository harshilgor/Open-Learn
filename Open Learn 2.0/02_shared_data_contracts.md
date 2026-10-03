# Shared data contracts and architecture decisions

Define consistent ownership, identifiers, revisions, evidence meanings, and service contracts before changing the consumers.

Status: contract and decision-storage implementation added 1 October 2026; live migration and downstream consumer verification remain pending. Source: section 4 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

Implementation: [shared contracts and architecture decisions](../docs/SHARED_DATA_CONTRACTS.md), [typed models](../backend/app/shared_contracts.py), [decision repository](../backend/app/decision_store.py), and [additive migration 0029](../backend/migrations/versions/0029_shared_contracts.py). Existing consumers retain their legacy contracts until their owning feature is migrated.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Application foundation and durable execution](01_application_foundation.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/session_models.py](../backend/app/session_models.py)
- [backend/app/assessment_models.py](../backend/app/assessment_models.py)
- [backend/app/state_models.py](../backend/app/state_models.py)
- [backend/app/course_models.py](../backend/app/course_models.py)
- [backend/migrations](../backend/migrations)

## Implementation sequence

1. Map each proposed record family onto existing tables and typed models; document which records are authoritative and which are rebuildable projections.
2. Write architecture decisions for concept grain, capabilities, assistance lineage, event taxonomy, academic conflict rules, and task completion semantics.
3. Use typed columns for ownership, ordering, and uniqueness; version extensible payload schemas and add additive migrations.
4. Define decision snapshots and invalidation dependencies. Keep evidence quality, evidence strength, hypothesis support, and academic fact confidence distinct.

## Detailed feature requirements

### Core record families

| Record family | Principal fields and constraints |
| --- | --- |
| Account and device | Account ID, auth subject, device ID, grants, revocation, timezone, consent settings |
| Source and revision | Owner, kind, origin, immutable revision, content hash, locator, access state |
| Source span | Revision ID, page or text offsets, audio start and end, extraction method |
| Concept and mapping | Stable ID, definition, aliases, discipline, course outcome mapping, review state |
| Concept relationship | Directed endpoints, relationship type, source, confidence category, effective revision |
| Learning event | Owner, observation type, occurred time, received time, deduplication key, linked attempt and source |
| Event concept link | Concept ID, capability, role in question, attribution basis, uncertainty |
| Evidence evaluation | Rubric revision, outcome, assistance, validity, grading method, evidence quality |
| Learner projection | Concept and capability, state, evidence strength, conflicts, effective event set, reducer revision |
| Hypothesis | Concept, possible error explanation, supporting and contradicting events, status, history |
| Academic fact | Subject, predicate, value, valid period, observed time, source, confirmation and conflict status |
| Question and family | Immutable presented content, private key, rubric, sources, objective, family, validation history |
| Intervention | Selected action, target concepts, decision snapshot, generated content reference, exposure and completion |
| Study plan and task | Goal, availability, plan revision, task spec, status, prerequisites, linked learning activity |
| Job and decision trace | Input revisions, policy revision, status, reason codes, cost and latency metadata |

Use typed columns for fields that control authorization, filtering, uniqueness, and ordering. Reserve JSON payloads for validated extensible details. Each payload has a schema revision and a parser. Avoid one unrestricted facts JSON object becoming the only source of truth for every subsystem.

### Distinct meanings of confidence

Evidence quality describes whether the question, grading, and source basis are trustworthy enough to use. Evidence strength describes the diversity and independence of observations about a capability. A misconception score expresses support for a possible error explanation. Academic fact confidence expresses how directly a source establishes a course fact. These fields are not interchangeable.

Model-produced scores are advisory unless calibrated against labeled outcomes. User-facing displays use words such as tentative, supported, conflicting, and insufficient evidence. We will not present a heuristic score as a probability of mastery or a predicted exam grade.

### Revisions and reproducibility

Each decision retains the learner projection revision, academic snapshot revision, concept graph revision, policy revision, context manifest, and relevant source revisions. Keep the question as it was displayed even if its source note later changes. Historical outputs must remain explainable without using today's edited sources.

Corrections create a new evaluation or superseding fact and invalidate dependent projections. Account deletion is different: it removes personal content and dependent records under the deletion workflow. Append-only history means normal application updates do not silently rewrite observations; it does not mean personal data can never be deleted.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
