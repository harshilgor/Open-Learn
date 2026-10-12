# P14–P16 implementation notes

Updated: 2026-10-11. Implementation is prepared locally; the free production
blueprint remains active. No paid Render service was created or deployed.

## P14 — Independent generation execution

- Added the supervised `generation` hosted role. It runs its own
  `GenerationManager`, provider streams, lease heartbeats, recovery loop, and
  bounded shutdown drain.
- In external worker mode, API processes persist and return accepted/queued
  generation receipts, but do not schedule model work. Existing durable
  generation rows, idempotency, owner fencing, usage admission, and event replay
  remain the source of truth.
- The worker claims work through the existing transactional capacity lease.
  Graceful shutdown stops new claims, gives active streams up to 20 seconds to
  finish, flushes their checkpoint, and marks unfinished work interrupted. A
  hard crash is reconciled after lease expiry. Neither path silently retries a
  provider stream that cannot resume exactly; partial output remains available
  and another provider charge requires an explicit learner retry.
- Added the worker to the already inactive paid Virginia proposal only. The
  free `deploy/render.yaml` stays on embedded execution because Render does not
  offer free background-worker instances.

## A01 — Shared notification decision

**Decision: PostgreSQL `LISTEN/NOTIFY`; defer managed pub/sub.** The application
already depends on PostgreSQL for durable jobs and replay. PostgreSQL wakeups
add no broker, billing line, or second source of truth. Notifications carry only
generation IDs and are emitted by database triggers in the same transaction as
the durable event/queue/cancellation change. PostgreSQL delivers them after
commit. The listener reconnects with backoff; SQL replay and bounded polling
cover missed notifications and listener outages.

The listener reserves one connection from each enabled process's existing
bounded SQLAlchemy pool. That is a real capacity cost. Therefore the feature is
off by default and is enabled in the inactive external-worker proposal, where
P05 role budgets can be requalified. It remains off in the live free API's
five-connection shared pool. Render Key Value is deferred: it would add another
service and operational failure mode, while the existing durable SQL events
already satisfy correctness. Revisit only if measured notification fan-out or
database connection pressure fails P15's latency budget.

## P15 — Shared wakeups and fallback

- Added PostgreSQL triggers for committed generation events, new queued work,
  freed capacity, and cross-process cancellation.
- A process-wide listener wakes all local SSE subscribers for a generation and
  asks a generation worker to claim queued work or honor a remote cancellation.
- Notifications never carry answer text. Subscribers always query the durable
  ordered event log before delivering events. When enabled, the listener
  reconnects with exponential backoff and subscribers poll at most every five
  seconds; with notifications disabled, existing 500 ms polling remains.
- Added schema migration `0084_generation_shared_wakeups` and the matching
  release-contract capabilities. SQLite development does not install PG
  triggers and retains its polling path.

## P16 — Fair admission and process isolation

- The generation worker is an independent process role, with a separate
  five-connection default pool budget. Existing learning, agent, browser, class,
  and reminder roles remain separate worker entry points.
- Generation admission is bounded by 20 queued items per owner and 500 queued
  globally by default. Limits have safe upper clamps and produce a clear 429
  capacity response instead of accepting unbounded work. Idempotent replays do
  not consume additional queue slots.
- Queued work expires after 15 minutes by default (configurable within a bounded
  range) and receives a visible `QUEUE_EXPIRED` failure. Generation work has no
  automatic provider retry; manual retry remains an explicit learner action.
- Active work is capped at two per owner by a new transactional owner capacity
  reservation, in addition to the existing conversation and deployment caps.
  A migration marker prevents old leases from decrementing the new owner
  counters during rollout.
- Queue selection rotates through each owner's first queued item before
  admitting that owner's next item, preserving FIFO order per owner and
  preventing one account from filling the worker's first claim batch.
- Database row/claim contention is unchanged beyond the short serialized queue
  admission check and existing capacity rows; P02 concurrency measurements must
  determine whether admission locking or further partitioning needs redesign.

## Activation and evidence still required

1. Apply the release-owned migration to a compatible environment.
2. Requalify P05 connection totals with one generation worker and listener
   connections before enabling the inactive paid proposal.
3. Run P02 correctness and load scenarios for idempotent retries, API restarts,
   worker SIGTERM/crash, stale leases, replay gaps, notification reconnect,
   cross-process Stop, owner limits, fairness, and queue overflow.
4. Compare accepted, first persisted text, and browser delivery p50/p95/p99;
   report queue time separately from context and provider time.
5. Deploy only after the free-hosting choice changes and coordinated P04
   release/rollback gates pass.

No production performance improvement is claimed from the local implementation.
