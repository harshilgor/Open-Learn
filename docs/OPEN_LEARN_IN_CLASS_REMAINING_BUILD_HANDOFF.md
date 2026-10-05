# Open Learn In-Class: Remaining Build Handoff

**Purpose:** hand this file to a future coding agent to continue the In-Class architecture upgrade without relying on the original chat.

**Status checked:** 5 October 2026. This is an implementation backlog, not a claim that the remaining items are complete. Re-check the current branch, schema head, code, and tests before changing anything; this checkout has substantial pre-existing work and may have changed since this handoff was written.

## Current implementation status — 5 October 2026

The implementation milestones below have now been built and integrated. Their original requirements remain below as acceptance criteria, not an instruction to reimplement finished code.

| Milestone | Implemented result | Acceptance still open |
| --- | --- | --- |
| 1: Caption notes | OpenAI event adapter; bounded 10-minute interim TTL; durable interactive provisional-note jobs; revision/epoch/lease fences; archived chunk coverage and transcript corrections reconcile drafts; retry controls and separate latency metrics | Real microphone/provider latency and quality |
| 2: Library cues | Owner/course/role-filtered course-library lookup, physical vs printed page cues, chapter/section/slide/figure/equation cues, ambiguity choices, async chat/professor routing and Materials picker | Real-library semantic quality |
| 3: Material v2 | Versioned page/cue/term ledgers, measured quads where available, optional embedding reranking with lexical fallback, resumable extraction checkpoints and leased per-page OCR, progress/retry APIs | Hosted storage, real OCR/provider performance; parser/text caps deliberately remain |
| 4: Desktop | Consent/ownership bridge, tray capture, lock/suspend Stop/save, bounded quit acknowledgement, explicit resume and source reacquisition, persistent recovery status | Packaged Windows lifecycle and actual OS behavior |
| 5: Mobile | Consent-based capture, persistent manifest/chunk upload recovery, pause/resume/mark/stop, mounted capture controller, foreground recovery and logout handling | iOS/Android native builds and device interruptions/background policies |
| 6: Accessibility | Native state/selection announcements, keyboard pane close/focus recovery, polite transcription status, hidden duplicate PDF canvas and reduced-motion scroll | Windows screen reader, VoiceOver/TalkBack, real zoom/reflow/contrast matrix |
| 7: Metadata | Migration 0071 normalizes NeedInfo, drops duplicate attachment arrays, paged owner/class ledger and direct resolution, portable/cascade behavior | Representative production session measurements |
| 8: Operations | Isolated deterministic acceptance runner with optional explicitly designated empty PostgreSQL test database; local paging/fairness/replay/metrics checks and material scale report | Hosted PostgreSQL concurrency, multi-device real sessions, provider/device/storage-pressure acceptance |

Current implementation evidence is in `docs/IN_CLASS_COMPLETION_STATUS.md`, `docs/IN_CLASS_ACCESSIBILITY.md`, and `docs/IN_CLASS_MATERIAL_V2_ACCEPTANCE.md`. The feature is not yet certified for every production/device environment. Next work should perform the open acceptance checks above and fix any failures, rather than rebuild the completed milestones.

## Start here

Read these first:

1. `docs/IN_CLASS_NEXT_IMPLEMENTATION_PLAN.md` â€” phase checklist and design constraints.
2. `docs/IN_CLASS_IMPLEMENTATION.md` â€” current behavior, routes, data flow, known limitations, and validation history.
3. This handoff â€” the remaining work is expanded below into implementation-sized milestones.

Keep the established boundaries: explicit recording consent; live notes must not wait on materials, quizzes, cards, or revision synthesis; original recorded audio and batch transcription remain authoritative; generated outputs must retain owner, class, recording, transcript-revision, lease, and source-access fences; external resources are read-only unless a learner separately confirms an import/action; retries must be idempotent. Do not claim real-provider, hosted, packaged-desktop, mobile-device, accessibility, or latency acceptance unless it was actually exercised in that environment.

## What is already in place

Do not rebuild these as if they were missing. Verify the code before extending them:

- Durable class sessions reuse lecture recording/transcription, jobs/outbox, quiz and artifact systems.
- In-class coordination advances through bounded transcript/chunk pages, uses short fast-note windows, schedules slower specialists separately, and records stage metrics.
- Class updates support durable event replay/SSE, cursor recovery, bounded snapshots, transcript/output pagination, and a persistent reference pane.
- Corrections and recovered audio rebuild dependent outputs under revision fences. The 5 October update adds migration `0067_class_chunk_coverage`: completed chunk count/revision counters are updated with successful transcription and avoid rescanning every completed sequence during partial recovery.
- Resource intake includes library, public URL, resumable file upload, existing Drive and synced Canvas coverage integrations, persistent course preferences, optional YouTube search, and PDF reading/search/OCR within documented limits.
- Long revision summaries/recall use durable hierarchical jobs; the final quiz remains sampled and labelled bounded.
- Optional OpenAI live captions can be persisted as provisional turns with approximate recording-relative timing. These captions still do not feed note generation.
- Desktop has optional computer-audio capture and a consent-gated display-sleep blocker. Mobile Classes can read/replay class state but cannot capture or control a live recording.

