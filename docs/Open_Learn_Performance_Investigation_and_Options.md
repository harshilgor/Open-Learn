# Open Learn: production performance investigation and options

Date: 2026-10-10. Scope: measurement and recommendations only. No application or hosting changes were made for this investigation.

Follow-up: see [Scalable architecture review](Open_Learn_Scalable_Architecture_Review.md) for the subsequent live deployment audit and revised decisions. That audit verified the current Render Free allocation as 0.1 CPU / 512 MB, an Oregon API with a Virginia database, and gaps in the proposed paid deployment. Its current observations supersede historical hosting assumptions below.

## 1. Production measurements

Visited https://open-learn-eta.vercel.app in the user's authenticated Chrome browser. Opened a separate new chat, retaining Conversation mode and Quick depth. Submitted: **Explain why the sky is blue in two sentences.**

| Observation | Result |
| --- | --- |
| First submission | Unavailable warning visible by 1.188 seconds after beginning the Send click |
| First observation window | No assistant answer through 27.029 seconds |
| One explicit retry | Unavailable warning visible by 0.448 seconds; no answer during the approximately 19-second retry observation window |
| Public API /health, first request | HTTP 502; total 0.239235 seconds |
| Public API /health, second request | HTTP 200; first byte 6.021327 seconds; total 6.021367 seconds |

Browser observations were sampled roughly once a second with an external clock. They include browser automation overhead and are upper bounds on when a visible state appeared, not precise network timings. These failed submissions did not produce a valid first-token or completion measurement. They must not be reported as a successful 27-second generation or a population percentile. The health endpoint performs database readiness checks but invokes no language model. Its six-second response is evidence of delay outside answer generation; it does not isolate CPU, database, network, or queue time.

Screenshot: C:/Users/harsh/.codex/visualizations/2026/10/05/01a10ae9-112c-7671-803b-4187d7ba8d61/production-latency-measurement.png

Earlier production investigation identified intermittent database_busy errors and Render health-check timeouts. Those are historical findings, distinct from this run. The previously inspected backend was Render Free, 512 MB and 0.15 CPU. This run did not re-inspect its hosting configuration.

## 2. What fractions of a millisecond can mean

A complete remote AI answer cannot have a sub-millisecond guarantee. User-to-server transit, database access, provider queueing, prompt processing, and token generation all take time. Even a 60 Hz display presents frames about 16.7 ms apart. Small local computations can take fractions of a millisecond, but that is not the user's observed answer latency.

Proposed warm-service targets, subject to baseline measurement and capacity validation:

| Experience | Initial target |
| --- | --- |
| Local typing, navigation feedback, outgoing bubble | Under 50 ms for feedback; no main-thread stalls |
| Local note recovery persistence | Within 100 ms of a debounced edit |
| Message acceptance, excluding a required user decision | p50 under 250 ms; p95 under 750 ms |
| First meaningful generated text on an ordinary short question | p50 under 1 second; p95 under 2.5 seconds |
| Cloud note save, excluding intentional debounce | p50 under 300 ms; p95 under 1 second |
| First stream delivery after provider text arrives | Under 100 ms application overhead at p95 |

These are engineering goals, not achieved numbers or provider guarantees. Completion time depends on requested output length and task complexity. Track failures separately, including failed acceptance and failed streams, to avoid making latency look better by excluding outages.

## 3. Concrete code findings

- **Shared scarce connections:** backend/app/database.py configures a five-connection pool with zero overflow and a ten-second checkout timeout. Increasing it blindly risks exhausting the upstream database connection limit, particularly during deploy overlap.
- **Serial admission requests:** web/lib/browser-assistant.ts tryStart refreshes tasks, then awaits conversation admission. web/components/learn-chat.tsx subsequently awaits mode classification before generation when browser admission did not handle the request. Social turns have a narrow bypass, but ordinary questions retain these serial steps.
- **Mode classification is not always another LLM call:** backend/app/mode_transition_service.py defaults legacy classification to rules. Configured provider/hybrid paths and other classification contracts need separate measurement. Do not assume all prompts incur an extra model call.
- **Database work in the token loop:** backend/app/generation_service.py checks records.cancelled for every provider delta. First-delta metrics are persisted before parser publication. Each text flush persists a delta, fetches the generation record, and persists a checkpoint. These are awaited operations, even though thread offloading prevents event-loop blocking.
- **Durable replay polling:** DurableReplayEventStore reads events and status from PostgreSQL, then waits up to 0.5 seconds when there is no local notification. Local notifications can wake it immediately, so this is not an unconditional 500 ms delay. Cross-process notification and polling load deserve measurement.
- **Buffering:** generation text uses default thresholds of 120 characters or 300 ms. The elapsed-time check runs when a parser delta arrives; it is not an independent timer. Small stalled outputs may remain buffered until another delta or final flush.
- **Connection reuse:** backend/app/model_provider.py opens a new httpx.AsyncClient per stream.
- **Background polling:** browser task discovery polls every five seconds; assistant execution refresh polls every two seconds. Multiple tabs multiply this demand.
- **Note recovery:** web/components/workspace-panel.tsx autosave waits 650 ms, then stops when error is set. A successful save also awaits the notes-list refresh. Save success and list refresh failure need independent states.
- **Health work:** /health invokes web-evidence readiness; /ready checks the database and schema. Liveness, readiness, and diagnostics need separate purposes so expensive diagnostics do not cause restart loops.

