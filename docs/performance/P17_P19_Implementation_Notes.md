# P17–P19 implementation notes

Updated: 2026-10-11. Changes are local and have not been deployed. Production
measurements and the P02 correctness/performance qualification remain the gates
for enabling any provider or storage architecture change.

## P17 — Frontend update work

- `GenerationStream` coalesces adjacent `text.delta` events for the same
  generation and block into at most one UI callback every 40 ms. Other event
  types flush the pending text first, so block boundaries, cancellation, errors,
  and completion keep their existing order. The durable sequence cursor advances
  with the displayed batch; after a disconnect, server replay remains the source
  of truth for any unacknowledged events.
- The reminder-message refresh pauses in a hidden browser tab and refreshes when
  the tab becomes visible. This removes background polling while retaining a
  current foreground view.
- Browser-task list refreshes now share an in-flight request for the same
  session and account generation. Poll, event, and submission triggers no
  longer launch duplicate simultaneous snapshots; a response from a previous
  account generation cannot overwrite current task state.
- Large Quiz, Flashcard, In-Class, Reminder, Visualization, lecture-note, and
  compact tutor components are split into feature chunks and loaded when first
  opened. Once a user visits a tab, it remains mounted so its local state and
  active work are preserved. Notes stay eager because they are the default
  workspace surface. No transcript virtualization was added without profile
  evidence.
- Reduced-motion support already existed in the chat greeting and remains
  intact. Full transcript virtualization and shared cross-tab generation
  streams are deferred until traces show those costs are material. Each tab
  currently keeps its own authenticated replay cursor, and a
  leader-tab design must prove that hidden-tab suspension and reconnect cannot
  delay or lose another tab's view.

## P18 — Context and model path

- The context engine still applies its existing input budget, required context,
  recent-turn window, ranked evidence selection, and omission provenance.
- Partial evidence selection now counts the growing serialized JSON array
  incrementally instead of serializing the entire selected prefix for each
  candidate. That changes context accounting from repeated prefix serialization
  to one serialization per candidate, without changing item order or the
  conservative token estimate.
- No model route or prompt-cache option was changed. The available production
  evidence is two successful prompts and is not a model comparison or a quality
  qualification. Prefix caching is provider/model specific; changing the payload
  or downgrading the model before a representative P02 quality/latency/cost
  benchmark could change answers without demonstrated benefit. Keep the current
  route and selected context until that benchmark is available.

## P12 follow-up — Generation admission

- Normal chat generation carries its selected Buddy presentation (`ask`,
  `conversation`, or `learn`) inside the same idempotent durable acceptance
  command that stores the learner turn. The presentation is persisted in the
  same transaction before response context is prepared, removing a separate
  browser-to-API mode write for each generation.
- Existing Buddy/course attribution remains unchanged; a missing chat binding
  is initialized using the course Buddy or account default. The initial Learn
  path still persists Learn presentation because it first creates a Journey
  through a distinct command. Explicit mode changes still save immediately.
- The request hash omits this new optional metadata to preserve retries from
  clients that accepted the same message before this field existed. Mode
  classification remains after attachments and URL preparation; its
  state-changing recommendation is not moved ahead of fallible preparation.
- Ordinary Ask/Learn messages now use one generation endpoint request for mode
  classification and generation admission. The descriptor carries advisory
  suggestions, or returns a `mode_choice` response when explicit confirmation
  is required. The transition receipt is stored with owner/session/client
  message identity, so a lost response replays the same offer; dismissal resumes
  that same outbox message with its bypass ID. Confirmation and mode revision
  checks remain in the existing transition interaction path.
- Browser control actions and first-turn Learn Journey planning still use their
  dedicated workflows because they have separate durable side effects and
  acceptance contracts. The old mode-classification endpoint remains for
  those clients and compatibility. End-to-end P02 routing/replay qualification
  remains open.

## P19 — Uploads, object cleanup, and retention

- Keep the existing API-mediated direct upload for files up to 50 MiB and the
  resumable chunk route above that limit. It already scopes sessions to owner,
  material, and class intake; bounds sizes; checks each part's SHA-256; verifies
  the assembled bytes; expires resumable sessions after 24 hours; and cleans
  abandoned parts when new large uploads arrive.
- Added `object_cleanup_queue` (`0085_object_cleanup_queue`). Chunk object keys
  are now committed to the retry ledger in the same transaction before expired
  session/part references or completed part rows are removed. Deletes are
  idempotent; failures remain queued with a five-minute retry delay. The
  material worker drains the queue in bounded batches. This closes the prior
  gap where storage delete failures became untracked objects.
- Direct browser-to-object-store upload is deferred: no upload latency/volume
  distribution demonstrates that API transfer is the bottleneck, and the
  existing object-store contract does not expose scoped, expiring upload
  capabilities. Revisit when upload bytes and API transfer time are instrumented
  and large uploads measurably affect API capacity. Any future signed upload
  must bind owner, material/version, key, byte limit, checksum, and expiry, then
  verify server-side before ingestion.
- Retention rule: do not prune generation events or active/recoverable job
  checkpoints. Keep generation replay data needed by active streams and preserve
  existing operation/usage receipts. Upload chunks are temporary and removed on
  completion or expiry through the retry queue. Broader terminal event/artifact
  retention remains disabled until replay windows, legal/product retention
  requirements, and storage growth are measured; never introduce a TTL that can
  break replay or uncertain-effect recovery.

## Rollout and remaining evidence

- Apply migration `0085_object_cleanup_queue` through the release migration job
  before deploying code that uses the queue. Release contract now requires
  schema head `0085_object_cleanup_queue` and capability
  `object-cleanup-queue-v1`.
- Keep deployment on the current free hosting setup. No production release or
  paid service was activated by this work.
- No tests were run in this implementation turn. Before release, qualify
  stream batching/replay ordering and cleanup retry/recovery on SQLite and
  PostgreSQL, then compare visible update cadence, main-thread work, API upload
  time, and object-cleanup backlog under P02 workloads.
