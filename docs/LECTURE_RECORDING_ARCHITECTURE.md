# Lecture recording architecture and implementation plan

## Existing architecture

- `web/components/class-recorder.tsx` uses one `MediaRecorder`, accumulates every one-second event in memory, and writes one Blob to `web/lib/class-recordings.ts` only after Stop. The browser then creates a workspace note and uploads the Blob.
- `backend/app/class_recording_routes.py` accepts one owner-scoped 24 MiB upload. `backend/app/class_recording_service.py` saves one file and one `class_recordings` row, then a FastAPI background task transcribes the whole file and writes a Markdown guide and transcript into the workspace note. The startup hook in `main.py` resumes queued work.
- `workspace_note_service.py` owns Markdown files and optimistic revisions. The notes UI edits those files and polls recording status. Legacy audio can be read from IndexedDB or the authenticated backend route.
- `material_owner` is the current local development identity boundary; hosted access fails closed. `WorkflowStore` supplies durable idempotent jobs and expiring leases. `model_provider.py` supplies the common structured JSON transport. Materials, course ownership, context retrieval, and KaTeX rendering already exist.
- The prior pipeline lacks independent capture persistence, chunk ordering, segment timestamps, explicit processing stages, structured lecture facts, and claim evidence. A large lecture exceeds the single-upload limit. A browser interruption can lose all audio captured since Start.

## Target architecture

1. Capture independently playable short audio files from a continuous microphone stream. Persist every file and its sequence/timing/checksum in IndexedDB before upload. Retain unacknowledged files. Persist the recording manifest and final expected count locally.
2. A durable upload queue creates an owner-scoped server recording, sends chunks by sequence with idempotent PUT, checks the server acknowledgement, and retries with bounded backoff. Browser startup resumes incomplete manifests. Stop ends capture immediately; upload and processing continue.
3. Server files use generated immutable object keys and atomic writes. A normalized `lecture_recordings` row tracks session state, expected count, course, note, preferences, and stage states. `lecture_audio_chunks` has a unique `(recording_id, sequence_number)` constraint, checksum, timing, storage key, transcription state, and retry metadata. Missing chunks remain visible and block final publication.
4. Each accepted chunk enqueues an idempotent transcription job through `WorkflowStore`. The transcription adapter has a provider-neutral interface. Its raw result becomes timestamped, versioned `lecture_transcript_segments`; normalization retains raw text and marks uncertainty. Adjacent boundaries use previous transcript context and conservative deterministic duplicate removal.
5. Finalization records the expected chunk count and exposes missing sequence numbers. Once every chunk has transcribed, resumable jobs run section segmentation, structured section analysis, evidence verification, and deterministic note block generation. Adjacent semantic sections are merged across analysis windows. Semantic sections are unrelated to audio file boundaries. Model output passes typed schema validation; server assigns IDs and rejects evidence references outside the transcript. Only supported, normalized, or clearly uncertain claims reach lecture-derived blocks. Corrections, questions, equations, examples, administrative items, and emphasis have distinct kinds.
6. `lecture_sections`, `lecture_entities`, and `lecture_note_blocks` hold the canonical representation and evidence IDs. The note view renders generated Markdown content from these blocks with rich math support. User-authored note text remains in its current workspace note; generated blocks are stored separately and rendered alongside it, so regeneration never overwrites edits. The workspace Markdown export currently contains the authored body; the full local backup also contains the generated block tables.
7. The notes UI shows aggregate progress, structured blocks, transcript timestamps, and audio seek. Course context may help interpret terminology but never counts as evidence of what was spoken. The existing legacy `class_recordings` route and Markdown notes remain readable; only newly started recordings use this pipeline.

## Planned files and interfaces

| Area | Change |
| --- | --- |
| Database | Add migration after `0025_class_recordings.py` with lecture sessions, chunks, transcript segments, sections, entities, note blocks, and relevant uniqueness/owner/status indexes. |
| Backend | Add `lecture_models.py`, `lecture_storage.py`, `lecture_service.py`, `lecture_pipeline.py`, `lecture_provider.py`, `lecture_routes.py`, and a recoverable worker. Register routes and startup recovery in `main.py`. Reuse `WorkflowStore`, `WorkspaceNoteService`, material/course access, and the text provider adapter. |
| Browser | Replace in-memory recording with capture/IndexedDB/upload modules, keep `ClassRecorder` focused on controls and status, and add a recovery manager and structured note view. Extend `web/lib/api.ts`. |
| Documentation | Document API, stage transitions, ownership, recovery, provider configuration, audio retention, and legacy behavior here and in `backend/README.md`. |

## API contract

