# Open Learn: task-wise performance implementation plan

Created: 2026-10-10. Status: P01/P02 delivered; P03/P04 implemented and locally validated, with hosted activation/qualification pending. P05 onward planned. See [implementation evidence](performance/P01_P04_Implementation_and_Validation.md).

Source: [Scalable architecture review](Open_Learn_Scalable_Architecture_Review.md) and [production measurements](Open_Learn_Performance_Investigation_and_Options.md).

## Objective and execution rules

Make chat, notes, and navigation consistently responsive as usage and features grow. Preserve context switching, mode recommendations, Buddy preferences, course/attachment context, branching, cancellation, permissions, usage accounting, durable jobs, and replay.

Tasks below are ordered implementation units suitable for separate pull requests. Each task must record its commit/PR, evidence, observed performance change, and rollback procedure before being marked complete. Dependencies refer to task IDs. A conditional task is complete when its evaluation and adopt/defer decision are documented; it does not require introducing every alternative.

Prepare configuration, cost estimates, and cutover steps before requesting any necessary paid infrastructure approval. Do not interpret this planning document as authorization to purchase services or switch production. Recheck live configuration and vendor capabilities when executing; the review is a dated snapshot.

Do not remove context or quality checks to meet latency goals. No uncapped retries, unlimited queues, or fabricated progress. Preserve owner isolation and revision checks in all optimizations.

## Success measures

Initial objectives, to validate against a defined workload rather than claim as achieved:

| Metric | Objective |
| --- | --- |
| Local interaction feedback | <50 ms |
| Message acceptance | p95 <750 ms |
| First meaningful text, ordinary short questions | p95 <2.5 s |
| Cloud note save, excluding debounce | p95 <1 s |
| Provider text to browser delivery overhead | p95 <100 ms |

Task P02 defines the tested concurrency, user regions, sample size, error budget, and quality thresholds. Report p50/p95/p99, failures, queue time, and total completion separately. A failed request is not a fast successful request. Complex tool tasks have separate budgets. Fractions-of-a-millisecond remote AI completion is not an objective.

## Stage 1 — Baseline and release foundations

### P01 — Confirm deployment and request topology

- [x] Inventory live frontend/API/worker commits, regions, process modes, pool settings, provider configuration, and deployment triggers. Record public configuration only.
- [x] Determine compiled direct/proxy configuration and map request boundaries; authenticated runtime capture remains explicitly unverified.
- [x] Record quota risk separately from missing-schema/direct-SQL hypotheses; project usage attribution remains unavailable.
- Deliverable: current topology, unresolved risks, and environment matrix.
- Done when: every request hop and live execution role is documented; hypotheses are distinguished from proven causes.
- Depends on: none.

### P02 — Define workload and regression contracts

- [x] Create representative scenarios for greetings, tutoring, follow-ups, context switches, mode recommendations, branches, notes, browser, documents, in-class, and reminders.
- [x] Define proposed baseline/growth/burst assumptions, geographic coverage, and bounded production probe budget.
- [x] Define quality/error/latency objectives, including long histories, reconnects, and multiple tabs.
- Deliverable: benchmark specification and preserved-feature checklist.
- Done when: performance and correctness have explicit pass/fail criteria with sample sizes; no invented supported-user capacity.
- Depends on: P01.

### P03 — Add end-to-end timing and operational visibility

- [x] Implement enqueue/admission/SQL/context/queue/provider/persisted-text/browser-receive/React-commit timing. Lock waiters are sampled; lock duration is not isolated.
- [x] Add separate note-save, loop-lag, generation/queue/lease/pool diagnostics; hosted retry/saturation distributions require live evidence.
- [x] Add private dashboard and investigation thresholds without content or correlation IDs in metric labels.
- [ ] Collect successful production stage traces and qualify hosted/fleet behavior after deploying instrumentation.
- Deliverable: baseline report with failed and successful requests, cold/warm samples, and cost per workload.
- Done when: a slow request can be attributed to a stage; telemetry failure does not block ordinary operations.
- Depends on: P02.

### P04 — Align production builds and release controls

- [x] Add frontend/API CI and production Next.js/asset build parity; document local framework differences.
- [x] Add schema/capability/commit gates, single migration job, pair checks, and coordinated release workflow.
- [x] Add rollback/expand-contract rules and release-managed schema-check-only runtime; current hosted bootstrap persists until activation.
- [ ] Activate hosted CI/secrets, reconcile hosting drift, and rehearse hosted rollout/rollback. Local compiled-artifact pair gates passed.
- Deliverable: reproducible release pipeline and runbook.
- Done when: staging demonstrates a compatible rollout and rollback using production artifacts.
- Depends on: P01–P02.

