# In-Class implementation and acceptance status

Updated 5 October 2026. All remaining implementation tracks from the handoff have code paths integrated. Production readiness still depends on the environment acceptance below; local tests do not establish native capture or real-provider quality.

## Caption notes and reconciliation

Migration 0070 adds a separate provisional note ledger and expiring interim text. The OpenAI event adapter maps committed/delta/final/error events into provider-independent capture state. Interim updates are coalesced to at most one request per item per second; the server keeps at most 20 per class with a ten-minute TTL. Interim content is excluded from permanent class events and profile imports. Finalized captions remain bounded at 20,000 turns per class; timed finalized turns schedule durable interactive draft jobs at priority 110, with source version, processing epoch and worker lease fences. Untimed captions remain replay text.

Drafts cite live-caption IDs and remain visibly provisional. The existing batch audio transcript remains authoritative. Completed overlapping audio intervals trigger bounded reconciliation pages: fully covered drafts become reconciled with authoritative segment/revision links; covered intervals with no speech become unmatched/unverified. Transcript corrections refresh those links; reconciliation event keys include both caption and note revisions so a caption updated after archival is reconciled again. Stale workers cannot publish a retired draft. Partial or missing audio does not certify a draft. Student note bodies and quiz attempts remain separate. Pause/resume requeues unfinished drafts, and failed drafts have explicit revision-fenced retry. Metrics report `caption_note` latency separately from batch transcription.

## Materials and references

Migrations 0068/0069 add immutable-source page, cue, term, extraction-checkpoint and OCR ledgers. Course lookup searches beyond loaded class references, filters owner/course/role/access, rechecks source revision after optional embedding work, and preserves lexical search when that provider is absent or fails. It distinguishes physical PDF pages from printed labels, supports chapter/section/slide/figure/equation labels, and offers candidate choices when ambiguous. Chat and professor cues reuse the reference pane; Materials also provides an explicit lookup form. Already authorized course sources open without an implicit import.

Page geometry uses measured PyMuPDF quads/crop/rotation when available; legacy inferred locations remain labelled approximate. Figure/equation labels and nearby text are indexed evidence, not verified visual interpretation. Extraction checkpoints allow retries to skip settled pages. Background OCR claims and settles one page with source hash/lease checks, bounded render/time/text budgets, status and retry APIs. Retry search postings and cue discovery use immutable canonical passage wording rather than a nondeterministic second OCR result; the six material-index tests cover this consistency guard. The pane shows index progress. Existing 1,000-page and five-million-character indexing caps remain, with the 500-MiB upload cap independent of extracted text coverage.

Local material evidence is in `docs/IN_CLASS_MATERIAL_V2_ACCEPTANCE.md`: 1,000 text pages, scanned pages with explicitly unavailable OCR, rotated page geometry, and a 499-MiB streaming object write. Reported Python heap excludes native-library allocations. Real OCR/provider/hosted storage load is not certified by those probes.

## Capture platforms

Desktop has consent/ownership-checked tray controls. Lock/suspend requests Stop/save; waking does not activate a microphone. Quit waits up to three seconds for a saved-manifest acknowledgement. Pause releases microphone, loopback, mixer and wake locks; explicit Resume reacquires sources while preserving the manifest. Denied Resume leaves the capture paused. Recovery status persists. This implements sleep/wake recovery; it does not claim OS wake scheduling or recording through sleep.

Mobile capture remains mounted across navigation. It uses the established native WAV segments and class setup/device/epoch upload protocol, durable checksums/acknowledgements/markers, explicit consent, pause/resume/mark/stop, saved upload retry, foreground recovery and logout shutdown. An OS-stopped recording is recovered as interrupted rather than silently resumed. Local files remain until explicit deletion after upload; server retention remains separately disclosed. See `mobile/README.md` and `desktop/README.md` for platform acceptance requirements.

## Metadata and accessibility

Migration 0071 normalizes growing NeedInfo arrays into an owner/class ledger, removes duplicated attachment lists from saved session JSON, retains direct lookup/idempotent resolution and bounded cursor pages, and supports backfill/downgrade/import/export/delete. A synthetic 1,200-request payload measured 444,365 bytes before compaction and 76 bytes afterward. This is a fixture measurement, not a production workload claim.

Accessibility fixes include recording state announcements, mobile selection states, polite transcription status, keyboard Escape/Close and reference focus recovery, hidden duplicate PDF visual canvas and reduced-motion scrolling. Detailed source/DOM evidence and manual acceptance matrix are in `docs/IN_CLASS_ACCESSIBILITY.md`.

## Validation evidence

- Combined backend slice: 76 passed, 2 skipped across class, caption notes, metadata, materials, lecture, workflow, migrations and storage. A subsequently added HTTP caption/reference lookup test also passed (7 caption tests total, including caption revision after archival).
- Browser integration, capture and recording-status suites: 10 tests passed through the native Vite config loader, including provisional replacement and library lookup outside the snapshot. Desktop lifecycle tests: 3 passed. Mobile source typecheck passes.
- Operational runner: `python backend/scripts/in_class_acceptance.py --output work/in-class-acceptance-final.json` passes five deterministic local groups, including 205-segment pagination, replay, owner/device fences, per-class fairness/reserved batch capacity, and metrics percentile/retention checks. It ignores the application's default database and allows PostgreSQL only through an explicitly designated empty acceptance database.
- Source TypeScript checks pass with stale generated `.next` route declarations excluded. The normal project check still reports missing generated route exports; generated user build state was preserved.

## Acceptance remaining

Run real microphone/OpenAI reconnect, quality and latency checks; hosted PostgreSQL concurrent leases/multi-device sessions; shared object-store storage pressure; packaged Windows lock/tray/suspend/quit; Android/iOS device permission/interruption/background/OS-kill recovery; NVDA/Narrator/VoiceOver/TalkBack and real zoom/reflow/contrast. Credentials, native toolchains and devices were not used for these checks. Record results and fix failures before claiming complete production acceptance.

### Environment audit — 5 October 2026

The final acceptance audit checked tool availability and environment variable names without printing secrets. `OPENAI_API_KEY` and `OPENLEARN_ACCEPTANCE_DATABASE_URL` are absent from the execution environment. `adb`, `java`, and `psql` are unavailable on PATH. Docker CLI is installed, but `docker info` cannot connect to the Docker Desktop Linux engine named pipe. This session has no recorded packaged-device capture or actual screen-reader run.

Resume prerequisites: provide a dedicated empty PostgreSQL database named `openlearn_acceptance_*` via `OPENLEARN_ACCEPTANCE_DATABASE_URL`; enable the configured provider in a safe test environment; supply the native Android/iOS build toolchain and devices; run packaged Windows and assistive-technology acceptance using the documented procedures. No existing application database should be repurposed as an acceptance database.

The full user goal remains unachieved while these acceptance requirements are unresolved. Local implementation/test progress is retained; remaining environment acceptance requires an external-state change or user participation.
