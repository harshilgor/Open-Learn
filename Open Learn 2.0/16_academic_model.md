# Academic model and course fact reconciliation

Represent academic expectations, deadlines, and covered material with provenance and explicit conflicts.

Status: planned. Source: section 18 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Shared data contracts and architecture decisions](02_shared_data_contracts.md)
- [Identity authorization and device synchronization](03_identity_and_device_sync.md)
- [Stable concepts and course mappings](05_stable_concepts.md)
- [Source evidence and derived memory](08_source_memory.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/course_models.py](../backend/app/course_models.py)
- [backend/app/course_service.py](../backend/app/course_service.py)
- [backend/app/course_routes.py](../backend/app/course_routes.py)
- [web/components/course-home.tsx](../web/components/course-home.tsx)
- [web/lib/api.ts](../web/lib/api.ts)

## Implementation sequence

1. Extend courses with terms, assignments, assessments, coverage, and immutable academic fact observations.
2. Resolve entities using external IDs and source identity; implement field-specific reconciliation and durable user overrides.
3. Preserve date-only and unknown-timezone values plus student-specific due dates; keep confirmed, probable, and unknown exam scope separate.
4. Build course timeline, upcoming work, source links, conflict resolution, and last-sync status. Provide manual input independently of Canvas.

## Detailed feature requirements

### Entities and expected knowledge

The academic model represents what a course expects and what has been covered. It owns course instances, terms, materials, lectures, assignments, assessments, coverage observations, and academic facts. It does not own personal mastery. Courses can be populated manually, through uploads, lecture understanding, or the local Canvas reader.

Assignments store external identity where available, title, instructions, material references, effective due date, availability, completion observations, and concept or outcome mappings. Assessments store known date, format, scope claims, weighting when explicitly supplied, and source status. Coverage records what was taught or assigned and when, separately from what the learner completed.

### Fact provenance and conflicts

Each academic fact includes subject, predicate, value, source span or authenticated browser locator, observed time, effective time, source revision, confirmation status, and reconciliation rationale. Preserve raw observations from all sources. The canonical view points to the chosen fact and any unresolved conflict.

Use field-specific reconciliation. The authenticated student's Canvas assignment date is a strong basis for the effective due date; the syllabus may define baseline policies; a recent direct professor announcement may modify exam scope. A single global rule that newer always wins or Canvas always wins is insufficient. If two credible sources disagree and neither clearly supersedes the other, expose the conflict and avoid an invented resolution.

Canvas supports differentiated assignment dates and overrides [5]. Our browser reader must preserve the date shown for the authenticated learner, not replace it with a generic date parsed elsewhere. Store date-only, timezone-unknown, and no-date cases explicitly. Null is not the same as an assignment due immediately.

### Scope mapping

Connect an assessment to course outcomes and concepts using source-backed scope claims. Confirmed scope, probable scope, and unknown scope are separate sets. Professor emphasis can increase a planning priority under a documented heuristic, but it does not prove an omitted topic is excluded. Weighting remains unknown if no credible source specifies it.

Lecture coverage can expand course-concept mappings, but proposed mappings need review when ambiguous. Syllabus expectations and lecture coverage can differ without either being wrong: a future topic may be expected but not yet taught. Store both rather than collapsing them into one covered flag.

### Reconciliation jobs and UI

Academic ingestion writes immutable observations, then runs idempotent entity matching and fact reconciliation. Match external assignment IDs first. Fall back to course, source URL, and explicit identifiers; title similarity alone is insufficient for automatically merging distinct homework sets. A source disappearing during a failed or partial sync does not mean the assignment was deleted.

Course pages show timeline, covered concepts, upcoming work, materials, and last synchronization. Conflicting or tentative facts have a visible review affordance. Students can add missing exams and correct imported facts while preserving an override and its reason. Later syncs do not silently overwrite a deliberate user correction.

### Completion requirements

Test multiple sections, override dates, date-only events, changed exam scope, duplicate assignment titles, withdrawn announcements, partial imports, and student corrections. Completion requires a plan or readiness report to identify the sources behind its academic expectations.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