These observations identify optimization candidates. Per-stage traces are still required to establish their contribution to production latency.

## 4. Preserve the existing behavior

Retain Buddy preferences, course context, explicit and automatic note context, recent turns, conversation summaries, branch selection, context switching, mode recommendations, user-confirmed transitions, browser clarification targets, attachments, cancellation, durable replay, idempotent acceptance, revision checks, owner isolation, usage accounting, and source provenance.

Changing scheduling or reducing round trips is preferable to discarding these features. Never route from only the newest text when the selected browser question, branch, passage, or conversation changes its meaning. Never show fabricated progress or a cached answer as a fresh personalized generation.

## 5. Options, in recommended order

| Option | Implementation approach | Expected benefit and constraint |
| --- | --- | --- |
| Restore stable service capacity | Diagnose 502s and pool exhaustion; use always-on compute with measured headroom; audit API/database region placement | Prevent cold starts and resource starvation. Paid changes require a hosting decision; no exact gain established. |
| Add stage traces | Correlate UI send, routing, admission, pool wait, context, provider request/first delta, persisted delivery, browser render, and completion | Establish the critical path. Existing metrics cover only part of it; use monotonic duration clocks within each process and avoid subtracting unsynchronized clocks. |
| Separate health endpoints | Constant-time liveness; bounded/cached readiness; detailed diagnostics separately; schema validation at startup plus controlled refresh | Avoid repeated expensive checks and restart cascades without hiding dependency failures. |
| Consolidate admission | One server command loads a versioned context snapshot and returns generation acceptance, tool task, or mode-choice proposal | Preserve all routing outcomes while removing client/server round trips and duplicated context reads. Required mode choices still block execution. |
| Reuse independent work | Gather independent reads concurrently under a concurrency limit; reuse a transaction connection where appropriate | Reduce serial waits without parallelizing dependent writes or overrunning the pool. |
| Optimize database access | Measure slow queries and checkout waits; remove nested checkouts; shorten transactions; index actual query plans; batch adjacent writes | Reduce contention. Preserve revision and worker-lease fencing. Size pools across all processes against the database limit. |
| Optimize durable streaming | Commit ordered event batches; derive checkpoint metadata from the write receipt; flush first meaningful text promptly; use a bounded timer for subsequent chunks | Reduce SQL per displayed chunk while preserving replay. Keep persistence-before-delivery unless a clearly different durability contract is approved. |
| Push cancellation and wakeups | Use local cancellation flags and cross-worker notifications, backed by periodic durable checks and fencing at writes | Avoid a database read per token. Stop latency and stale-worker rejection remain explicit acceptance criteria. |
| Reduce idle polling | Shared visible-tab subscriptions, event notifications, incremental snapshots, backoff when idle, bounded reconnect with jitter | Lower load throughout the platform. Preserve discoverability and reconnect replay; avoid creating a new stream per component unnecessarily. |
| Reuse provider transport | Lifespan-managed HTTP clients, bounded connection limits, compatible keep-alive and graceful shutdown | Remove repeated connection setup. Keep per-request credentials and usage receipts isolated. |
| Cache stable prompt prefixes | Put stable instructions first and changing turn data later; use model-supported caching and measure hit rate | Reduce repeated prompt processing. Minimum lengths and route affinity affect effectiveness; do not pad prompts just to obtain a cache hit. |
| Cache context safely | Cache parsed documents and revision-keyed context ingredients; maintain summaries before the next turn where possible | Avoid repeated preparation while retaining original source references and recent messages. Key by owner, branch, revisions, model, and relevant settings; invalidate on edits, deletes, switches, or permissions changes. |
| Tune provider routing | Benchmark first-token latency and throughput for the existing model; use supported routing preferences, bounded failover, or benchmark direct transport | Preserve model quality while avoiding congested endpoints. Affinity for caching and routing to another host can conflict; measure both. |
| Separate background work | Dedicated worker capacity for titles, indexing, reminders, document processing, summaries, and visuals | Interactive requests get predictable capacity. A write needed for acceptance still completes before acknowledgment; text completion need not wait for an optional visual. |
| Repair note autosave | Persist owner-scoped local drafts, serialize saves, retry transient failures with backoff, reconcile lost responses, separate save/list states | Avoid manual retries and repeated list requests. New-note creation needs idempotency; preserve conflicts and never overwrite newer server revisions. |
| Optimize React rendering | Batch streamed updates once per frame, avoid reparsing the entire transcript, memoize stable messages, virtualize long histories, lazy-load heavy tools | Smooth typing, streaming, and canvas interactions. Profile before applying; this does not speed the provider. |
| Optimize navigation and data loading | Show cached validated views immediately, revalidate incrementally, prefetch likely routes, deduplicate requests, cancel stale reads | Make context switching and returning to a workspace fast. Cached content must remain visibly stale when appropriate. |