## Stage 2 — Stable capacity and regional placement

### P05 — Set process and connection budgets

- [ ] Calculate peak database use across API replicas, all workers, migration/listener connections, provider services, and deployment overlap.
- [ ] Choose direct/session/transaction pooling per role after checking session state, prepared statements, locks, and listener requirements.
- [ ] Configure bounded per-role pools and request/worker concurrency, preserving operational headroom. Document cost and instance sizing from measurements.
- Done when: connection totals stay inside effective limits during rollout and bursts; pool waits are observable.
- Depends on: P01, P03.

### P06 — Separate liveness, readiness, and diagnostics

- [ ] Make liveness cheap; use bounded dependency readiness; move deep schema/configuration checks to startup/release diagnostics.
- [ ] Avoid repeated schema introspection/new connections on routine probes. Keep schema incompatibility visible and fail appropriately.
- Done when: dependency degradation is distinguishable from process failure and probes do not cause restart storms.
- Depends on: P03–P04.

### P07 — Prepare and execute Virginia cutover

- [ ] Prepare replacement always-on Virginia API/background service configuration, explicit worker modes, secrets mapping, quota remediation, costs, and rollback endpoints.
- [ ] Obtain any required infrastructure/billing approval for the concrete proposal; provision staging/replacement services afterward.
- [ ] Use the existing database; avoid unnecessary data migration. Drain/fence old consumers before activating replacements and coordinate frontend origin configuration.
- [ ] Resolve the quota risk with an approved capacity or usage plan; verify backup policy and restore access.
- Done when: same workload is measured before/after; notes and chat work; old consumers cannot duplicate side effects; rollback is exercised.
- Depends on: P04–P06. Dedicated generation separation is delivered in Stage 4; do not claim it is already external here.

## Stage 3 — Shorten the request and persistence path

### P08 — Remove blocking work from async request paths

- [ ] Audit generation/context/accounting paths, including context_snapshot argument evaluation before to_thread and synchronous usage reservation/dispatch.
- [ ] Offload blocking work with bounded execution or adopt async access selectively. Preserve transaction/session ownership and required budget checks.
- Done when: concurrent note requests remain responsive during generation and event-loop lag improves without accounting regressions.
- Depends on: P03. Can be prepared while Stage 2 infrastructure is pending.

### P09 — Reduce database round trips

- [ ] Replace workflow-store N+1 reads, redundant record fetches, and repeated request-local identity reads with batched/scoped operations.
- [ ] Add measured indexes and pagination; inspect query plans and transaction/lock duration. Do not cache permission revocations indefinitely.
- Done when: queries per representative operation decrease with equivalent ordering, authorization, and revision behavior.
- Depends on: P03, P05.

### P10 — Improve provider connection lifecycle

- [ ] Reuse appropriately scoped HTTP clients with bounded pools, explicit timeouts, cancellation, and clean shutdown.
- [ ] Bound retries; avoid retrying after partial output in a way that duplicates answers or charges.
- Done when: concurrent streams, cancellation, shutdown, and provider failure handling retain correct accounting.
- Depends on: P03, P08.

### P11 — Batch durable streaming and bound flush delay

- [ ] Implement transactional ordered event/checkpoint batches and remove nonessential first-token blocking metrics writes.
- [ ] Add a genuine flush timer independent of new provider deltas. Persist before notifying subscribers.
- [ ] Replace per-token cancellation queries with bounded checks while retaining durable cancellation and final-state reconciliation.
- Done when: stalled small chunks flush within budget; reconnect has no missing/duplicate visible text; cancellation and terminal events remain correct.
- Depends on: P08–P10.

### P12 — Consolidate admission and context routing

- [ ] Define one idempotent command returning accepted work, mode recommendation, or required clarification.
- [ ] Consolidate serial browser/mode/generation preparation; parallelize independent reads only.
- [ ] Preserve selected branch/passage, course context, Buddy preferences, user-confirmed mode transitions, and revision conflict behavior.
- Done when: P02 routing/context scenarios pass with fewer browser round trips and no duplicate generation on retry.
- Depends on: P08–P09; release via P04 compatibility rules.

### P13 — Make note saves resilient and independent

- [ ] Separate local recovery, cloud persistence, and list-refresh states. A refresh failure must not invalidate a successful save.
- [ ] Add bounded automatic retry for transient failures, revision-aware conflict handling, and owner-scoped local persistence.
- [ ] Preserve pending edits across navigation/reconnect; clear or isolate drafts on account changes. Do not present local-only persistence as cloud success.
- Done when: notes survive offline/reconnect and concurrent typing/generation without stale overwrite or incorrect save errors.
- Depends on: P02–P03, P08.

