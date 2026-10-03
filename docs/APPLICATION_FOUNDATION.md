# Application foundation and durable execution

## Execution profiles

Open Learn remains one Python backend application. HTTP and streamed lesson generation run in the API process. Persistent learning commands, lecture stages, ingestion, and outbox delivery use the worker from the same package.

Local development defaults to `OPENLEARN_WORKER_MODE=embedded`: startup runs a polling worker, and request background tasks may reduce dispatch latency. Persistent records, rather than those tasks, are the recovery mechanism. Production/deployed environments default to `external`; supervise this command alongside the API, using the same database and storage configuration:

```powershell
python -m backend.app.worker
```

`--once` processes one bounded iteration for an operator. Graceful shutdown stops polling; work not completed before process termination becomes eligible after its lease expires. Database migrations remain the existing Store startup boundary; deployments should run migrations before starting concurrent API/worker replicas.

## Ownership

| Module | Current service boundary | Owned mutations |
| --- | --- | --- |
| Execution | `WorkflowStore`, `Outbox` | Job claim, renewal, retry, cancellation and delivery |
| Interactive generation | `GenerationStore`, generation service | Stream lifecycle and replay events |
| Assessment | `QuizService` | Quizzes, presentations, grading, attempts and position |
| Learning state | `LearnerStateService` | Current state events and projections |
| Materials | `MaterialService` | Source versions, extraction jobs, searchable blocks |
| Notes | `WorkspaceNoteService`, `StudyNoteService` | User notes and approved tutor updates |
| Lectures | `LectureService`, lecture pipeline | Audio metadata, transcript segments and derived note blocks |
| Courses | `CourseService` | Course records and membership context |

Identity, evidence ledger, canonical concepts, academic data and planning services are subsequent 2.0 components. Their tables are not fabricated here. Consumers use owner service APIs or emit durable work; they must not directly update another module's projections.

## Job contract and fencing

`learning_jobs` retains existing IDs and API shape and adds input revision, attempts, retry time, progress, cancellation state and safe error code. Claim uses an atomic conditional UPDATE, which preserves SQLite's single-writer behavior and is safe under PostgreSQL concurrent claimers. An active lease lasts fifteen minutes and is renewed once a minute during execution. Cancellation clears the lease immediately. Completion requires the same live lease; expired workers cannot commit the learning command. Lecture transactions additionally validate the active execution context before any mutation.

Provider preparation happens outside the command commit transaction. Existing assessment services retain their revision checks; `input_revision` records the submitted expected revision. Each future handler must validate its own source revision as well as its lease before committing derived output. A lease does not establish source freshness.

Transport timeouts/network errors and HTTP 408/429/5xx retry with exponential backoff and jitter, capped at five attempts. HTTP authentication/permission failures and unclassified or invalid-input failures stop for attention. Error codes do not include prompts or source text. Explicit lecture retry resets retry metadata. Provider execution is at least once and may incur duplicate provider cost after a crash.

## Transactional follow-up delivery

`Outbox.emit` takes the authoritative command's connection. Deduplication is owner-scoped, and conflicting payload reuse fails the whole transaction. Learning completion events commit with the quiz result. Lecture regeneration commits an `execution.job.requested` event with the updated recording state. Delivery atomically creates its idempotent job and marks the event delivered; a crash rolls both back. Audio chunk metadata and its transcription job now commit together.

Outbox consumers run short database-only operations. Never call providers or storage from an outbox handler: create a durable job instead. PostgreSQL uses `FOR UPDATE SKIP LOCKED` for delivery and SQLite uses `BEGIN IMMEDIATE`. Unknown topics remain pending until their owning consumer is registered. Current learning-completion delivery records dispatch in operational logs; future evidence/planning consumers must use dedicated topics and must not mistake this notification for a learner-state rebuild.

## Projection freshness

`ProjectionWatermarks.advance` commits a monotonic owner/projection/target revision with projection mutations. `status` returns `pending_analysis` when it has not reached the required revision. Future context/readiness consumers must catch up, recompute the required small state, or expose pending analysis. These APIs are foundations; no new learner-state reducer or readiness calculation is introduced by feature 01.

## Compatibility and rollout

### Immutable binary storage

`object_store.py` defines one immutable put/read/delete protocol. Local storage publishes an fsynced temporary file using atomic create-without-overwrite and rejects conflicting reuse. The S3 adapter uses conditional object creation and SHA-256 metadata; it accepts an injected client or uses the SDK credential chain. No credentials are stored in object keys. Configure `OPENLEARN_OBJECT_BACKEND=s3`, `OPENLEARN_OBJECT_BUCKET`, optional `OPENLEARN_OBJECT_ENDPOINT`, and optional `OPENLEARN_OBJECT_PREFIX`. Install the backend requirements in both processes. Buckets must support conditional writes.

The lecture compatibility adapter retains existing owner/recording/chunk keys and the local recordings directory. Selecting S3 does not silently upload old files: migrate existing objects preserving those keys before switching a deployed database. Legacy whole-class recordings and material blobs retain their current storage paths; they can adopt the shared protocol when their respective feature migrations address downloads, retention and export together.

Whole-class recording execution now uses the same durable jobs and lease fencing, including recovery of preexisting queued/processing rows. An API restart no longer blindly resets another worker's active recording. Deleting a recording revokes its job lease before deleting metadata.

Migration `0028_execution_foundation` adds metadata without renaming current jobs, quiz records or generation streams. Existing manual retry paths must reset attempt/error scheduling metadata when returning a failed job to queued. The shared object storage contract and lecture compatibility adapter are implemented separately in the same change.

Static parsing and code inspection are performed during implementation. No automated tests, provider requests, live database migrations or production recovery experiments were run for this task. Crash recovery, hosted PostgreSQL concurrency, object-storage credentials and real provider failure behavior need explicit execution verification before production rollout.