## Recommended build order

Implement one milestone at a time. Each milestone needs its own current-code review, focused automated tests, documentation update, and a clear list of environment checks that remain. These tasks have dependencies, so do not begin by implementing every phase in one large change.

### 1. Live captions into useful provisional notes

**Why:** captions currently display and replay, but learners do not get fast notes from them. They wait for the separate authoritative batch transcription path.

**Build:**

- Define a small transcription-provider interface for live sessions so provider-specific Realtime behavior is kept behind an adapter. Preserve the configured OpenAI-only class policy unless the product explicitly changes it.
- Decide and document the privacy/retention contract for interim (not-yet-final) caption text. Persist only what is needed for reconnect and provisional note generation; enforce per-owner/class limits and expiry/cleanup. Finalized caption turns already have their own replay ledger.
- Turn finalized caption turns into low-latency, tier-1 provisional note jobs. Keep these jobs separate from slow material/practice/card work and make retries/idempotency durable.
- Reconcile provisional notes to authoritative batch-transcript segments using recording ID, overlapping time ranges, and transcript/source revisions. When batch transcription corrects or replaces a caption, link the replacement, retire or update stale provisional output, and preserve learner-authored notes and quiz attempts.
- Clearly label caption-grounded notes provisional until the authoritative transcript settles. Handle captions that never receive a batch match (missing audio, interruption, no speech) without presenting them as verified.

**Likely touchpoints:** `backend/app/live_transcription.py`, `backend/app/in_class_service.py`, `backend/app/in_class_routes.py`, `backend/app/lecture_pipeline.py`, `backend/app/in_class_models.py`, migrations after `0067`, `web/lib/live-lecture-transcription.ts`, `web/components/in-class-workspace.tsx`, `web/components/in-class-workspace.module.css`.

**Acceptance:** provider adapter contract tests; persisted interim/final replay and expiry tests; duplicate/reordered caption idempotency; fast provisional note appears before batch transcription; delayed, corrected, duplicated, unmatched, and missing batch segments reconcile safely; stale workers cannot publish; saved student note edits and quiz attempts survive; captions remain opt-in and visibly provisional; owner isolation and retention limits are tested. Measure and report caption-to-provisional-note p50/p90 separately from batch transcription.

### 2. Course-library cue and outline lookup

**Why:** page/chapter/figure navigation currently searches only references already loaded in the active class snapshot. It cannot find a cue elsewhere in the learner's authorized course library.

**Build:**

- Define normalized cue types for physical page, printed page label, chapter, section, slide, figure, and equation. Preserve the distinction between physical PDF page index and printed label.
- Build a query/index path over ready materials available to the current learner and exact course, with the existing answer-key/sample-paper exclusions and attachment/access checks.
- Return compact candidate references and provenance, then reuse `ClassActionRouter` and the existing reference pane for navigation.
- Require deterministic disambiguation. If multiple sources or labels tie, show a choice or fall through to normal chat; never silently open an arbitrary source or perform an unrequested fetch/import.

**Likely touchpoints:** `backend/app/material_service.py`, `backend/app/material_models.py`, material routes/indexer, class route/service, `web/lib/in-class.ts`, `web/components/in-class-workspace.tsx`, and the existing material/reference pane.

**Acceptance:** tests for physical vs printed pages, chapter/section aliases, duplicates/ambiguity, deleted or detached materials, cross-course denial, protected material roles, and citation provenance. The result must contain only currently authorized references, be bounded in size, and open the cited page/passage through the existing router. Add end-to-end tests that exercise a cue whose source is not already in the live class snapshot.

### 3. Material-v2 indexing and retrieval

**Why:** uploads currently support files up to 500 MiB, but extraction/indexing is still limited to 5 million characters, 1,000 PDF pages, and up to 20 blank-text OCR pages. Stored PDF geometry is approximate text-location data, not full page quads; figures/equations are not a course-wide retrieval index.

**Build in sub-slices:**