- `POST /v1/learners/{owner}/lecture-recordings`: idempotent creation from a client-generated recording ID and immutable capture metadata; returns the note ID.
- `PUT /v1/learners/{owner}/lecture-recordings/{id}/chunks/{sequence}`: bounded binary body plus start/end/MIME/checksum headers; returns the committed checksum and sequence. Identical duplicates succeed; conflicting duplicates return 409.
- `POST /v1/learners/{owner}/lecture-recordings/{id}/finalize`: submits expected chunk count, duration, markers, and interruption status; returns continuity status and missing sequences. Publication waits until the gap list is empty. Preferences are supplied at creation and can be changed by regeneration.
- `GET /v1/learners/{owner}/lecture-recordings/{id}`: aggregate capture, upload, transcription, and analysis status. `GET .../chunks`, `.../chunks/{sequence}/audio`, `.../transcript`, `.../sections`, `.../representation`, and `.../notes` expose owner-scoped data. Retry endpoints target a chunk or failed jobs; regeneration changes note depth without transcribing again.
- Existing `workspace-notes` and legacy `class-recording` APIs continue to work.

## State, storage, and recovery

Capture transitions: local `recording → paused → stop_requested`, with `interrupted` on restart and `completed` after server completion. Server status moves `recording → waiting_for_uploads → processing → completed`, or `failed` if a job needs retry. A chunk moves locally from `persisted → uploading → server_confirmed` or `failed`, while server transcription moves `pending → running → completed` or `failed`. The server acknowledges only after file and metadata are durable. Upload order never determines lecture order.

The browser retries creation and each missing upload after reconnect and reload. An interrupted capture requires the learner to choose **Finish saved audio** to acknowledge that its final seconds may be missing. The backend worker claims jobs with the existing lease mechanism, resumes expired work, and skips completed chunk transcription and unchanged final stages. File write before DB failure can leave an orphan object; DB metadata never acknowledges a missing object. Deletion and retention run only after ownership and completion checks. Missing chunks are explicit in status and prevent final authoritative notes. The local backup archive includes retained recording files and all lecture tables, with a 512 MiB archive limit.

## Model and verification strategy

- Transcription uses the configured audio adapter, with chunk-specific calls and prior transcript tail as contextual vocabulary when supported. Raw text and relative timestamps are immutable; normalized text has a separate version.
- Semantic segmentation groups transcript segments across chunks. Per-section structured extraction uses bounded nearby transcript plus relevant course material. Course passages are interpretation context, never lecture evidence.
- Pydantic validates sections/entities/blocks, evidence IDs, timestamps, kinds, and output sizes. The server generates stable IDs. A verification stage checks every professor-derived block against referenced transcript segments and excludes unsupported claims. Uncertain math keeps spoken form; enrichment has a separate source label.
- Note depth and inclusion preferences change rendering and note generation without another transcription call.

## Migration and validation strategy

The new schema is additive. Legacy records retain their current playback and Markdown rendering. New rows carry pipeline versions and provider/model metadata. Migration upgrade and downgrade must preserve old tables.

The implemented backend tests cover owner isolation, idempotent and conflicting uploads, checksum rejection, out-of-order arrival, missing sequences, HTTP acknowledgement, transcription retry, unsupported claim exclusion, deletion, user edit preservation, evidence-backed note blocks, automatic lecture context, migration downgrade, and a simulated one-hour lecture with 450 slices. All 10 lecture integration tests pass. Two browser capture unit tests pass, including a failed local save remaining recoverable rather than being reported as saved. Type checking, targeted lecture lint, and the production frontend build pass. The full backend suite currently reports 337 passed, 13 failed, and 3 skipped; its failures are in quiz, course, provider, and other learning paths. Full frontend lint has two errors in course and quiz components. Browser microphone capture, real provider output, transient network failure, and multi-process worker execution still need live environment checks.

## Operating details and current limits

- Configure the existing text model provider and `OPENAI_API_KEY` for audio transcription. `AI_TUTOR_TRANSCRIPTION_MODEL` defaults to `gpt-4o-mini-transcribe`. The legacy single-file route remains available for prior recordings.
- The current local environment has no active `OPENAI_API_KEY`, so a real transcription and note-generation run remains an acceptance gate before release.
- New captures need a browser tab open while the microphone is recording; browser storage must remain available. Upload resumes when the app is reopened, online, or foregrounded. A browser that clears IndexedDB before upload can lose unsent slices.
- Timing is at the eight-second slice level when the transcription provider supplies only text. Unknown speakers stay `unknown`; the system does not infer professor or student identity from voice alone. Low-confidence equations keep spoken wording instead of invented notation.
- Worker recovery uses the local app process and its existing database leases. Multi-instance deployment needs shared durable object storage and a dedicated worker deployment before it should accept real classroom recordings.
