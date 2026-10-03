# Integrated acceptance and user journeys

These are the source brief’s release-level requirements. Every component must be integrated into the relevant journeys.

## Complete user journeys

### Course import to targeted learning

A student signs in, pairs the local Canvas extension, selects two courses, and imports assignments, modules, syllabus, and announcements. The reader records completeness and source locators. The academic model resolves the effective student deadlines and presents any ambiguous exam scope for review. The student can use manual course data if Canvas is temporarily unavailable.

During class, the student records audio. Captured units are durable locally and uploaded as connectivity permits. Decoded windows produce provisional transcript segments. When recording stops, missing units are reconciled, the transcript is finalized, and lecture understanding extracts source-backed coverage and emphasis. Notes preserve separate user edits.

The student asks to learn today's lecture. The context compiler retrieves the lecture, relevant course materials, and learner evidence. The policy sees a possible prerequisite gap, explains why a brief diagnostic would help, and honors the student's choice. The diagnostic uses the shared question pipeline and writes evidence through the same transaction as Quiz.

An incorrect response suggests two possible error explanations. A discriminating check supports one of them. Learn gives a targeted explanation, then offers a distinct independent task. That result updates capability state, hypothesis status, and the review schedule. Merely delivering the explanation does not.

### Readiness to a feasible plan

The student asks whether they are ready for the exam and provides 90 minutes tonight. Readiness reports demonstrated procedure, stale recall, and untested transfer against confirmed and probable scope. The advisor recommends a short check for the highest-impact unknown. The generator creates its executable task and the planner fits it with a fixed homework obligation.

The check establishes a capability previously unknown. Replanning removes redundant unstarted practice while preserving the active task and pinned homework block. A later independent retrieval is scheduled within the student's availability. The student can inspect why a task was added, pin it, shorten the available window, or dismiss an optional recommendation.

### Recovery and correction

Canvas login expires during a refresh. Imported records remain available with the last successful check shown. The run pauses for student authentication and resumes through its course checkpoint. A partial run does not delete unseen assignments.

A recording upload loses its acknowledgment. The client retries the same hashed sequence, receives the existing acknowledgment, and continues without duplicate audio. A transcription job fails, but the source audio remains and the student retries processing. Missing capture intervals are identified in the transcript rather than hidden.

The learner challenges a question whose source contained an error. The item is suspended, revalidated, and invalidated. Correction events rebuild learner state and remove the resulting unnecessary repair task. The original question remains visible in history with its corrected status. This journey must work without an operator manually editing the database.

## Acceptance matrix and completion standard

| Area | Required end-to-end acceptance evidence |
| --- | --- |
| Identity | Two accounts cannot access each other's sources, jobs, streams, attempts, or browser grants |
| Synchronization | A retried offline event appears once and a stale mutable update cannot overwrite a newer revision |
| Evidence | Attempt, ledger, projection, and quiz progress commit atomically or leave no partial result |
| Corrections | Invalidating an item repairs state, review, readiness, and affected unstarted tasks |
| Concept graph | Stable history survives graph revision without equating distinct course outcomes |
| Learner state | Assisted success, independent success, exposure, unknown evidence, and stale recall stay distinct |
| Misconceptions | A discriminating task changes a tentative hypothesis and the teaching action |
| Memory | Editing or deleting a source updates retrieval and derived facts without leaking stale content |
| Context | Ask, Learn, and Quiz use relevant shared history within a logged bounded context |
| Quiz | Planned objective, validated item, rubric grading, and shared evidence form one complete workflow |
| Teaching | Selected intervention respects learner intent and produces a measurable follow-up opportunity |
| Streaming | Cancellation and reconnect preserve canonical content and do not fabricate completion |
| Recording | A long capture survives connectivity loss and restart for all durable captured units |
| Media and transcription | Encoded units decode correctly, windows are bounded, overlap is reconciled, and gaps remain visible |
| Mobile capture | Foreground and native background behavior pass the supported device matrix |
| Lecture facts | Concepts, emphasis, and academic mentions link to actual timestamped transcript support |
| Academic facts | Conflicts, student-specific deadlines, and partial imports are reconciled without invented certainty |
| Canvas | Installation, pairing, import, refresh, expiry recovery, policy blocking, and disconnect are usable |
| Readiness | Report categories match capability evidence and explicitly preserve scope uncertainty |
| Tasks and planning | Tasks launch activities, fit availability, preserve pinned work, and replan from accepted outcomes |
| Evaluation | Baseline comparisons, labeled regressions, and delayed-outcome collection run reproducibly |
| Migration | Existing histories remain intact and resumable with idempotent mapping and backfill |
| Operations | Worker recovery, provider outage, restore, source deletion, and account deletion have tested procedures |

The release is complete when these journeys and invariants pass in the supported local and hosted environments, the team has reviewed the educational quality comparison, and all ordinary failure states have a user recovery path. Completion is assessed by observable behavior and evidence, not by how many modules or prompts were added.
