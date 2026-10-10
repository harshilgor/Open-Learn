# Live Branching and Parallel Response Generation: Execution Plan

**Source:** OpenLearn Live Branching Technical Report, version 1.0, 9 October 2026
**Status:** Durable branch-aware acceptance is active; multi-generation scheduling remains disabled by `LIVE_BRANCHING_ENABLED=false`. Code-level stages 0–6 are implemented; rollout acceptance and several environment-dependent gates remain open. Updated 10 October 2026.
**Scope:** Let a learner send follow-ups while Buddy is responding, durably accept them, and produce isolated alternative or revised answers without losing prior work.

## Implementation status

This execution record follows the complete source plan below. It distinguishes code present in this checkout from validation that requires CI or the deployed PostgreSQL worker topology.

| Stage | Status | Evidence / remaining gate |
| --- | --- | --- |
| 0 — Audit and decisions | Complete | Existing FastAPI/SQLAlchemy/SSE stack retained; Render deployment topology and provider usage accounting were inspected. Branch-scoped context, generation-scoped SSE cursors, selected-answer CAS, and DB-backed leases/capacity are documented in code. |
| 1 — Durable inbox/outbox | Implemented | Stable client message IDs, durable accepted receipts/events, ordered conversation sequences, duplicate-safe submission, reload recovery, and queued/sending/accepted/failed/choice client states. |
| 2 — Branch model and fencing | Implemented | Alembic `0082_live_branching` adds durable inbox, branches, heads, snapshots, leases/fences and bounded capacity; stale owners are rejected; `0083_live_branching_observability` adds aggregate operational counters and outbox snapshots. |
| 3 — Concurrent manager | Implemented behind flag | DB capacity permits two generations per conversation by default and a configurable deployment cap; output and event cursors are generation-scoped; text is persisted in bounded batches (120 characters or 300 ms by default), with cancellation-safe final checkpointing. Provider cancellation is best effort. The real simultaneous-stream integration test is skipped by this restricted Windows asyncio/socketpair environment and must pass in normal CI before rollout. |
| 4 — Relation and context policy | Implemented | Deterministic ADD/CLARIFY/REVISE/NEW_TOPIC/CANCEL/UNCERTAIN routing; explicit cancellation is targeted; branch context follows ancestors and excludes sibling/new-topic output. Relation confusion research and user-reported correction workflow remain rollout measurements. |
| 5 — Branch API/SSE/UI | Implemented | Per-generation response cards, branch selection, queued/running/terminal states, partial output, Stop/Stop all, live follow-ups, replay/recovery, and linked “Ask again” execution retries. SSE observer attachment no longer relies on removed disconnect-grace state. Keyboard/screen-reader usability still needs a human accessibility pass. |
| 6 — Recovery, security and operations | Code implemented; runtime gates open | Startup/periodic lease recovery, cancellation-over-failure precedence, owner checks, retry with a new generation linked to the accepted message, token/cost accounting, and token-protected aggregate metrics are present. Each provider worker binds the verified owner and conversation/session usage root, including queued/recovered work. PostgreSQL multi-worker restart/replay and staging acceptance are still required. |
| 7 — Optional optimizations | Deferred by design | No cache/reuse/duplex optimization is included until stages 0–6 meet their runtime gates and measured quality/cost data justifies it. |

Operational metrics are available at `GET /v1/operations/live-branching/metrics?hours=24` when `LIVE_BRANCHING_METRICS_TOKEN` is configured, using `X-OpenLearn-Metrics-Token`. The response contains only aggregate data and short pseudonymous conversation keys; client outbox telemetry sends status counts and oldest pending age only, never message text. Snapshots are shown only while fresh (90 seconds) and purged after 24 hours. Leave the metrics token unset to disable the endpoint.

### Validation snapshot — 10 October 2026

