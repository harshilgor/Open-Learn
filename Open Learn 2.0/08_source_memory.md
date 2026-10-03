# Source evidence and derived memory

Manage revisioned sources, exact evidence, and derived summaries with shared retrieval, correction, and deletion rules.

Status: implemented locally for source revisions, retrieval, provenance, correction, deletion, and extractive continuity summaries; model-based summary regeneration and deployed acceptance remain gated. Source: section 10 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

## Current implementation and verification

`SourceMemory` stores owner-scoped immutable revisions with exact text ranges, hashes, and extraction metadata; lexical retrieval filters ownership, course scope, deletion, and current revision. Derived preferences and summaries retain explicit scope and source basis. Source edits/removal invalidate dependent facts. Existing notes, lecture intervals, and material blocks are snapshotted into content-addressed memory revisions when selected for context, while their original stores remain authoritative and their source-specific commit fences are preserved. Summary generation is deterministic and extractive with exact source ranges; it does not claim to be a provider-generated summary. The Source & remembered facts settings view supports inspection, correction, removal, dismissal, and explicit refresh.

Focused local tests cover source correction/removal during generation, account isolation, stale material extraction, portable export/import, and source provenance snapshots. Remaining work is provider-backed summary generation with durable regeneration jobs, systematic background backfill independent of context requests, and live PostgreSQL/vector-index acceptance. Current lexical retrieval works without embedding credentials; embeddings remain optional and unconfigured.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Shared data contracts and architecture decisions](02_shared_data_contracts.md)
- [Identity authorization and device synchronization](03_identity_and_device_sync.md)
- [Stable concepts and course mappings](05_stable_concepts.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/material_service.py](../backend/app/material_service.py)
- [backend/app/workspace_note_service.py](../backend/app/workspace_note_service.py)
- [backend/app/workspace_note_context.py](../backend/app/workspace_note_context.py)
- [backend/app/conversation_state.py](../backend/app/conversation_state.py)
- [backend/app/automatic_note_context.py](../backend/app/automatic_note_context.py)
- [backend/app/semantic_retrieval.py](../backend/app/semantic_retrieval.py)

## Implementation sequence

1. Introduce immutable source revisions and semantic spans carrying original locators, course scope, hashes, and extraction provenance.
2. Unify source eligibility checks and lexical/optional vector indexing; exclude deleted or superseded sources before ranking.
3. Retain scoped explicit preferences and summary provenance. Connect source corrections to derived-fact and cache invalidation.
4. Preserve user-edited notes and recording-generated blocks separately; build correction, removal, and reprocessing interfaces.

## Detailed feature requirements

### One practical memory system

Memory will have three operational categories. Source memory contains documents, transcripts, notes, conversation turns, and question presentations. Evidence memory contains what the learner did and how the response was evaluated. Derived memory contains learner projections, course facts, explicit preferences, summaries, and hypotheses. Each derived item links to its source or evidence basis.

These categories share storage services and lifecycle rules. We do not need separate episodic and semantic databases. The purpose is to retrieve the right fact and correct it when its basis changes.

### Ingestion and retrieval preparation

For each source, authorize access, validate type and size, hash the bytes, store an immutable revision, and extract structured text. Prefer semantic blocks such as a definition, example, slide section, or transcript interval over arbitrary character cuts. Store page, heading, course, concept candidates, and original offsets. Overlapping chunks may improve retrieval but must retain shared origin IDs so repeated retrieval does not inflate evidence or duplicate context.

Use full-text retrieval for exact notation and lexical terms, plus vector retrieval where available for paraphrases. Always apply owner, course access, deletion, and revision filters before using results. A vector index is an index of sources, not a second authoritative copy of facts. Deleted or superseded content is excluded immediately even while asynchronous index cleanup is pending.

### Summaries preferences and corrections

Preserve explicit learner preferences with the original statement and scope. A course-specific preference for short answers must not silently become a universal learning-style label. Inferred preferences remain tentative and can be confirmed or dismissed. Do not infer cognitive traits from response time or a single task.

Conversation summaries retain unresolved questions, decisions, constraints, and provenance. They assist continuity but never replace exact attempt evidence. Summary generation uses bounded chunks and source ranges; failed compaction does not permit silent loss of required history. Regenerate summaries when source turns are corrected or deleted.

Note edits create revisions and protect student writing. Generated recording output remains separate from authored note content. When an old source is corrected, invalidate derived facts and affected context caches. For a quiz already in progress, preserve the displayed item and mark validity for review rather than silently rewriting it.

### Completion requirements

Settings and source views allow correction, removal, reprocessing, and inspection of generated facts. Test source edits during indexing, removal during model generation, duplicate documents, corrupted extraction, and retrieval across accounts. Completion requires all workflows to retrieve permitted current content and explain historical outputs using preserved revisions.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
