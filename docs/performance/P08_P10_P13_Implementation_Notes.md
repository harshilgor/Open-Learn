# P08–P13 implementation notes

Updated: 2026-10-11. These changes are local implementation work; hosted
performance qualification and a release are still pending.

## P08 — Async request path

- Moved the generation context-snapshot SQL read into `asyncio.to_thread`.
- Reused the generation record already fetched for preparation instead of
  performing another blocking read to obtain its session ID.
- Moved streamed model usage reservation/dispatch and settlement off the API
  event loop. `asyncio.to_thread` preserves the request's usage context.
- Shielded the reservation operation against cancellation; if cancellation
  arrives before the provider request starts, settle the reservation at zero
  rather than leave it held.

## P09 — Database round trips

- Changed `WorkflowStore.listing` from one ID query plus one payload query per
  row to a single owner- and kind-scoped query returning payload and revision.
- Added `/workspace-notes/page` with owner-scoped keyset pagination (50 by
  default, max 100) over `updated_at DESC,id DESC`, using the existing
  `(learner_id, updated_at)` index. The Notes workspace and its note pickers now
  fetch one page and expose Load more instead of reading every Markdown file
  into the first list response. Search remains capped at its existing result
  limit. The full-list route remains available for older clients.
- The generated-title repair endpoint is no longer called synchronously while
  listing or opening notes; that maintenance walked the full note vault on
  routine UI reads. PostgreSQL query plans and lock-duration attribution remain
  open, so no additional index was added.

## P10 — Provider connections

- Reuse one bounded `httpx.AsyncClient` per event loop for streamed provider
  calls. Defaults are 64 total and 16 keep-alive connections; environment
  overrides are clamped to safe positive limits.
- Retain the existing 180-second request and 20-second connect timeouts.
- The stream context closes each response on completion or cancellation.
  API shutdown closes its event loop's client. No automatic stream retry was
  added, avoiding duplicate output or charges after partial responses.

## P13 — Note save independence

- A successful cloud write now remains successful if refreshing the notes list
  fails. List refresh failures use a separate status message and retry button.
- Existing-note PATCH receives at most one retry after 250 ms for transient
  408/429/5xx responses. The API's expected-revision check acknowledges an
  exact replay after a lost response. Note creation is not retried, avoiding
  duplicate notes.
- Existing local recovery is keyed by authenticated owner and editor context.
  On account change, preserve the old owner's unsaved draft, clear the active
  editor, and load only the new owner's recovery draft and note list.
- Revision conflicts remain visible and drafts stay recoverable; local copies
  are never described as cloud-saved.

## P11 — Durable streaming batches

- Added an atomic generation-store operation that updates partial output and
  inserts the ordered `text.delta` plus `generation.checkpoint` events in one
  transaction. Subscribers are notified only after that transaction commits.
- Removed the extra full generation-record read and second transaction from
  each production text flush.
- Added an independent bounded flush timer, so a low-volume fragment is
  persisted within the configured flush budget even if the provider pauses.
- Added a per-generation flush lock and monotonic sequence handling so timer
  flushes cannot reorder durable events or regress the finalization sequence.
- Shielded the event batch's synchronous database write from task cancellation
  and resolve its commit result before replaying a pending buffer, preventing a
  Stop racing a completed database commit from duplicating visible text.
- Reduced durable cancellation polling from every provider delta to a bounded
  interval (`GENERATION_CANCEL_CHECK_MS`, clamped to 100–2000 ms). Explicit
  Stop still cancels the active iterator immediately; finalization still checks
  durable cancellation state.
- First-token timing is now persisted asynchronously so its database write does
  not delay the first visible text. Telemetry remains best-effort.

## P12 — Admission and context routing

- Kept the existing idempotent generation command as the single durable
  acceptance boundary. It returns the accepted generation receipt before the
  provider runs; retry keys still prevent duplicate work.
- Moved the session ownership check into the idempotent acceptance transaction
  and reused that validated session object when creating the first Journey,
  removing a separate connection and duplicate session lookup on new chats.
- Ordinary Ask/Learn generation now runs advisory classification inside the
  generation admission request. The same command returns an accepted receipt,
  an advisory suggestion alongside the generation, or a mode-choice receipt
  when explicit confirmation is required. Dismissal resumes the same outbox
  message ID; acceptance still uses the existing revision-checked transition.
- Branch/passage, course, Buddy, and mode context remain built by the existing
  Journey preparation path from the persisted accepted command and generation
  snapshot. No new parallel queries were added where dependencies or database
  pool pressure could make latency worse.
- Normal generation carries the selected Buddy presentation with the durable
  request and writes it in the acceptance transaction, eliminating a separate
  mode-save HTTP round trip for each message. Existing chat attribution is kept;
  missing attribution resolves to the course/account Buddy. Initial Learn mode
  still saves before its distinct Journey command. The optional field is
  excluded from the idempotency hash so in-flight older clients can retry.
- Independent attachment preparation and URL-material creation in the chat
  composer now run concurrently while preserving attachment order and existing
  cancellation handling.
- Browser control and initial Learn Journey planning remain separate because
  they have distinct durable side effects. The legacy mode-classification
  endpoint remains for compatibility. End-to-end replay and routing acceptance
  still needs the P02 qualification run.

## Validation and rollout

- Python syntax compilation and `git diff --check` passed for the modified
  backend modules and current workspace changes.
- The repository's tests were not run. No hosted latency claim is made from
  these code changes.
- P11/P12 correctness acceptance (stream replay during pauses/reconnect,
  cancellation races, idempotent retries, mode choice, branch/context routing)
  still needs the P02 regression workload before release.
- Compare P02 workloads before and after release, reporting successful and
  failed p50/p95/p99 separately, including note autosave during concurrent
  generation. Preserve the free-hosting choice; P07's paid cutover remains
  deferred.
- Rollback is the normal coordinated release rollback under P04. These code
  changes add no schema and need no database rollback.
