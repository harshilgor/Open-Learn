# Performance plan audit — 11 October 2026

## Conclusion

The plan is **not complete**, and its performance objectives are **not achieved**. Substantial implementation shipped in `bc6f3b78aceefe3ce2cfae3042a426933b31cb4d`, but code presence, deployment success, and performance acceptance are different milestones. Earlier documents incorrectly described this deployed code and migrations as local-only. This audit supersedes those status statements; their technical implementation descriptions remain useful.

Evidence: [successful production release #21](https://github.com/harshilgor/Open-Learn/actions/runs/38174094539), [latest observations](Production_Release_and_Latency_2026-10-11.md), [earlier traced baseline](Hosted_Activation_and_Measurements.md), implementation notes, and the current source. The previously verified public frontend/backend pair reports this commit and schema `0085_object_cleanup_queue`. A fresh shell metadata request during this audit failed DNS resolution in the execution environment; that failure does not establish a production outage. No new deployment, purchase, load test, or feature removal was performed for this audit.

## Task-by-task disposition

“Released” below describes implementation, not a passed latency objective. Local tests cannot substitute for the plan's hosted acceptance criteria.

| Task | What exists | Still needed for completion |
| --- | --- | --- |
| P01 | Deployment inventory and request topology. | Keep authenticated runtime hops and actual settings current; distinguish proposed configuration from live configuration. |
| P02 | Workload, preserved-feature contracts and explicit targets. | Specification is delivered; executing its representative workload is P20/P22 work. |
| P03 | API/SQL/context/provider/durable-event/browser timing and private diagnostics released. | Reliable browser export and hosted structured logging; correlated attribution, sufficient samples and fleet distributions. |
| P04 | Preflight and coordinated production release succeeded; compiler precedes writes, schema/commit pair verified. | Isolated rollback rehearsal and evidence. A successful deployment is not a performance pass. |
| P05 | Bounded pools, zero overflow, connection-budget gate and admission controls. | Burst/connection-hold qualification. Live API still shares five database connections across embedded work. |
| P06 | Cheap liveness, readiness coalescing and startup/schema checks. | Code released; sustained hosted behavior belongs in workload qualification. |
| P07 | Virginia placement and separate-worker proposal prepared. | Region cutover, worker provisioning, quota/backup verification and restore evidence. Paid activation deferred by the keep-hosting-free decision. |
| P08 | Blocking work offloaded from async request paths. | Demonstrate event-loop responsiveness and note latency under concurrent generation; current observations do not pass. |
| P09 | Batched reads, request identity reuse and keyset note pagination. | PostgreSQL execution plans, transaction/lock analysis and justified indexes against measured slow queries. |
| P10 | Provider connection reuse, bounded timeout/retry and cancellation handling. | Hosted concurrent streaming and failure qualification; quantify remaining provider time. |
| P11 | Durable checkpoint/event batching and persistence before delivery. | Hosted flush/delivery budget and recovery qualification; retain replay/cancellation correctness. |
| P12 | Ordinary Ask/Learn classification and admission consolidated into one idempotent command; presentation/recommendation receipts retained. | Representative production mode/context/replay qualification. Browser actions and first Learn journey remain specialized by design. |
| P13 | Note revisions, local recovery, save/list states and bounded retry handling. | Cloud persistence was read back, but speed and save independence under load are not achieved. |
| P14 | Separate generation role, leases, fencing and graceful drain implemented. | Production activation and isolated worker crash/restart/usage accounting qualification. Live generation still runs in the API process. |
| P15 | PostgreSQL notification triggers/listener and durable fallback implemented; migration 0084 applied through schema 0085. | Listener activation after connection requalification; cross-process latency, cancellation and reconnect evidence. Live free configuration retains polling. |
| P16 | Owner/global queue bounds, expiry and fair selection implemented. | Actual workload isolation and hosted fairness/overflow/load evidence. Entry points alone do not create separate live processes. |
| P17 | Lazy chunks, 40 ms transcript batching, same-session in-flight browser refresh deduplication and hidden-tab reminder pause. | Cross-tab coordination is not implemented. Profile other mounted/background poll sources; virtualization remains conditional on evidence. |
| P18 | Context serialization accounting improved; context/provenance policy retained. | Representative model routing/quality/cost benchmark and provider-specific prefix-cache evaluation. No faster model/cache route was activated. |
| P19 | Retryable object cleanup ledger and worker drain implemented; migration 0085 applied. | Operational retry/recovery qualification. Direct signed uploads and broader pruning have documented defer decisions. |
| P20 | Fixture reporting and isolated load/fault procedures. | Completed representative PostgreSQL/provider/browser/multi-process runs, 100 eligible samples per scenario/profile, measured capacity and costed scaling bounds. Fixture tooling is not hosted qualification. |
| P21 | Runbooks and future-feature latency/ownership/queue checklist. | Accepted RPO/RTO, actual backup/object coverage and an isolated restore exercise. |
| P22 | Staging/promotion/alias gates and comparison tooling; actual production release and bounded observations. | Controlled before/after comparison, representative quality/error/cost window and rollback evidence. Current samples do not establish an improvement. |
| A01 | Decision: PostgreSQL wakeups rather than a separate broker. | Evaluate operational performance when enabled; currently inactive in the free shared pool. |
| A02–A09 | Documented defer decisions and revisit triggers; SSE retained. | These are conditional alternatives, not eight missing mandatory migrations. Revisit only at their stated triggers. |

## Why the objectives are still missed

### 1. The earlier trace shows substantial application/database delay

The earlier inertia trace recorded 269 SQL executions (21.252 seconds total), 66 checkout observations (43.660 seconds total), context preparation of 26.468 seconds and provider first delta of 4.804 seconds. These timings overlap and **must not be added**. They establish that provider speed alone was not the whole problem. They do not prove which individual query, transaction or pool waiter dominates the current release.

P09's database-plan/lock work is still missing. Increasing the pool blindly can shift contention to PostgreSQL; offloading synchronous work frees the event loop but does not eliminate database round trips or connection waits.

### 2. The intended capacity isolation is not active

The live topology remains a free Render API in Oregon with the database in Virginia, embedded workers and a shared five-connection pool. Chat preparation, durable events, note saves and other work can compete for that pool. Cross-region sequential calls also accumulate network latency. Dedicated role code and capability flags do not mea
n that dedicated workers are deployed.

This topology is a plausible contributor, not a measured explanation for every second. Paid compute could remove cold starts and enable isolation, but neither an upgrade nor a hosting migration guarantees the targets without query and workload measurements.

### 3. Frontend optimization is partial

Same-tab refresh deduplication is not cross-tab coordination. Visited feature panels remain mounted to preserve state. Recent access logs showed calendar, usage, assistant and class traffic during the measurement window. That justifies profiling unnecessary polling while preserving active recordings and reconciliation; it does not prove that one specific poll caused the slow response.

### 4. Observability still has an operational gap

The browser diagnostics component reads `performance=1` once on mount. Workspace navigation constructs new URLs without retaining that flag; remounting can disable the panel. The flag disappeared in the production probe. Targeted hosted log reads also returned no structured performance lines. The hosted startup uses Uvicorn, while the performance logger sets a level but no explicit sink; verify logging configuration before declaring the sink defective.

Without reliable correlated timing, a change can pass correctness tests and still fail the real latency objective. Repeated deployments cannot replace this evidence.

### 5. The final acceptance gates were never passed

P20/P22 require representative load and quality checks. The latest probe had no meaningful inertia answer visible at 113.4 seconds; note “Saved” appeared after approximately 31.5–33.1 seconds including debounce/UI work. These are observation bounds, not p95 or comparable isolated HTTP durations. They demonstrate a poor user experience, but do not establish controlled regression causality or a valid percentage improvement.

## Next work, preserving features

1. Repair profiling persistence/export and verify structured timing delivery. Capture acceptance, queue, context, SQL/checkout, provider, persistence and browser timing for the same request; capture note requests concurrently. No release-workflow rewrite is needed for this investigation.
2. Complete P09 against the actual slow PostgreSQL queries: plans, connection hold time, transaction scope and lock contention. Batch repeated lookups and shorten transactions without dropping course/Buddy/attachment context, permissions or usage checks.
3. Complete P17's measured polling work: coalesce identical snapshots across tabs, pause nonessential hidden activity, preserve active class/browser jobs and authoritative replay. Investigate repeated finalization and stale reconnect notices before changing cadence.
4. Requalify P05/P15 budgets, then choose an explicitly approved topology for region alignment and execution isolation. Keep paid activation deferred while the current free-hosting instruction stands. Do not enable listeners by consuming scarce live pool capacity without measurement.
5. Complete P18's model/cache comparison with the same feature and quality contract. Cache only safe reusable inputs with correct owner/context/revision scope; do not silently downgrade answers.
6. Run P20/P21 in isolation, then P22's controlled observation window. Report successes, errors, cancellations and p50/p95/p99 with sample counts. Only then mark the plan complete.

The target is fast **successful, correct** work. Hiding errors, shortening answers indiscriminately, skipping context, or showing faster animations would not satisfy the plan.