### Additional options if these are insufficient

- Benchmark a fast model for bounded classification while retaining the current answer model. Validate mode accuracy, contextual follow-ups, abstention, and transition suppression before using it.
- Offer a fast-answer model only after a comparative quality evaluation. A cheaper/faster model is not automatically equivalent for teaching, sources, math, or tool use.
- Consider reserved/provider priority capacity if measured provider queues dominate. This costs money and does not fix application database waits.
- Partition interactive and background admission budgets; cap per-owner and total concurrency, with fair scheduling and honest queue states. Unlimited concurrency can make every request slower.
- Benchmark direct provider access versus the current gateway before changing it. Gateway overhead may be much smaller than model queueing or application overhead.
- Use exact validated caching for static application help or metadata. Do not use broad semantic answer caching for personalized tutoring; it risks stale or cross-user answers.
- Speculative model execution and duplicate hedged requests are advanced options only after profiling. They may waste tokens, race context revisions, or trigger duplicate actions. Never speculate browser actions, reminders, writes, or confirmed mode transitions.
- Self-hosted inference, model quantization, and speculative decoding are infrastructure alternatives, not first fixes for this application's current symptoms. They add operational and quality responsibilities and cannot guarantee sub-millisecond replies.

## 6. Execution and verification sequence

1. **Availability and baseline:** restore working acceptance; record warm and cold runs separately. Measure repeated short questions, contextual follow-ups, mode suggestions, required transitions, long-context turns, attachments, and browser tasks. Also measure typing notes while chat streams. Run controlled concurrency tests on staging before load testing production.
2. **Database and streaming:** reduce checked-out connection time and SQL per chunk; maintain durable replay, cancellation, ownership leases, ordered sequences, and crash recovery. Compare trace stages and SQL counts before/after.
3. **Unified admission and context:** consolidate routing, reuse snapshots, prepare summaries outside avoidable foreground work. Verify identical branch, note, course, and mode outcomes, including ambiguous browser replies.
4. **Provider transport and caching:** benchmark same-model routing and cache policies with identical context. Compare first meaningful text, output throughput, cache hit rate, cost, and failure rate.
5. **Platform smoothness:** autosave recovery, bounded background work, shared subscriptions, incremental UI rendering, and fast navigation. Verify reload recovery, unknown save outcomes, edits during retry, and no duplicate note creation.
6. **Capacity validation:** choose hosting capacity based on measured workloads, run release canaries, and set latency/error budgets. Keep rollbacks and feature flags for behavior-affecting changes.

Acceptance suite must cover concurrent tabs, follow-ups during generation, explicit context and mode switches, interrupted streams, cross-worker reconnection, cancellation, required user confirmations, note revision conflicts, account switching, owner isolation, and usage charges without duplication. Latency gains are accepted only when these behaviors remain correct.

## 7. Official references

- Render free-service behavior: https://render.com/docs/free
- OpenRouter latency, provider queues, throughput and routing considerations: https://openrouter.ai/docs/guides/best-practices/latency-and-performance
- OpenRouter provider selection: https://github.com/OpenRouterTeam/docs/blob/main/guides/routing/provider-selection.mdx
- Claude prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching

These references establish available techniques; they are not measurements of Open Learn or promises of a specific speedup.
