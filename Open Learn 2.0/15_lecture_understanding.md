# Lecture understanding and timestamped observations

Turn reconciled transcripts into inspectable concept coverage, examples, emphasis, and academic observations.

Status: planned. Source: section 17 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Stable concepts and course mappings](05_stable_concepts.md)
- [Source evidence and derived memory](08_source_memory.md)
- [Reliable recording and incremental transcription](14_recording_and_transcription.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/lecture_pipeline.py](../backend/app/lecture_pipeline.py)
- [backend/app/lecture_models.py](../backend/app/lecture_models.py)
- [backend/app/lecture_service.py](../backend/app/lecture_service.py)
- [backend/app/review/concept_sync.py](../backend/app/review/concept_sync.py)
- [web/components/lecture-notes-view.tsx](../web/components/lecture-notes-view.tsx)

## Implementation sequence

1. Extract typed observations from coherent sections using course vocabulary and source-backed timestamps.
2. Validate support spans, mathematical uncertainty, concept mappings, negation, and duplicate origins.
3. Emit coverage events and academic fact candidates; distinguish professor-discussed errors from learner misconceptions.
4. Generate revisioned guides and timestamp links, preserving authored notes and triggering targeted reprocessing after corrections.

## Detailed feature requirements

### Structured output and value

Lecture understanding converts a transcript into source-backed academic observations that can drive quizzes and planning. It extracts concept coverage, definitions, equations, worked examples, common errors discussed by the professor, emphasis, mentioned assignments, exam statements, and lecture sections. Extraction of coverage never updates demonstrated learner understanding.

Every observation links to a transcript revision and audio interval, with the supporting text span. Facts include whether the statement was direct, inferred, tentative, or negated. Important for the exam is professor emphasis. It does not automatically establish a complete exam syllabus.

### Processing sequence

Divide the reconciled transcript into coherent lecture sections with bounded overlap and stable origin IDs. Retrieve relevant course vocabulary and supplied slides to interpret notation. Extract candidates using a typed schema, then validate timestamp bounds, quotations or support spans, concept mappings, and referenced academic entities. Deduplicate observations that arose from overlapping sections.

Separate mathematical content reconstruction from raw transcription. A spoken formula can be normalized using source material, but a guessed symbol must remain uncertain until validated. Store a correction suggestion beside the transcript rather than rewriting the original audio-derived text without provenance.

### Academic statement handling

An assignment mention becomes a candidate linked to an existing assignment if identity is clear. An incomplete mention such as problems seven through thirteen tomorrow remains an unresolved task reference with its lecture date and course timezone. Do not invent a deadline time. A statement about an exam next Friday resolves against lecture date and timezone, with ambiguity flagged when necessary.

An extraction can record a professor discussing a student's common misconception. That is course material, not evidence that the current learner holds the misconception. This distinction must be explicit in schema and tests because the same phrase can otherwise leak into personal diagnosis.

### Notes and corrections

Generate the lecture study guide from validated observations and source spans. Keep a readable outline, key concepts, worked examples, practice suggestions, and timestamp links. Preserve student-edited notes under the existing note policy. A transcript edit or new slide revision reprocesses affected sections and supersedes changed facts without duplicating the lecture.

The UI allows a student to inspect the moment behind a fact, correct an extraction, confirm an assignment match, or dismiss an uncertain claim. A correction triggers academic reconciliation and invalidates future context as needed. An already completed quiz retains its historical source revision and can be reviewed if the correction changes item validity.

### Completion requirements

Test negated exam statements, ambiguous dates, repeated emphasis, noisy equations, overlapping extraction, professor-discussed misconceptions, and transcript edits. Completion requires quiz requests scoped to a lecture or week to use actual covered concepts and preserve source links.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