1. **Index contract and migrations:** define versioned page, block, figure, equation, OCR, and retrieval records tied to immutable material-version/source revisions. Include deterministic idempotency and reindex behavior.
2. **Page geometry:** store page-space quads/bounding boxes with coordinate transform, crop/rotation, and confidence metadata. Label inferred geometry and fail closed when extraction cannot support it.
3. **Figure/equation discovery:** index captions, labels, nearby explanatory text, and page links. Keep extracted document content untrusted; it is evidence, never executable instructions.
4. **Retrieval:** provide owner/course-filtered full-text search and optional vector retrieval. Use the repository's existing embedding/provider abstractions when they fit; make vector generation optional and preserve lexical fallback. Recheck material access and source revision before returning/publishing a result.
5. **Background extraction/OCR:** make work resumable/page-bounded, retain per-page OCR status/confidence, and give learners an honest indication of pages not processed.
6. **Scale acceptance:** benchmark indexing, retrieval, object storage, and cleanup at representative small and large documents. Adjust limits only from measured memory, latency, and storage results.

**Likely touchpoints:** `backend/app/material_service.py`, `backend/app/material_orchestrator.py`, `backend/app/material_models.py`, `backend/app/material_routes.py`, `backend/app/material_upload_stream.py`, material migrations, `backend/app/object_store.py`, retrieval/context compilation, `web/components/class-pdf-reader.tsx`, `web/components/material-library.tsx`, and `web/components/in-class-workspace.tsx`.

**Acceptance:** migration upgrade/downgrade and legacy-index compatibility; repeated/restarted extraction is idempotent; OCR/page failures are independently retryable; geometry respects rotation/crop/page coordinate systems; full-text and vector results obey owner/course/role/access fences; deleted or revised sources invalidate cached hits; load tests include long PDFs, scanned PDFs, image-rich PDFs, and files near the configured upload cap; memory, latency, and storage metrics are recorded. Do not increase hard limits solely to satisfy a synthetic file size.

### 4. Desktop capture lifecycle completion

**Why:** Windows capture can prevent display sleep during an active recording, but it does not wake a sleeping system and lacks the planned tray/lock-screen lifecycle behavior. Current notes state that packaged desktop acceptance has not been done.

**Build:**

- Decide the supported product behavior for OS sleep, lock, app minimization, app close, and tray operation before wiring native events.
- Add only OS-supported wake/lock/tray controls; report unavailable states rather than promising to wake a machine when the operating system cannot do so.
- Keep capture ownership and consent explicit; reliably release tracks, display/audio loopback, power requests, upload workers, and notification resources on pause, stop, logout, crash, navigation, lock, and shutdown.
- Add user-visible status/recovery when the OS suspends capture or upload.

**Likely touchpoints:** `desktop/src/main.cjs`, `desktop/src/preload.cjs`, `desktop/README.md`, `desktop/forge.config.cjs`, `web/components/class-recorder.tsx`, `web/components/class-recorder.module.css`.

**Acceptance:** native lifecycle tests and manual packaged Windows acceptance for minimize, tray, lock, sleep/wake, network loss, app quit, and restart recovery. Verify no capture survives explicit Stop/logout and no unexpected microphone/system-audio prompt occurs. Document OS/version limitations.

### 5. Mobile live capture and control

**Why:** the native mobile Classes view is read-only; students cannot begin, pause, resume, mark, stop, upload, or follow a live class there.

**Build:**

- Extend the existing mobile Classes view to create/reopen a class capture with explicit microphone consent and persistent capture status.
- Reuse the chunk manifest and resumable upload/recovery semantics instead of adding a second recording protocol. Persist locally and resume safely after app backgrounding, process death, network changes, and device restart where the platform permits.
- Add clear controls for pause/resume, marker, stop, upload/transcription progress, and returning to the class workspace. Integrate current SSE replay and authoritative snapshot recovery.
- Handle interruptions (phone calls, permission revocation, low storage, battery policies) explicitly. Mobile capture remains user initiated; navigation must never start a microphone.

**Likely touchpoints:** `mobile/src/ClassLive.tsx`, `mobile/src/App.tsx`, `mobile/src/account.ts`, `mobile/src/Settings.tsx`, `mobile/app.config.ts`, `web/lib/lecture-capture.ts`, `web/lib/lecture-upload-queue.ts`, and shared class API contracts.

**Acceptance:** unit tests for queue persistence, retry/idempotency, and state restoration; device acceptance on supported iOS/Android versions for permission denial/revocation, backgrounding, calls/interruption, stop, offline capture, reconnect, upload retry, and cross-device class reopen. Confirm owner/device fencing and that local audio retention matches the desktop/web disclosures.

### 6. Accessibility review and fixes

**Why:** controls have some labels/status announcements, but the plan still requires broader keyboard and assistive-technology acceptance across desktop and mobile.

**Build:** review the entire capture and study flow, including consent, live captions, Notes/Materials/Practice/Revision navigation, PDF canvas controls, dialogs, errors, status badges, transcript cues, and the mobile live view after it is built. Fix discovered problems in the components rather than recording a checklist-only pass.