- `backend/tests/test_live_branching.py`: 21 passed, 1 skipped. The skipped simultaneous-stream integration uses asyncio socket pairs, which block in this restricted Windows environment; run it in supported CI.
- `backend/tests/test_generation_infrastructure.py`: 2 passed, 1 skipped. The skipped async event-buffer test uses the same restricted socket-pair path.
- `python -m compileall -q backend/app/generation_service.py backend/app/generation_store.py backend/tests/test_live_branching.py`: passed after the final cancellation/checkpoint changes.
- `web/tests/chat-outbox.test.tsx`: 6 passed.
- Targeted ESLint: no errors; two existing `react-hooks/exhaustive-deps` warnings remain in `learn-chat.tsx` (`onMissingSession`, `submit`).
- `npx tsc --noEmit` still fails on stale generated `.next/types/validator.ts` route exports and unrelated existing mocks in `browser-assistant.test.tsx` and `quiz-quality.test.tsx`; it reports no errors in the changed UI/API files.
- A full PostgreSQL multi-worker restart/replay run and human accessibility review were not available in this workspace.

Before enabling concurrency in production, run the skipped integration test in supported CI, exercise restart/replay with at least two PostgreSQL-backed workers, review the aggregate metrics in staging, and complete the keyboard/screen-reader pass. `LIVE_BRANCHING_ENABLED=false` preserves one active generation per conversation, but durable branch-aware acceptance and persistence already run in serial mode; setting it to true enables the configured parallel limit. This is the compatibility boundary in the current implementation because the legacy generation path is no longer a separate runnable implementation.

## Product outcome

The learner can send a follow-up during generation and receive an immediate durable acceptance. OpenLearn may then run multiple complete responses concurrently. Every response uses an immutable context snapshot and has its own branch, output buffer, event identity, and lifecycle. A late response can never silently replace the currently selected answer. Messages, queued work, and partial output survive reloads and recover safely after worker restarts.

## Guardrails from the report

- Keep the first implementation in the existing FastAPI modular monolith, SQLAlchemy/Alembic persistence, React/TypeScript client, and SSE transport.
- Reuse and extend existing generation, event, and conversation stores. Do not add Redis, a separate queue service, a new agent framework, or duplicate tables without measured need.
- Persist every user message before classification, scheduling, or model work. A full generation slot must queue work, never discard or reject the message.
- Keep branch selection independent from generation completion. Preserve older output and make its status visible.
- Bound parallel work. Initial target: two full generations per conversation plus a deployment-wide budget.
- Do not hold database transactions or conversation locks while waiting on a model provider. Do not use an in-process lock as a multi-worker correctness guarantee.
- Do not promise exact provider decoding resumption after restart. Save checkpoints and, if needed, create a new generation that may use prior text as optional draft context.
- Do not add an LLM merge step, unbounded parallelism, or per-token database rows in the first release.

## Repository facts that shape the build

Reconfirm these facts during Stage 0 because the working tree and deployment can change:

- **backend/app/generation_store.py** persists generation_records and durable per-generation generation_events; its create path currently rejects another active generation for the same conversation.
- **backend/migrations/versions/0021_one_active_generation.py** enforces a partial unique active-generation index for owner and session. It must not simply be deleted before safe multi-generation ownership and state transitions exist.
- **backend/app/generation_routes.py** currently invokes interrupt_active() when the router is built. **GenerationStore.interrupt_active()** marks active records interrupted without a stale-owner lease check. Replace this blanket startup behavior with safe reconciliation.
- **backend/app/generation_service.py** owns live streams in a process-local task map. This is acceptable only with a single owning worker or additional database-backed lease/fencing primitives for multi-worker deployments.
- **backend/app/journey_service.py** submits, prepares, and commits a stream against a specific Journey revision and shared mutable turn state. Concurrent generations need independent immutable snapshots and isolated result commits; loosening the active-generation constraint alone is unsafe.
- The existing branches table is used for learner study sidecars, not competing assistant responses. Do not overload it with response-branch semantics.
- **web/hooks/use-chat-outbox.ts** and **web/lib/chat-outbox.ts** keep the outbox in sessionStorage. Restored entries are currently marked failed, and **web/components/learn-chat.tsx** serializes sending behind busy. Make outbox recovery and server acceptance correct before enabling concurrent generation.

## Stages and exit gates

### Stage 0 — Repository audit and decisions

**Purpose:** Confirm the design against the current code and deployment before migration or behavior changes.

**Work**