## Stage 4 — Independent, durable execution

### P14 — Extract the generation worker role

- [ ] Add a generation runner to hosted_runtime and deployment definitions; APIs admit and stream durable work without owning execution lifetime.
- [ ] Reuse existing records, leases, fencing, revisions, and idempotency. Specify recovery behavior for provider streams that cannot resume exactly.
- [ ] Configure external mode explicitly; migrate ownership without running duplicate embedded consumers.
- Done when: API restart does not cancel an independently running answer; worker crash recovers honestly without duplicate external effects or budget charges.
- Depends on: P04–P05, P11–P12.

### P15 — Add shared wakeups with durable fallback

- [ ] Compare dedicated PostgreSQL listener versus pub/sub using measured connection and latency needs; choose through A01 below.
- [ ] Publish after commit, wake stream/job readers across replicas, and retain replay plus bounded fallback polling.
- [ ] Support listener reconnect, lost/duplicate notifications, and cross-process cancellation.
- Done when: cross-replica delivery meets its budget and notification loss never loses authoritative work/events.
- Depends on: P11, P14, A01.

### P16 — Isolate workloads and enforce fair admission

- [ ] Reserve capacity for interactive requests and saves; separate generation from CPU-heavy documents, browsers, class processing, and schedules.
- [ ] Set per-owner limits, queue bounds, priority/fairness, deadlines, retry budgets, and honest overloaded/queued states.
- [ ] Measure global capacity-row contention and worker-claim contention before changing their algorithms.
- Done when: batch bursts do not starve notes/chat; overload is bounded and recovery does not create retry storms.
- Depends on: P05, P14–P15.

## Stage 5 — Frontend and model efficiency

### P17 — Reduce polling and rendering work

- [ ] Consolidate status subscriptions, deduplicate requests, and coordinate multiple tabs where safe; retain reconnect fallback.
- [ ] Limit transcript updates per chunk; lazy-load heavy panels and add history virtualization only where profiling warrants it.
- [ ] Keep one accurate progress indicator and responsive composer/cancellation controls; honor reduced motion.
- Done when: long-history/multi-tab workloads reduce requests and main-thread stalls without missing updates or breaking accessibility.
- Depends on: P03, P12, P15.

### P18 — Optimize context construction and model selection

- [ ] Reuse stable prompt prefixes where supported, scope caches to owner/context/version, and invalidate correctly.
- [ ] Use bounded retrieval and incremental summaries with provenance while preserving selected context and recent revisions.
- [ ] Benchmark available model/provider routes on P02 quality, latency, reliability, and cost criteria. Keep complex tasks on adequate models.
- Done when: gains are measured and quality/context thresholds pass; no blanket smaller-model downgrade or stale personalized-answer cache.
- Depends on: P03, P10, P12; infrastructure baseline stabilized by P07.

### P19 — Prepare large-file and storage growth paths

- [ ] Measure attachment/storage bottlenecks. If justified, implement authorized direct upload sessions with scoped access, expiry, checksums, limits, and server verification.
- [ ] Adapt the existing storage contract explicitly; preserve ownership/provenance and clean abandoned uploads.
- [ ] Define event/job/artifact retention and safe archival without deleting replay data still needed by active work.
- Done when: documented adopt/defer decision exists; any adopted path passes unauthorized-upload, expiry, retry, and recovery checks.
- Depends on: P01–P03, P04.

## Stage 6 — Conditional alternatives and scaling decisions

Evaluate these explicitly; do not install all of them. Each decision records baseline, prototype evidence when warranted, cost, failure modes, migration/rollback work, and a revisit trigger.