**Acceptance:** keyboard-only completion of setup, capture, pause/mark/stop, notes navigation, citations, PDF page/search, and error recovery; screen-reader announcement order for recording state, upload failures, provisional-vs-authoritative notes, and transcript updates; zoom/reflow and contrast checks; reduced-motion behavior; manual checks with supported Windows screen reader/browser and supported iOS/Android accessibility services. Save a concise results matrix with OS/browser/AT versions and remaining exceptions.

### 7. Session metadata compaction

**Why:** a known remaining maintenance item is auditing growing class session payloads. Several high-volume structures have already moved to indexed tables, but this needs evidence-based review rather than an assumed completed status.

**Build:** measure real serialized session payload size/field growth on short and long classes. Identify fields that grow with transcript length, outputs, events, or window count. Move only unbounded/duplicated structures into owner/class-scoped ledgers with indexes and bounded pages; retain compact cursors/pointers and lazy compatibility reads for existing sessions. Avoid duplicating canonical events, output versions, transcript rows, or window membership in JSON. Add retention/cleanup and export/import behavior where relevant.

**Likely touchpoints:** `backend/app/in_class_service.py`, migrations `0048` onward, `backend/app/identity_import.py`, `backend/app/identity_data.py`, snapshot/event paging, and docs.

**Acceptance:** tests for old payload compatibility, migration backfill, owner scoping, pause/restart/import/export/delete, and large-session growth bounds. Record measured payload-size and snapshot-query improvements. Do not remove legacy fields until migration and recovery are proven.

### 8. Production and device acceptance

This is an acceptance track, not a feature checkbox. Run only when credentials/devices and safe test accounts are available:

- Hosted PostgreSQL migration, concurrent transcription claims, lease expiry, rollback, and class isolation.
- Multi-device replay, stale cursor recovery, idempotent commands, profile import, and changed/deleted material access.
- Long recordings, many transcript pages/windows, tab/app death, offline upload recovery, audio retention/deletion, and storage pressure.
- Real configured provider latency, reconnect behavior, transcription quality, cost accounting, retries/rate limits, and provisional-to-authoritative note reconciliation.
- Packaged desktop lifecycle and native mobile capture after those features are implemented.
- Accessibility review above.

For each run, record environment, software/provider versions, test-data shape, observed p50/p90 values, failures, and unresolved issues. Keep measured results separate from local deterministic tests.

## Coverage gaps to close as features are built

The 5 October backend run passed 61 tests with 2 skipped across In-Class, lecture, execution foundation, migrations, object storage, and materials. That verifies useful foundations, not every architecture contract. Add focused tests when touching these areas:

- Coordinator continuation across more than one 100-segment page; silence flush and settled tail behavior.
- Cursor replay, cursor-ahead/history-gap reset, and snapshot recovery through browser SSE.
- Class-specific queue priority, per-class caps, reserved batch capacity, and cross-class fairness.
- Metrics endpoint owner scope, bounded retention, percentile calculations, and diagnostics UI.
- Resource-intent connector policy and authorization across re-open/retry flows.
- Browser workspace integration tests using the current resource connector/preferences/events/stream API surface.
- Migration `0067` backfill with existing completed class chunks and safe handling of concurrent new completions.

The Web runner could not start in the recorded Windows environment because Vite/Node subprocess creation returned `spawn EPERM`; TypeScript also reported missing exports from generated `.next` route declarations. Diagnose environment/generated-type freshness before interpreting those as application errors. Do not remove or rewrite generated build state without checking whether it belongs to the user.

## Definition of done for a future implementation task

The chosen milestone is complete only when its backend/data path, API contract, client behavior, migrations, failure/retry semantics, owner/access fences, focused tests, and documentation all work together. Run the relevant tests and static checks. Manually exercise provider/device flows when available, and state explicitly which environment checks remain unavailable. Update both this handoff and `docs/IN_CLASS_NEXT_IMPLEMENTATION_PLAN.md` so future agents can tell completed work from open acceptance.

## Suggested prompt to give a coding agent

> Read `docs/OPEN_LEARN_IN_CLASS_REMAINING_BUILD_HANDOFF.md`, `docs/IN_CLASS_NEXT_IMPLEMENTATION_PLAN.md`, and `docs/IN_CLASS_IMPLEMENTATION.md`. Inspect the current checkout and identify the first uncompleted milestone (or the milestone I name). Implement that milestone end to end in the existing architecture, preserving consent, ownership, revision, worker-lease, source-access, and idempotency fences. Add focused tests and update the plan/handoff. Do not redo completed features, broaden scope to unrelated product work, deploy, or claim device/hosted/provider acceptance you did not run. Report changed files, tests run, limitations, and remaining milestones.