1. Trace ORM models, migrations, generation routes/store/manager, Journey read/write semantics, provider adapter, event replay, current outbox, cancellation, and startup/shutdown hooks.
2. Record actual generation statuses, idempotency keys, event sequence scope, checkpoint format, route request/response contracts, and existing constraints. Map each conceptual report entity to an existing table or document why an additive table/field is needed.
3. Confirm deployment worker/process topology, database type, and whether a durable owner lease/fencing token already exists. An in-process semaphore is not a deployment-wide budget across multiple processes.
4. Verify provider streaming cancellation, idempotency, timeout/unknown-outcome handling, and whether provider requests can be reconciled or resumed.
5. Baseline message acceptance latency, first-token latency, token cost, interruption rate, and queue behavior before choosing numeric SLO or spend thresholds.
6. Decide and document: generation/event cursor model; selected-answer and alternatives presentation; per-user/conversation token budget; explicit Stop semantics; global concurrency enforcement mechanism; classifier fallback behavior.

**Recommended starting decisions:** retain generation-scoped cursors to fit the current per-generation event store; show the selected answer prominently and keep earlier versions accessible but collapsed; make Stop target the selected generation and provide a separate Stop all; use deterministic cancel detection and conservative branching for uncertain relations.

**Exit gate:** A reviewed schema/API mapping and migration plan exists; worker topology and consistency mechanism are known; no duplicate store or unsafe removal of the one-active-generation constraint is proposed.

### Stage 1 — Durable message inbox and correct outbox semantics (PR 1)

**Purpose:** Make message acceptance immediate, idempotent, and independent of model completion.

**Work**

1. Extend the existing message/generation route contract to accept a stable client message ID, text, optional reply-to-generation ID, and mode. Use that ID as the idempotency key.
2. Validate conversation ownership, append the user event, assign a monotonically increasing per-conversation sequence, and persist the acceptance before starting asynchronous work.
3. Return an accepted receipt promptly with server message ID, conversation sequence, context revision, accepted=true, and scheduled/active generation IDs. A duplicate key returns the original receipt and never creates a second logical user message. Send the same ID as the Idempotency-Key header and client_message_id body field.
4. Make client outbox states explicit: queued, sending, accepted, and failed. On reload, send queued entries after reconnect; query or retry sending entries with the same key because the result may be unknown; reconcile accepted messages separately from generation status; expose retry/edit only for confirmed failures.
5. Keep the composer enabled for supported follow-ups. Show the optimistic message immediately, then reconcile it with the durable receipt. Do not block unrelated queued messages indefinitely on a failed item.
6. Add compatible, additive schema changes only after Stage 0 mapping. Prefer existing event/message storage; introduce only missing idempotency or revision fields. Backfill only where historical source data is trustworthy; never fabricate provider request IDs.

**Exit gate:** Reload/retry and unknown-request-outcome scenarios produce one logical user message per client ID; queued messages remain queued until actually submitted; server acknowledgement does not wait for model generation.

### Stage 2 — Branch model, immutable context, and ownership primitives (PR 2)

**Purpose:** Represent each answer independently and make stale writes impossible before allowing concurrency.

**Work**

1. Add or map the report concepts to current persistence:
   - Append-only ConversationEvent: conversation, sequence, event type/payload, creation time, client message ID.
   - ResponseBranch: conversation, parent branch, triggering message, relation, branch status, creation time.
   - Generation: conversation, branch, immutable context revision, triggering message, optional parent generation, execution status, owner fence, output sequence/checkpoint, error code, timestamps.
   - Branch selection/head: selected branch and expected revision, separate from generation completion.
   - Client outbox receipt state where server-side reconciliation is needed.