| ID / task | Trigger and work | Acceptance / dependency |
| --- | --- | --- |
| A01 — Shared notification and Redis decision | Compare PostgreSQL session listener with managed pub/sub. Assess connection budget, wakeup load, failure recovery, and operational cost. Evaluate derived-data caching separately from notifications. | Select simplest option meeting P15; durable SQL remains authoritative. Depends P03/P05/P11. |
| A02 — Managed workflow pilot | Evaluate one noninteractive batch task if custom worker operations/retries are burdensome. Compare Render Workflows with existing jobs; assess scheduling, preview support, startup delay, and idempotency. | Adopt only with demonstrated operational/cost benefit; no added interactive chat delay. Depends P14/P16. |
| A03 — Advanced orchestration review | Consider Temporal or equivalent when human waits, compensation, and workflow versioning exceed current job capabilities. | Written requirements/fit decision; migration only if justified. Depends A02 and concrete feature demand. |
| A04 — Read replica/cache evaluation | Use traces to identify read-heavy, stale-tolerant workloads after query optimization. | Explicit consistency/lag policy; current context and read-your-writes stay on primary. Depends P09/P16. |
| A05 — All-Vercel backend comparison | Prototype representative requests only if operations/cost remain problematic. Account for durable execution, streaming, connection limits, authentication, uploads, and observability. | Comparable workload and cost report; migrate only with clear net benefit. Depends P07/P14/P16. |
| A06 — Managed containers/queues comparison | Evaluate AWS or another suitable platform if placement, scale, compliance, or economics demand more control. | Total operating cost, staffing, portability, and rollback assessed; no speculative migration. Depends P16/P20. |
| A07 — Transport decision | Retain SSE for token/status delivery. Evaluate WebSockets only for a concrete bidirectional feature. | Evidence of product need; replay/auth/backpressure maintained. Depends P15/P17. |
| A08 — Geographic expansion | Review actual distant-user latency. Prefer workspace home regions; define residency, routing, fencing, failover, and migration before writes span regions. | Data consistency and recovery design precedes deployment; no premature global active-active database. Depends P20/P21 and traffic evidence. |
| A09 — Orchestration/sharding threshold | Assess Kubernetes, database sharding, or capacity-counter partitioning only after measured operational/lock/scale limits. | Document defer decision and measurable revisit trigger unless evidence justifies a prototype. Depends P16/P20. |

## Stage 7 — Capacity validation and production rollout

### P20 — Load, resilience, and autoscaling qualification

- [ ] Run P02 workload at baseline/growth/burst concurrency with chat, notes, background jobs, and multiple tabs together.
- [ ] Exercise provider slowdown, rate limits, database pool pressure, notification loss, API/worker restart, expired leases, and rolling deployments.
- [ ] Size warm capacity and scaling bounds from queue age, active work, latency, memory, database limits, and provider quotas; add cooldowns and graceful scale-down.
- [ ] Publish measured supported load, SLO results, costs, and remaining bottlenecks. Recheck plan-specific scaling capabilities before configuration.
- Done when: agreed workload and correctness/error objectives pass, with explicit limits instead of an unlimited scalability claim.
- Depends on: P07–P18; P19 if adopted.

### P21 — Restore and operational readiness

- [ ] Define recovery point/time objectives; verify database/object backup coverage and perform an isolated restore exercise.
- [ ] Write runbooks for pool exhaustion, stale leases, delayed reminders, failed saves, provider outages, quotas, and deployment rollback.
- [ ] Add a new-feature checklist covering latency budget, queue class, authorization, idempotency, retention, and observability.
- Done when: restore evidence and operational ownership exist; alerts link to actionable runbooks.
- Depends on: P04–P05, P16.

### P22 — Controlled rollout and final comparison

- [ ] Roll out compatible backend/worker changes before frontend dependencies, using staged traffic or feature flags and predeclared rollback thresholds.
- [ ] Monitor latency, error rate, note integrity, queue age, provider costs, and context/mode quality through a representative observation window.
- [ ] Drain obsolete services and remove them only after rollback coverage and recovery evidence are retained.
- [ ] Publish before/after results and unresolved items; mark alternatives adopted/deferred with revisit criteria.
- Done when: production meets the agreed workload objectives, preserved-feature checks pass, and rollback remains documented.
- Depends on: P20–P21 and relevant alternative decisions.

## Suggested execution order

1. P01–P04: establish evidence and safe releases.
2. P05–P07: stabilize capacity and placement. P08–P10/P13 may be prepared while infrastructure decisions are pending.
3. P08–P13: reduce latency in existing paths.
4. P14, A01, P15–P16: independent generation and shared events.
5. P17–P19: frontend, model, and storage improvements.
6. P20–P22: qualify capacity, recovery, and production rollout.
7. Review A02–A09 at their stated triggers; record defer decisions for those not justified.

Do not delay an independently validated reliability fix until all stages are complete. Release small compatible increments through P04, measuring each change. The final rollout task consolidates qualification rather than requiring one large release.

## Completion record template

For each task append: status (planned/in progress/blocked/completed/deferred), responsible owner, dependency status, PR/commit, validation evidence, before/after timings and error counts where applicable, costs, rollback steps, and remaining risks. Deferred alternatives additionally require a revisit trigger. Do not mark measured objectives achieved without production or representative staging evidence.
