# In-Class mode implementation

Implemented on 4 October 2026 against the existing Python/React application. The web feature reuses lecture capture/transcription, the durable agent worker, course/Buddy attribution, QuizService, shared artifact storage, and the responsive study canvas. It does not provision Supabase or replace the native recording adapter.

## Start and revisit

Choose In-Class from the conversation mode menu or Start class session from a course. The explicit conversation request “Start taking notes for this class” opens the same setup. Opening setup never starts a microphone. Select the course, Buddy override, title, available course materials, microphone where the browser enumerates multiple inputs, detail/audio preferences, and quiet output preferences. Consent must be checked before Start listening is enabled.

The start gesture requests microphone access before a long server operation. Denial leaves no recording manifest and shows the failure in setup. Successful capture saves an owner-labelled manifest and independent audio slices locally. A stable recording ID is reused when the API becomes available. Setup resolves the explicit Buddy override, course Buddy, then account default, and creates one class envelope, recording note, and linked conversation. Setup retries reuse those identities; a changed device/setup is rejected.

The floating shell controls show elapsed time, saved slices, local/connected state and microphone level. Pause/resume capture, mark a moment, Stop, and reopen Class remain available while another workspace view is open. Stop releases microphone tracks immediately and persists final metadata independently of cloud completion. Pause processing is a separate control. Returning to Conversation or closing the canvas does not stop capture.

Course Classes reopen the class workspace. A link of the form `/s/{sessionId}?class={classId}` restores the correct conversation and canvas, including after chat restoration. Reopening on another device is read-only with respect to microphone capture. Device/epoch headers fence class chunk admission; mid-session device handoff is intentionally unsupported in this version.

## Durable processing

Migration 0048 adds `class_sessions`, `class_input_windows`, `class_output_versions`, and `class_session_events`, with owner indexes and recording/class cascading relationships. It is additive and leaves the lecture audio/transcript tables authoritative. Migration 0050 repairs two missing scheduling columns in installations created from an earlier revision of the existing worker schema; it preserves responsibility rows.

Transcript, correction and finalization commits emit the class handoff into the existing transactional execution outbox. The coordinator consumes the handoff once and schedules `class_specialist` jobs through WorkflowStore in the agent worker. Local UI events only navigate. API BackgroundTasks do not create a second class-specialist queue.

A contiguous completed-chunk watermark prevents reordered speech from being processed as earlier coverage. Live windows settle at 30 seconds or 2,000 characters, with a 7,500-character grouping bound, prior passage context and a topic hint. At most 200 windows are accepted. Stable window keys include source wording/revisions and prior context. Four specialist executions can run concurrently per worker tick; provider calls run outside publication transactions. Leases, processing epoch, retry attempt, current window and transcript revision are checked before publication. Stale results cannot replace current output.

Enabled specialists produce:

- Notes: validated generated blocks with supplied transcript segment IDs. Evidence controls reveal the supporting wording and timestamps. Generated versions remain separate from the student's authored note body.
- Materials: existing retrieval over attached reference sources, excluding answer keys and unrelated courses; passages are labelled supplementary. Source access is rechecked on publication and every snapshot.
- Practice: a pinned lecture-only QuizService activity with an independently checked first question prepared before readiness. Further questions, answering, feedback and challenges use the established quiz engine. Coverage itself creates no mastery evidence.
- Flashcards: grounded candidates in one private draft deck per class, keyed by input window. The class view supports answer/evidence reveal. Candidates remain unscheduled; this integration does not implement the broader flashcard editing/spaced-review feature.

Corrections replace current generated versions and mark previous quiz context superseded, while preserving presentations, answers, and student note edits. Failed outputs have independent retry controls. A new retry attempt fences a previously running transport retry. Processing cancellation retains ready content and prevents old jobs publishing after resume.

## Revision package and coverage

Stopping records expected chunks/duration and retains the existing capture integrity checks. Complete transcription schedules a summary, active-recall prompts and revision quiz. These publish independently; ready notes stay readable if another output fails. Enabled class draft cards remain available in Practice. A durable inbox delivery links back to the revision package through the shared notification table; workers do not send direct device messages.

Missing slices remain visible. Preparing available coverage requires stopped capture and an explicit partial-package command. Interruption, missing input, failed outputs, window limits or bounded synthesis are labelled completed-partial rather than complete. Synthesis context is bounded: large transcripts are sampled and labelled, and quiz context is limited to 12,000 characters. A long-class hierarchical synthesis implementation is still needed to guarantee exhaustive full-lecture synthesis; current output never claims that coverage when bounded.

## Rendering and recovery

The class canvas has Notes, Materials, Practice and Revision views. Desktop uses the existing split canvas beside Buddy; mobile expands the same mounted workspace with Return to conversation. Quiet badges indicate practice availability. The snapshot/cursor endpoint is polled every three seconds; the snapshot remains authoritative, and delivered cursor events provide replay metadata. There is no new WebSocket infrastructure. Overlapping polls are prevented, old snapshots cannot overwrite newer cursor state, late responses from a previous class are ignored, and background updates do not move reading focus or scroll.

Opening saved class state does not request microphone permission. Account changes stop active capture; local manifests and upload recovery are owner-bound. Disconnected API/provider states retain local audio and ready generated output. The existing recording recovery/export flow handles interrupted saved slices and never restarts a microphone automatically.

Owner portability discovers the new tables through the existing ownership reflection. Import remaps class/session/window/output references and deck window keys, and imports class envelopes paused with no active jobs/capture. Deleting the recording cascades class rows, cancels its specialist jobs, removes the private draft deck and audio; shared quiz attempts remain historical records in their owned conversation. Full account erasure retains the existing comprehensive ownership cleanup.

## Validation and remaining acceptance

Automated checks cover stable/idempotent setup; foreign owner isolation; live outputs before Stop; checked shared quiz preparation; reordered/duplicate chunks and outbox handoffs; source corrections during provider execution; expired leases; independent failure/retry; processing revision conflicts; explicit missing-coverage decisions; source access loss; export/import/delete; and HTTP capture-device fencing.

Validation results: 18 In-Class tests and 22 existing lecture/assessment tests pass (40 backend tests); four frontend suites pass 11 tests; `tsc --noEmit` passes.

Frontend checks cover no automatic microphone access, denial leaving no manifest, immediate microphone release at Stop, reconnecting with notes/focus intact, late snapshots for another class, separate processing pause, mobile workspace preservation and class restoration. TypeScript checks pass. Desktop and 390px mobile browser checks used a labelled demo class and a deterministic provider fixture, without recording a real microphone or making paid generation calls.

Remaining environment acceptance: hosted PostgreSQL concurrency/leases and shared-device sync; long real recordings, storage-pressure and tab-close recovery; real provider latency/semantic quality; and native background/lock-screen capture. No live latency target or native capture reliability is asserted. Real class generation needs the application's configured transcription/text providers and an embedded or externally running existing agent worker.

Screenshots: `work/in-class-desktop.png` and `work/in-class-mobile.png` (sample data).