2. Add unique constraints for conversation/client-message ID and conversation/sequence; indexes for conversation/status/creation time, branch/creation time, and generation/sequence replay; foreign keys to conversation and triggering event. Keep history via status transitions rather than deleting it.
3. Add atomic compare-and-set transitions for ownership, output checkpoint, and terminal state. Every update verifies current status, owner fence, and expected output/revision sequence. Reject stale writers.
4. Introduce a database-backed lease/fence if more than one worker can own a stream. Establish how worker ownership is renewed and how it expires. Local locks may reduce contention but cannot replace this guarantee.
5. Store output in bounded checkpoints or chunk batches, not one row per token. Keep database transactions short and never hold one while awaiting provider I/O.
6. Migrate in compatibility order: additive nullable columns/tables, safe backfill of well-sourced history, dual read compatibility, feature-flagged branch-aware writes, then later removal of legacy assumptions after telemetry supports it.
7. Replace the active-generation uniqueness rule only as part of the tested transition to a bounded multi-generation policy. Do not leave the system briefly without an active-work limit.

8. Keep generation execution lifecycle distinct from branch presentation: queued, accepted, running, completed, interrupted, and failed describe execution; superseded describes branch preference and may coexist with a still-running generation.

**Exit gate:** Concurrent state-transition tests prove that only the current owner/revision can write; selected-head updates require an expected revision; old chat reads remain compatible; no legacy learner-sidecar branch table is repurposed.

### Stage 3 — Bounded concurrent generation manager and scheduler (PR 3)

**Purpose:** Run independent full responses at the same time while preserving capacity and cancellation controls.

**Work**

1. Build the coordinator, scheduler, and generation-manager responsibilities inside the current backend: create immutable context snapshots, persist queued work, admit jobs, own provider streams, checkpoint output, handle errors/cancellation, and publish terminal state.
2. Support at least two simultaneous full-response generations per conversation by default. Enforce a configurable deployment-wide budget using a cross-worker-safe mechanism when deployment has multiple owners.
3. Prioritize by explicit user intent, relation, age, and selected branch. When capacity is full, keep the accepted message and expose queued/waiting state. Any resource-reclamation cancellation/deprioritization must be observable and reversible where possible.
4. Keep separate buffers, sequence counters, context revisions, and branch identities for each generation. A newer generation may become preferred through an explicit conditional selection update; an older generation completing later cannot switch the selected answer.
5. Extend the provider-neutral adapter with stream, best-effort cancel, and capability metadata. Cancellation is a request; report terminal confirmation separately.
6. Check generation status and owner fence before persisting or publishing every checkpoint, late delta, failure, and completion. After cancel, stop consuming/publishing stale chunks and propagate cancellation to tools.
7. Checkpoint text in batches (initial guide: every 250–500 ms or configurable token count); allow SSE chunks to remain smaller for perceived responsiveness.
8. Keep the serial implementation available behind a cohesive feature flag. Enable concurrent scheduling only after isolated-state and recovery gates pass.

**Exit gate:** Two full generations demonstrably stream at once with independent output; out-of-order completion cannot corrupt the selected answer; late events are ignored after cancellation; capacity limits work across the real worker topology.

### Stage 4 — Relation controller and context policy (report Phase 3; PR 5 scope)

**Purpose:** Interpret follow-ups without making message acceptance wait on classification or risking destructive mistakes.

**Work**

1. Implement relation categories ADD, CLARIFY, REVISE, NEW_TOPIC, CANCEL, and UNCERTAIN.
2. Detect explicit stop/cancel language deterministically first. For other messages, use deterministic rules and a low-cost schema-validated classifier only where useful; do not call a strong model for every follow-up.
3. Run classification after durable acceptance. If classification is delayed, start a provisional branch with the latest full context; later relation metadata may be refined without changing the immutable context snapshot.
4. Define branch/context behavior:
   - ADD: preserve the current response and create a separate/additive response using relevant context.
   - CLARIFY: retain the old answer and create a full response from the original request plus clarification; prior partial output may be optional draft context.
   - REVISE: create a corrected/reformatted branch and prefer it for the main view without deleting prior output.
   - NEW_TOPIC: create an isolated topic branch without irrelevant partial output.
   - CANCEL: persist the explicit control event, cancel only targeted generation(s), and confirm whether cancellation completed or the response had already finished.
   - UNCERTAIN: preserve existing output and conservatively branch subject to limits; low confidence alone never cancels work.
