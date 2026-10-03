# Reliable recording and incremental transcription

Preserve durable audio, decode supported media correctly, and recover usable transcripts across capture, upload, and processing failures.

Status: planned. Source: section 16 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Application foundation and durable execution](01_application_foundation.md)
- [Identity authorization and device synchronization](03_identity_and_device_sync.md)
- [Source evidence and derived memory](08_source_memory.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [web/lib/lecture-capture.ts](../web/lib/lecture-capture.ts)
- [web/lib/lecture-local-store.ts](../web/lib/lecture-local-store.ts)
- [web/lib/lecture-upload-queue.ts](../web/lib/lecture-upload-queue.ts)
- [web/components/class-recorder.tsx](../web/components/class-recorder.tsx)
- [backend/app/lecture_service.py](../backend/app/lecture_service.py)
- [backend/app/lecture_pipeline.py](../backend/app/lecture_pipeline.py)
- [backend/app/lecture_storage.py](../backend/app/lecture_storage.py)
- [desktop/src/main.cjs](../desktop/src/main.cjs)

## Implementation sequence

1. Choose the supported browser and native-mobile matrix; define AudioCaptureAdapter and manifests with capture epochs and actual timestamps.
2. Add capture-health and storage-pressure monitoring, durable unit writes, bounded upload queues, and recovery/export actions.
3. Implement hash-verified epoch/sequence uploads and final manifest reconciliation with explicit missing intervals.
4. Replace assumptions about independently playable browser chunks with container-aware assembly/decoding and checkpointed transcription windows.
5. Version provisional transcripts, reconcile overlaps, selectively retry suspect windows, and validate real long captures on each supported platform.

## Detailed feature requirements

### Product contract

Recording must preserve captured audio through network loss, application restart, upload retries, and transcription failure. The student must be able to see what is saved locally, what is acknowledged by the server, and whether capture itself is healthy. Audio storage and transcription are independent; a failed transcription must not require recording again.

Support desktop and mobile foreground browser recording, plus native mobile capture for the supported iOS and Android app targets when background or screen-locked recording is required. Put capture behind an AudioCaptureAdapter so web and native paths share manifests, uploads, transcripts, and processing. Platform packaging is part of completing reliable background mobile capture; a web page alone cannot supply that guarantee.

Browser chunk timing is not exact, and browsers can pause delivery or capture under platform conditions [1]. The recording specification also permits individual MediaRecorder blobs that are not independently playable [2]. Therefore a blob saved every few seconds is a durability unit, not automatically a standalone transcription file.

### Capture and local durability

Before recording, request microphone permission, choose a supported encoding, check storage availability, and create a recording ID and local manifest. Persist every emitted blob with recording ID, capture epoch, sequence, byte count, hash, actual timestamps, and encoding metadata in an IndexedDB transaction. Native adapters use durable local files and a manifest with the same logical fields.

Use a short configurable durability cadence, proposed at roughly five seconds where supported, and independently choose a longer transcription window, proposed at 30 to 60 seconds. Those are engineering targets to test, not guarantees supplied by the timer. A monotonic clock and actual capture observations determine duration; sequence count does not.

Track microphone state, mute, ended events, last data arrival, storage writes, and queued bytes. A stalled capture shows a visible warning and creates an interruption marker. Screen wake lock can improve foreground reliability where supported but is not a substitute for native background capture. Never show recording as healthy based only on an animated timer.

On pause, stop, or interruption, flush pending data when the platform allows and mark the capture epoch boundary. A restarted recorder begins a new epoch with its own encoding initialization data. App relaunch discovers unfinished manifests and offers resume, finish recovered recording, upload, or export. A crash can lose data not yet emitted and persisted; the UI must report recoverable duration honestly.

### Upload protocol

Create the server recording manifest independently of audio completion. Upload bounded units with an idempotent key consisting of recording ID, epoch, and sequence. The server verifies identity, size, hash, media metadata, and sequence. An acknowledgment is sent only after the bytes and manifest reference are durable. A repeated matching upload returns the same acknowledgment; mismatching bytes for the same key are rejected.

Limit upload concurrency and queue memory. Network loss retains units locally. Backoff retries use fresh authenticated upload grants after session renewal. A storage-pressure path pauses capture or asks for export before a write fails silently. Server acknowledgment permits local cleanup under a retention policy; retain a useful recovery copy until finalization or explicit cleanup.

Stop recording submits the expected final sequence for each epoch. Finalization checks the manifest for missing units and requests retransmission. If units cannot be recovered, produce a partial recording with explicit missing intervals. Do not concatenate across missing data and pretend the duration is continuous.

### Media assembly and live transcription

For browser media, decode the ordered contiguous stream using a server-side media pipeline that understands the container and its initialization bytes. Convert complete decoded samples into independently decodable transcription windows. For native or other adapters that emit independently decodable segments, validate that property before using a simpler segment path. Test every supported encoding and platform.

Persist a decoded-sample checkpoint, window manifest, and bounded decoded audio spool. A decoder restart resumes from a valid container boundary or replays the required contiguous encoded prefix, discards already committed samples, and resumes window emission. Use independently decodable segments or supported container checkpoints to reduce recovery cost; do not assume an arbitrary byte offset is a restart point.

Do not transcribe the entire growing lecture again after each upload. Each stable window has a content hash, audio range, prior-context hint if appropriate, and transcription job. A small overlap helps boundary continuity. Merge overlap using timestamps and text alignment; preserve uncertainty when alignment is ambiguous. Output retains original audio offsets, including pauses and missing intervals.

### Transcript revisions and final reconciliation

Store raw provider output, normalized segments, timestamps, language, uncertainty indicators when actually available, and transcription revision. Live segments are provisional and can be corrected. Do not synthesize confidence values from providers that do not return them. Corrections preserve the previous revision and invalidate dependent lecture facts.

After capture ends, reconcile ordering, overlap, missing ranges, and terminology. Retranscribe suspect windows selectively. Keep ordinary retrieval from provisional text visibly provisional until stable. Generate final notes from the reconciled transcript and course material, with citations to transcript spans. Preserve the original audio as the recoverable source.

### UI and completion requirements

The recording screen shows capture health, elapsed actual capture time, local saved duration, uploaded duration, and processing progress in plain language. Students can stop, resume after recovery, retry processing, edit transcript wording, and export recovered audio. Test a full-length lecture, offline recording, browser close, device restart, quota exhaustion, duplicate uploads, lost acknowledgment, missing unit, microphone interruption, locked-screen native capture, and worker crash. Completion requires recoverable captured content and a usable transcript even when processing partially fails.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
