# Stable concepts and course mappings

Keep learning evidence attached to stable concepts across sessions and graph revisions while retaining course-specific meanings.

Status: Implemented in the workspace, including reviewed current-revision mapping for task scopes; merge/split editor browser acceptance remains. See [verified coverage and remaining acceptance](LEARNING_WORKFLOWS_IMPLEMENTATION_STATUS.md). Source: section 7 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

Implementation: migration `0032_stable_concepts`, service/routes and `/concepts` review interface added. See [delivery and integration notes](../docs/STABLE_CONCEPTS.md). Runtime acceptance verification remains pending; no tests were run.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Shared data contracts and architecture decisions](02_shared_data_contracts.md)
- [Identity authorization and device synchronization](03_identity_and_device_sync.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/learner_graph.py](../backend/app/learner_graph.py)
- [backend/app/course_models.py](../backend/app/course_models.py)
- [backend/app/course_service.py](../backend/app/course_service.py)
- [backend/app/review/concept_sync.py](../backend/app/review/concept_sync.py)
- [backend/app/learning_policy.py](../backend/app/learning_policy.py)

## Implementation sequence

1. Add stable concept and CourseConcept mappings, including legacy graph/version/node mappings and reviewed aliases.
2. Implement scoped resolution with ambiguity results, reviewed relationship types, cycle rejection, and bounded prerequisite traversal.
3. Map rubric criteria to capabilities and target/prerequisite roles; preserve ambiguous attribution instead of penalizing every concept.
4. Build reviewed graph editing and mapping-error reporting. Preserve historical presentations through merges, splits, and graph changes.

## Detailed feature requirements

### Value and identity rules

The graph connects errors to prerequisite checks and connects course coverage to assessable capabilities. The current graph provides a useful base, but topic-word matching and graph-local IDs can fragment history. We will establish stable identity while allowing courses to use different notation, depth, and outcomes.

A concept stores a definition, aliases, discipline, expected grain, and examples. CourseConcept maps that concept to the course's wording, materials, scope, and expected capability. Similar names do not imply identical meaning. Linear algebra eigenvectors and an advanced spectral-theory outcome may share a parent concept while requiring distinct capability evidence.

### Relationships and validation

Support PREREQUISITE_OF, PART_OF, RELATED_TO, and COMMONLY_CONFUSED_WITH. Only prerequisite edges participate in prerequisite traversal. PART_OF links scope aggregation; RELATED_TO aids retrieval; confusion edges support diagnostic contrast. Do not use relatedness as a mandatory prerequisite.

Each edge keeps a rationale, source, review status, and effective revision. Proposed LLM edges are candidates until accepted by deterministic validation and an appropriate review policy. Mandatory prerequisite subgraphs must reject cycles. Traversal uses a configurable depth and candidate limit so a question about diagonalization does not trigger an endless survey of every earlier mathematics topic.

### Concept resolution

Resolve explicit concept IDs first, then course-specific aliases and outcome mappings, then lexical and semantic candidates. Return candidates and ambiguity when mappings are uncertain. A phrase such as fields requires course and source context. The interface asks for topic clarification when the distinction materially changes quiz scope; it does not silently choose a different course.

Map question rubric criteria to target and prerequisite concepts during authoring. Relevance weights express relationship to the item, not a universal probability of learner failure. Full success on a multi-concept question supplies aggregate positive evidence; partial failure must use rubric-level attribution. If the cause is ambiguous, keep ambiguous attribution and request a discriminating check rather than lowering every linked concept.

### Historical mapping and edits

Create a legacy mapping from graph ID, graph revision, and node ID to stable concept ID. Merges retain aliases and provenance. Splits require review of historical evidence because a formerly broad item may not identify which new subskill it measured. Uncertain historical events remain linked to the legacy concept until reviewed; do not fabricate precise mappings.

Graph changes invalidate cached prerequisite plans and context packets through revision keys. They do not retroactively change the question shown in an old quiz. A graph editor allows reviewed relationships and clear descriptions of why an edge matters. Students can report a mapping error without directly rewriting shared academic relationships.

### Completion requirements

Test alias ambiguity, duplicate names across courses, prerequisite cycles, graph revisions, merges, splits, and ambiguous rubric attribution. Completion requires evidence to follow a stable concept across sessions while course-specific scope and meaning remain intact.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