5. Persist every user message and event even when a short burst is coalesced into one generation context snapshot.
6. If prior text is reused, delimit it as a draft for possible reuse. The new generation may correct, omit, or replace it; it is not an exact continuation prefix.
7. Measure classifier confusion and fallback behavior against representative follow-ups.

**Exit gate:** Tests cover corrections, additions, clarifications, topic switches, explicit cancellation, ambiguous follow-ups, delayed classification, and burst coalescing without losing/reordering input.

### Stage 5 — Branch-aware API/SSE and chat UI (PR 4)

**Purpose:** Make every concurrent answer understandable, separately streamable, selectable, and recoverable in the product.

**API and event work**

1. Adapt existing routes rather than creating duplicate endpoints. Support the report's logical contracts using current route conventions: POST conversation message with idempotency key/client message ID, text, optional reply_to_generation_id, and mode; POST generation cancel with a reason and a cancel_requested receipt; GET conversation branches; POST branch selection with expected_branch_revision. Message acceptance returns message ID, conversation sequence, context revision, and scheduled/active generation IDs without waiting for generation. Cancellation means requested, not instantly stopped; report the terminal result separately. Check that the generation belongs to the authorized user and conversation.
2. Keep existing SSE heartbeat and Last-Event-ID behavior. Choose exactly one cursor model and document/test it. Recommended initial fit: separate per-generation cursors, matching the current generation-event store.
3. Extend events with the IDs needed to route and reconcile state:
   - message.accepted: message ID, conversation sequence, context revision.
   - generation.queued / started: generation ID, branch ID, queue reason or context revision.
   - generation.delta: generation ID, branch ID, monotonic sequence, delta.
   - generation.checkpoint: generation ID, output sequence, persisted length.
   - generation.completed / interrupted / failed: generation ID, final sequence or reason/partial-output availability/retryable safe error code.
   - branch.updated: branch ID, relation, status, selected state.
4. Never infer current branch from event arrival order. Never concatenate deltas from different generations. Review retention/compaction because the current SQL event store already persists per-generation events and duplicate unbounded token storage must be avoided.

**UI work**

1. Keep the composer active for eligible follow-ups. Render each sent user message immediately; reuse its client ID on retry.
2. Show status/activity per response card rather than one conversation-wide spinner. Provide separate Stop selected and Stop all actions.
3. Implement clear states:
   - Running: stream into its own response card with branch-specific progress.
   - Completed and selected: show as the current answer.
   - Completed but superseded: preserve under an accessible “Earlier response” / alternative version treatment.
   - Interrupted: preserve partial text, label it, and offer regenerate/continue as a new generation.
   - Failed: show a non-blocking actionable error and retry without blocking other branches.
   - Queued: show “Waiting to generate” while preserving acceptance and message order.
4. Render ADD as a separate reply; render revision as a new version while keeping the previous answer accessible.
5. On reload, reconcile accepted messages separately from execution state, rehydrate current branch/generation state, and reconnect from the durable cursor.
6. Before finalizing branch presentation, review current competitor patterns for multiple answers, streaming progress, and version history; keep the chosen behavior consistent with OpenLearn’s selected-answer model and verify it with learner feedback rather than copying interaction chrome blindly.

**Exit gate:** No cross-branch token mixing; reconnect replays missed events; selection remains stable under out-of-order completion; all six response states are usable by keyboard and screen reader; reload reconstructs accepted messages and current branch state.

### Stage 6 — Restart recovery, retries, security, telemetry, and rollout (PR 5 completion)

**Purpose:** Make the feature safe in real worker, network, and provider failure conditions.

**Recovery and retry work**

1. On startup/recovery, find active records with stale owner leases/heartbeats. Reclaim ownership safely before marking execution interrupted; never interrupt a live generation owned by another worker.
2. Preserve last checkpoint, generation ID, accepted user message, and branch state. If provider request state cannot resume, create a new retry generation linked to the interrupted one and optionally use saved text as context.
3. Reconcile queued work and durable messages independently. A generation interruption never marks an accepted user message failed.
4. Use cooperative, best-effort provider cancellation. Reconcile unknown provider outcomes where supported; retry transient failures with bounded backoff only; never silently retry user-cancelled work. A message retry reuses its message idempotency key but execution retry gets a new generation ID.
5. Gate side-effecting tools on current user intent and authorization at commit time. A stale or superseded generation cannot perform external actions merely because it emitted a tool call.
6. Verify ownership on every conversation, branch, generation, cancel, and selection route. Do not expose provider credentials/request IDs, internal chain-of-thought, or raw exceptions in SSE. Enforce per-user and per-conversation rate/token budgets. Review cache isolation for cross-tenant timing/data exposure.

**Operational measurement**

Instrument and expose at least:

- Message acceptance latency, p50/p95.
- Follow-up-to-new-first-token latency.
- Active generations per conversation and deployment.
- Tokens and cost per conversation, including superseded output.
- Stale-write rejection count.
- Outbox age/count by queued, sending, accepted, and failed state.
- Interrupted/failed rates by provider and cause.
- Branch-selection switches and repeated user prompts, interpreted with user research.

**Rollout**

1. Keep branch-aware durable writes compatible with serial operation and use one cohesive feature flag for parallel scheduling. Retain legacy reads; do not pretend a separate legacy writer remains available when it does not.
2. Enable first for development/internal accounts; exercise restart, replay, multi-worker, SQLite, and production-PostgreSQL paths before widening.
3. Compare telemetry to the pre-change baseline; set numeric p95 and token-cost limits after measurement, not by assumption.
4. Define rollback: disable new scheduling while retaining branch history and preserving legacy chat reads. Do not drop new state during rollback.
5. Remove old queue assumptions only after replay/recovery telemetry confirms the new path.

**Exit gate:** Restart recovery passes; no accepted messages are stranded; cancellation and retries are bounded/correct; security checks pass; metrics and feature-flag rollback are available.

### Stage 7 — Optional measured optimizations

Do this only after Stages 1–6 meet the definition of done.

- Evaluate scheduling policy, short burst coalescing, text reuse heuristics, and checkpoint tuning using measured latency, cost, and quality.
- Evaluate compatible prefix-KV caching only when provider/runtime supports it. It can reduce prompt prefill for identical prefixes; it does not remove decode cost for a new response or automatically reuse divergent output.
- Treat duplex/live-state steering as future research requiring a suitable model/runtime and interruption training, not as a drop-in feature or launch dependency.
- Keep parallel-response token overhead observable and configurable; reject optimizations that cause unacceptable answer-quality regression or higher cost per successful interaction.

**Exit gate:** Each optimization demonstrates measured benefit without an unacceptable quality regression or increase in cost per successful interaction.

## Cross-stage test and acceptance matrix

These scenarios are the acceptance matrix for the implementation. Focused tests now cover durable/idempotent acceptance, reply validation, branch classification/context/CAS, stale-owner fencing, stop semantics, linked retry idempotency, stale-write metrics, and outbox/aggregate metrics. The simultaneous-stream test is present but skipped in this restricted Windows session because asyncio socket-pair setup blocks here.

| Scenario | Required result |
| --- | --- |
| Follow-up during active stream | Message is durably accepted before the old response ends; a second generation can start concurrently. |
| Three rapid messages | All events/messages persist in order; queue/coalescing policy is explicit; no accepted input is lost. |
| Clarification mid-answer | Original output remains; new full answer uses original task plus clarification and may use a delimited draft. |
| Additive question mid-answer | Original may continue; additional response appears independently. |
| Older generation completes after newer one | Older result remains accessible but cannot change selected branch without an explicit selection transition. |
| Late token after cancellation | It is ignored for authoritative persistence and UI; terminal state remains correct. |
| Reload with queued outbox item | The queued item sends after reconnect and is not mislabeled failed. |
| Request outcome unknown after timeout | Retry uses same message idempotency key and does not duplicate the user message. |
| Backend restart during generation | Ownership is reconciled, partial output remains, accepted messages reconcile separately, and UI rehydrates/replays. |
| Two workers update same state | Only current owner fence/expected revision may commit; stale writer loses. |
| SQLite concurrent generation | Batched checkpoints avoid excessive contention; no lost output, deadlocked outbox, or unbounded token-row growth. |
| Tool call from superseded work | No side effect commits without current-intent and authorization validation. |
| Feature flag disabled | Legacy chat reads continue and branch history is not lost. |

Initial acceptance targets from the report: message acknowledgement follows durable persistence and does not wait for model generation; two independent full generations can stream in one conversation; all concurrency/recovery scenarios above pass; zero duplicate logical messages and zero cross-branch token mixing in the test suite. Establish numeric p95 latency and spend budgets from measured baseline.

### Explicit rollout limitations

- Run the skipped simultaneous-stream case on supported CI and exercise two PostgreSQL-backed worker processes, restart recovery, and replay before turning on the feature flag.
- There is no exact provider-stream resume after a process restart. The checkpoint is retained and the learner may start a linked retry generation.
- Provider-reported token/cost totals are exact where available; interrupted or cancelled streams may have unknown final usage. The metrics endpoint reports unknown counts instead of treating missing data as zero-cost usage.
- Provider-unavailable submissions are durably accepted as queued work and become eligible when a provider returns; they are not rejected before receipt.
- Each generation binds its verified owner plus session ID as the existing Usage Ledger task root, so work admitted after a request or recovered by another worker uses the same conversation-scoped cap. That cap inherits `OPENLEARN_FREE_CREDITS_MICRO`/the active usage policy grant; there is no separate, smaller live-branching spend ceiling. Calibrate any independent ceiling from staging measurements rather than inventing a number.
- Account-level usage enforcement and per-conversation concurrent-generation limits are in place; tune any independent spend ceiling from measured staging baselines.
- Provider failures are not silently auto-retried. Learners can start a new linked retry with a fresh generation ID; any transient automatic retry policy should be bounded and added only after provider outcome reconciliation is established.
- Outbox snapshots are aggregate status counts and oldest pending age from active browser tabs, with no message text or message IDs. They are freshness-limited to 90 seconds in the metrics response and purged from storage after 24 hours.
- Automated coverage does not replace human keyboard/screen-reader review, learner feedback on branch labels, or classifier correction research.

## Risk controls to carry through implementation

| Risk | Required control |
| --- | --- |
| Parallel work increases token cost | Start with two active generations per conversation; track superseded-output cost; expose stop controls; enforce a global budget. |
| Relation classifier makes a mistake | Persist every message; keep old output; make relations auditable; never cancel on low confidence; measure misclassification. |
| Old generation overwrites a newer answer | Isolated output, immutable context revisions, ownership fencing, and separate conditional branch selection. |
| SQLite write contention | Batch checkpoint writes, keep transactions short, and run concurrent local smoke/stress coverage; evaluate PostgreSQL behavior for deployed multi-worker load. |
| Provider cancellation is delayed or unsupported | Treat cancel as a request; ignore stale late events; stop side effects after supersession/cancel. |
| Branch UI becomes confusing | Distinct branch labels/status, explicit selected answer, no merged token streams, accessible earlier versions. |
| Restart cannot restore exact provider state | Preserve checkpoints and start a new linked generation with optional draft context; describe it as regeneration, not exact continuation. |
| Cache reuse crosses tenant boundaries | Review cache isolation/salts and ensure reuse cannot create cross-tenant data or timing leakage. |

## Research handoff

The report's references inform optional design evaluation, not fixed implementation requirements:

- **Speculative Interaction Agents (2026):** asynchronous reasoning/tool work should react to changed user intent and revise speculative actions.
- **Beyond the Turn-Based Game: Duplex Models (EMNLP 2024):** real-time input/output requires model/runtime and training support; it is not a drop-in capability for ordinary request/response APIs.
- **InferCept:** informs research on preserving, discarding, or swapping inference cache state around external interruptions.
- **vLLM Automatic Prefix Caching:** can reduce prompt prefill for matching prefixes on a compatible runtime; it does not eliminate decoding for a new answer.

Only pursue local experiments after the core durable branch system is correct. The report explicitly requires local evaluation rather than treating these works as proof of the best OpenLearn policy.

## Pull request sequence

1. **PR 1 — Durable inbox/outbox:** idempotent message receipt, queued/sending/accepted/failed recovery, no concurrent generation yet.
2. **PR 2 — Persistence and ownership:** additive migration, branch/generation model mapping, fencing/conditional transitions, repository-level state tests.
3. **PR 3 — Concurrent manager:** two isolated streams behind feature flag, queue limits, cancellation, checkpointing.
4. **PR 4 — Branch UX and replay:** branch cards/status, selected-answer transition, generation-scoped SSE routing and recovery.
5. **PR 5 — Relation/recovery/operations:** classifier and context policy, explicit cancel targeting, stale-lease recovery, metrics, rollout and rollback.
6. **Follow-up only if justified:** measured scheduling/cache/text-reuse experiments or duplex research.

## Final definition of done

- A learner can submit a follow-up while Buddy is generating; the server durably accepts it without waiting for the active response.
- Two full-response generations can stream concurrently and remain isolated in storage, events, and UI.
- Clarifications/revisions may use prior text as optional context; the original answer remains a separate accessible branch.
- A late delta, completion, or failure from old work cannot replace the selected answer.
- Reloads, network retries, and backend restarts do not duplicate accepted messages or strand queued work.
- Concurrency caps, global budgets, cancellation, token cost, and recovery are observable and tested.
- The feature can be disabled by flag without losing branch history or breaking legacy chat reads.

### PDF definition-of-done audit — 10 October 2026

| Report requirement | Implementation status | Evidence / remaining gate |
| --- | --- | --- |
| Accept and persist follow-ups while a response is still generating | Implemented | `generation_routes.create`, `GenerationManager.create`, and `GenerationStore.create` durably accept/idempotently record messages before queued provider work. A missing provider leaves accepted work queued. |
| Stream two full responses without mixing branches, events, or output | Implemented behind `LIVE_BRANCHING_ENABLED` | DB-backed capacity leases and per-generation event/output streams are present. The default remains serial (`false`); supported CI must pass the skipped simultaneous-stream test before enabling parallel execution. |
| Keep clarifications/revisions/new topics isolated and preserve earlier answers | Implemented | `ConversationBranchStore` snapshots branch ancestry and context revision; relation tests cover ADD/CLARIFY/REVISE/NEW_TOPIC/CANCEL/UNCERTAIN. |
| Prevent stale work from replacing the selected answer | Implemented | Owner fencing plus compare-and-set branch selection; late completion does not select a branch. Covered by `test_branch_selection_uses_compare_and_set_and_is_not_changed_by_late_completion`. |
| Recover from reloads, network retries, and backend restarts without duplicate accepted messages | Implemented in code; production topology gate remains | Stable message IDs, outbox retry, durable SSE replay, owner leases, checkpoints, and linked retry generations are present. Validate restart/replay with two PostgreSQL-backed workers before rollout. |
| Enforce/observe cancellation, concurrency, usage, cost, and recovery | Implemented with policy boundary | Shared DB capacity limits, cancellation-over-failure handling, owner-scoped usage contexts, usage ledger accounting, and aggregate operations metrics are present. The session cap inherits the existing usage-policy grant; an independently tuned live-branching spend ceiling still needs a policy decision and staging baseline. |
| Roll back concurrency without losing branch history or legacy reads | Implemented | `LIVE_BRANCHING_ENABLED=false` returns execution to one active generation per conversation while preserving durable branch data and legacy chat reads. |
| Research optimizations (cache reuse, speculative/duplex behavior) | Intentionally deferred | The report treats these as measured research directions, not core release criteria. No local benchmark justifies adding them yet. |

The code-level core requirements are implemented. Release readiness is not fully proven until the CI concurrency case, PostgreSQL multi-worker restart/replay, and human accessibility review pass; parallel execution also remains disabled until that gate is cleared.

## Source and research notes

The complete requirements, example API/SSE payloads, schema concepts, lifecycle diagrams, risk analysis, test matrix, research references, and definition of done are in **OpenLearn_Live_Branching_Technical_Report.pdf** (especially sections 1–14 and appendices A–B). Research in the report motivates asynchronous coordination, interruption-aware models, inference cache preservation, and prefix caching; it does not establish OpenLearn’s optimal policy. Use local benchmarks before selecting optimization or numeric budget thresholds.
