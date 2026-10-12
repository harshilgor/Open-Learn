# Open Learn: task-wise performance implementation plan

Created: 2026-10-10. Status corrected: 2026-10-11. Substantial P03-P19 implementation was released in bc6f3b7 through successful production run #21; production schema is 0085_object_cleanup_queue. The plan is NOT complete and latency objectives are NOT achieved. P07 region/paid cutover, P14 external execution and P15 listener activation remain inactive under the keep-hosting-free decision. P09 database analysis, P17 cross-tab coordination, P18 provider/model qualification, and P20-P22 hosted load/restore/controlled comparison evidence remain open. Checkboxes below describe individual deliverables, not passed task acceptance criteria. See the authoritative [current task audit](performance/Performance_Plan_Audit_2026-10-11.md) and [production release and latency evidence](performance/Production_Release_and_Latency_2026-10-11.md). Historical implementation-note status statements about local-only code or unapplied migrations are superseded by these records.

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
- [x] Collect initial successful production stage traces after deploying instrumentation; two successful prompts and one failed admission are recorded in [hosted measurements](performance/Hosted_Activation_and_Measurements.md).
- [ ] Qualify hosted/fleet behavior with representative sample sizes and concurrency under P20.
- Deliverable: baseline report with failed and successful requests, cold/warm samples, and cost per workload.
- Done when: a slow request can be attributed to a stage; telemetry failure does not block ordinary operations.
- Depends on: P02.

### P04 — Align production builds and release controls

- [x] Add frontend/API CI and production Next.js/asset build parity; document local framework differences.
- [x] Add schema/capability/commit gates, single migration job, pair checks, and coordinated release workflow.
- [x] Add rollback/expand-contract rules and release-managed schema-check-only runtime; current hosted bootstrap persists until activation.
- [x] Activate hosted CI/secrets and execute a production pair gate; release evidence is recorded in [hosted measurements](performance/Hosted_Activation_and_Measurements.md).
- [ ] Reconcile any remaining dashboard drift and rehearse hosted rollout/rollback in isolated staging. Local compiled-artifact pair gates passed.
- Deliverable: reproducible release pipeline and runbook.
- Done when: staging demonstrates a compatible rollout and rollback using production artifacts.
- Depends on: P01–P02.

## Stage 2 — Stable capacity and regional placement

### P05 — Set process and connection budgets

- [x] Calculate the documented rollout envelope and reserve operational headroom; the free live API remains a single shared five-connection pool with a ten-second wait.
- [x] Verify the live session-pooler mode and document why transaction pooling is not approved for migration or listener roles.
- [x] Configure bounded per-role pools and request/worker concurrency in the prepared hosted topology. Burst qualification is still open.
- Done when: connection totals stay inside effective limits during rollout and bursts; pool waits are observable.
- Depends on: P01, P03.

### P06 — Separate liveness, readiness, and diagnostics

- [x] Make liveness cheap; use bounded shared-pool readiness; keep deep schema/configuration checks in startup/release diagnostics.
- [x] Avoid repeated schema introspection/new connections on routine probes. Keep schema incompatibility visible and fail appropriately.
- Done when: dependency degradation is distinguishable from process failure and probes do not cause restart storms.
- Depends on: P03–P04.

### P07 — Prepare and execute Virginia cutover

- [x] Prepare the replacement Virginia service configuration, explicit worker modes, secret mapping, costs, and rollback procedure.
- [ ] Obtain any required infrastructure/billing approval for the concrete proposal; provision staging/replacement services afterward.
- [ ] Use the existing database; avoid unnecessary data migration. Drain/fence old consumers before activating replacements and coordinate frontend origin configuration.
- [ ] Resolve the quota risk with an approved capacity or usage plan; verify backup policy and restore access.
- Done when: same workload is measured before/after; notes and chat work; old consumers cannot duplicate side effects; rollback is exercised.
- Depends on: P04–P06. Dedicated generation separation is delivered in Stage 4; do not claim it is already external here.

Status: paid provisioning, quota remediation, cutover, workload comparison, and rollback rehearsal are deferred. The hosting-free decision does not complete P07.

## Stage 3 — Shorten the request and persistence path

### P08 — Remove blocking work from async request paths

- [x] Audit generation/context/accounting paths, including context_snapshot argument evaluation before to_thread and synchronous usage reservation/dispatch.
- [x] Offload blocking work with bounded execution or adopt async access selectively. Preserve transaction/session ownership and required budget checks.
- Done when: concurrent note requests remain responsive during generation and event-loop lag improves without accounting regressions.
- Depends on: P03. Can be prepared while Stage 2 infrastructure is pending.

### P09 — Reduce database round trips

- [x] Replace workflow-store N+1 reads, redundant record fetches, and repeated request-local identity reads with batched/scoped operations.
- [x] Add bounded owner-scoped keyset pagination for workspace-note summaries and switch the Notes workspace, picker, and practice selector to 50-item pages. Keep the full-list route for compatibility.
- [ ] Inspect PostgreSQL query plans and transaction/lock duration; add only indexes justified by those plans. Do not cache permission revocations indefinitely.
- Done when: queries per representative operation decrease with equivalent ordering, authorization, and revision behavior.
- Depends on: P03, P05.

### P10 — Improve provider connection lifecycle

- [x] Reuse appropriately scoped HTTP clients with bounded pools, explicit timeouts, cancellation, and clean shutdown.
- [x] Bound retries; avoid retrying after partial output in a way that duplicates answers or charges.
- Done when: concurrent streams, cancellation, shutdown, and provider failure handling retain correct accounting.
- Depends on: P03, P08.

### P11 — Batch durable streaming and bound flush delay

- [x] Implement transactional ordered event/checkpoint batches and remove nonessential first-token blocking metrics writes.
- [x] Add a genuine flush timer independent of new provider deltas. Persist before notifying subscribers.
- [x] Replace per-token cancellation queries with bounded checks while retaining durable cancellation and final-state reconciliation.
- Done when: stalled small chunks flush within budget; reconnect has no missing/duplicate visible text; cancellation and terminal events remain correct.
- Depends on: P08–P10.

### P12 — Consolidate admission and context routing

- [x] Remove the duplicate `/v1/account` request from the common chat path by reusing the owner resolved during browser-task refresh; retain a cold-session fallback. This removes one browser/API round trip but is not a substitute for the unified server command.
- [x] Persist selected Buddy presentation inside the idempotent generation-acceptance transaction, removing the separate per-turn mode write while preserving course/default Buddy attribution and the distinct initial-Learn Journey path.
- [x] Keep advisory mode classification after fallible attachment and URL preparation so failed preparation cannot leave a stale recommendation.
- [x] Define one idempotent generation command returning accepted work, a mode recommendation, or a required mode choice. Mode-choice receipts replay by the same client message ID and resume after dismissal.
- [x] Move ordinary Ask/Learn mode classification into generation admission, removing the serial classification HTTP round trip. Keep browser actions and initial Learn journey setup on their specialized workflows.
- [x] Preserve selected branch/passage, course context, Buddy preferences, user-confirmed mode transitions, and revision conflict behavior through the existing generation request and confirmation contracts.
- Done when: P02 routing/context scenarios pass with fewer browser round trips and no duplicate generation on retry.
- Depends on: P08–P09; release via P04 compatibility rules.

### P13 — Make note saves resilient and independent

- [x] Separate local recovery, cloud persistence, and list-refresh states. A refresh failure must not invalidate a successful save.
- [x] Add bounded automatic retry for transient failures, revision-aware conflict handling, and owner-scoped local persistence.
- [x] Preserve pending edits across navigation/reconnect; clear or isolate drafts on account changes. Do not present local-only persistence as cloud success.
- Done when: notes survive offline/reconnect and concurrent typing/generation without stale overwrite or incorrect save errors.
- Depends on: P02–P03, P08.

## Stage 4 — Independent, durable execution

### P14 — Extract the generation worker role

- [x] Add a generation runner to hosted_runtime and the inactive paid deployment proposal; external-mode APIs accept durable work without owning its execution lifetime.
- [x] Reuse existing records, leases, fencing, revisions, and idempotency. Provider streams that cannot resume exactly are surfaced as interrupted with partial output; no silent provider retry is made.
- [x] Configure external mode explicitly in the proposal; leave the live free deployment embedded and avoid duplicate consumers.
- Done when: API restart does not cancel an independently running answer; worker crash recovers honestly without duplicate external effects or budget charges.
- [ ] Apply/release the worker role and qualify API restart, graceful drain, hard crash, lease recovery, and provider accounting under P02.
- Depends on: P04–P05, P11–P12.

### P15 — Add shared wakeups with durable fallback

- [x] Compare PostgreSQL session listener with managed pub/sub; select PostgreSQL via A01 because the existing durable database is authoritative and the free plan should not add a broker.
- [x] Publish committed event/queue/cancellation wakeups, wake stream/job readers across replicas, and retain replay plus bounded fallback polling.
- [x] Support listener reconnect, lost/duplicate notifications, and cross-process cancellation.
- Done when: cross-replica delivery meets its budget and notification loss never loses authoritative work/events.
- [ ] Requalify pool budgets, release migration 0084, and measure cross-replica delivery on the selected hosted topology.
- Depends on: P11, P14, A01.

### P16 — Isolate workloads and enforce fair admission

- [x] Add an independently runnable generation role with a bounded connection pool; keep the free deployment on embedded mode until worker compute is approved. Existing document/browser/class/schedule worker roles remain separate in the hosted proposal.
- [x] Set per-owner active and queued limits, a global queue bound, round-robin owner fairness, a 15-minute queue deadline, and an honest capacity response. Provider streams have bounded timeouts and no automatic retry after partial output.
- [x] Keep capacity-row and worker-claim algorithms unchanged pending P02 contention evidence.
- Done when: batch bursts do not starve notes/chat; overload is bounded and recovery does not create retry storms.
- [ ] Validate workload isolation, queue fairness, bounded overload, and contention under P02 before external activation.
- Depends on: P05, P14–P15.

## Stage 5 — Frontend and model efficiency

### P17 — Reduce polling and rendering work

- [x] Deduplicate concurrent browser-task snapshot refreshes for the same session/account generation; preserve the existing bounded poll and event replay paths.
- [ ] Coordinate status subscriptions across multiple tabs where safe; retain reconnect fallback. Cross-tab stream sharing is deferred pending replay/reconnect design and request-volume evidence.
- [x] Batch streamed transcript deltas at a 40 ms UI cadence while preserving event order and durable replay sequence; pause reminder polling in hidden tabs.
- [x] Lazy-load heavy Quiz, In-Class, Flashcard, Reminder, Visualization, lecture-note, and compact tutor modules on first use; keep visited tabs mounted. Existing progress and cancellation controls remain unchanged.
- [ ] Add history virtualization only if browser profiling shows material main-thread or layout cost.
- Done when: long-history/multi-tab workloads reduce requests and main-thread stalls without missing updates or breaking accessibility.
- Depends on: P03, P12, P15.

### P18 — Optimize context construction and model selection

- [ ] Reuse stable prompt prefixes where supported, scope caches to owner/context/version, and invalidate correctly. Deferred until provider/model support and P02 benefit are measured.
- [x] Preserve bounded, ranked retrieval and omission provenance; context token budgeting now serializes each candidate once instead of repeatedly serializing the selected prefix.
- [ ] Benchmark available model/provider routes on P02 quality, latency, reliability, and cost criteria. Keep complex tasks on adequate models; no route downgrade was made.
- Done when: gains are measured and quality/context thresholds pass; no blanket smaller-model downgrade or stale personalized-answer cache.
- Depends on: P03, P10, P12; infrastructure baseline stabilized by P07.

### P19 — Prepare large-file and storage growth paths

- [x] Documented defer decision: retain the current bounded API/resumable upload paths until upload volume and transfer latency show a bottleneck; any direct storage upload must bind scoped access, expiry, checksum, limits, and server verification.
- [x] Added a retryable object-cleanup queue for expired/completed upload chunks; owner/provenance contracts remain enforced by existing upload sessions.
- [x] Recorded a conservative retention policy: preserve active/recoverable generation replay and uncertain-effect receipts; keep broader pruning disabled pending measured growth and retention requirements.
- Done when: adopt/defer decision documented. The adopted cleanup path still requires migration and retry/recovery qualification before release.
- Depends on: P01–P03, P04.

## Stage 6 — Conditional alternatives and scaling decisions

Evaluate these explicitly; do not install all of them. Each decision records baseline, prototype evidence when warranted, cost, failure modes, migration/rollback work, and a revisit trigger.

| ID / task | Trigger and work | Acceptance / dependency |
| --- | --- | --- |
| A01 — Shared notification and Redis decision | **Selected PostgreSQL LISTEN/NOTIFY** for wakeups, with durable SQL replay and bounded polling. Defer managed pub/sub while its extra service does not meet a measured need; see [P14–P16 notes](performance/P14_P16_Implementation_Notes.md). | Decision recorded; production listener activation remains gated on connection-budget and cross-replica measurement. Derived-data caching remains a separate decision. Depends P03/P05/P11. |
| A02 — Managed workflow pilot | Evaluate one noninteractive batch task if custom worker operations/retries are burdensome. Compare Render Workflows with existing jobs; assess scheduling, preview support, startup delay, and idempotency. | Adopt only with demonstrated operational/cost benefit; no added interactive chat delay. Depends P14/P16. |
| A03 — Advanced orchestration review | Consider Temporal or equivalent when human waits, compensation, and workflow versioning exceed current job capabilities. | Written requirements/fit decision; migration only if justified. Depends A02 and concrete feature demand. |
| A04 — Read replica/cache evaluation | Use traces to identify read-heavy, stale-tolerant workloads after query optimization. | Explicit consistency/lag policy; current context and read-your-writes stay on primary. Depends P09/P16. |
| A05 — All-Vercel backend comparison | Prototype representative requests only if operations/cost remain problematic. Account for durable execution, streaming, connection limits, authentication, uploads, and observability. | Comparable workload and cost report; migrate only with clear net benefit. Depends P07/P14/P16. |
| A06 — Managed containers/queues comparison | Evaluate AWS or another suitable platform if placement, scale, compliance, or economics demand more control. | Total operating cost, staffing, portability, and rollback assessed; no speculative migration. Depends P16/P20. |
| A07 — Transport decision | Retain SSE for token/status delivery. Evaluate WebSockets only for a concrete bidirectional feature. | Evidence of product need; replay/auth/backpressure maintained. Depends P15/P17. |
| A08 — Geographic expansion | Review actual distant-user latency. Prefer workspace home regions; define residency, routing, fencing, failover, and migration before writes span regions. | Data consistency and recovery design precedes deployment; no premature global active-active database. Depends P20/P21 and traffic evidence. |
| A09 — Orchestration/sharding threshold | Assess Kubernetes, database sharding, or capacity-counter partitioning only after measured operational/lock/scale limits. | Document defer decision and measurable revisit trigger unless evidence justifies a prototype. Depends P16/P20. |

Review status: A02–A09 have been evaluated against current triggers. A02–A06 and A08–A09 are deferred with explicit revisit conditions; A07 retains SSE. See [remaining execution audit](performance/Remaining_Execution_Audit.md).

## Stage 7 — Capacity validation and production rollout

### P20 — Load, resilience, and autoscaling qualification

- [x] Add a safe local fixture-profile runner for baseline/growth/burst and document the hosted staging workload/fault matrix in [P20–P22 readiness](performance/P20_P22_Operational_Readiness.md).
- [ ] Run the P02 scenarios against isolated staging with real PostgreSQL, provider, workers, notes, and multiple tabs; exercise the documented provider/pool/notification/restart/lease/rolling-release faults.
- [ ] Size warm capacity and scaling bounds from hosted queue age, active work, latency, memory, DB limits, and provider quotas; configure cooldowns/graceful scale-down only after resource and plan limits are measured.
- [ ] Publish measured supported load, SLO results, costs, and remaining bottlenecks. Recheck plan-specific scaling capabilities before configuration.
- Done when: agreed workload and correctness/error objectives pass, with explicit limits instead of an unlimited scalability claim.
- Depends on: P07–P18; P19 if adopted.

### P21 — Restore and operational readiness

- [ ] Agree the proposed RPO/RTO, verify database/object backup coverage and complete an isolated restore exercise.
- [x] Write operator runbooks for pool exhaustion, stale leases, delayed reminders, failed saves, provider outages, quotas, and deployment rollback; performance alerts link to relevant procedures.
- [x] Add a new-feature checklist covering latency budget, queue class, authorization, idempotency, retention, and observability.
- Done when: restore evidence and operational ownership exist; alerts link to actionable runbooks.
- Depends on: P04–P05, P16.

### P22 — Controlled rollout and final comparison

- [x] Keep serialized backend-first deploy, frontend staging/pair gate, manual promotion, and rollback thresholds; add a post-promotion public alias/commit compatibility gate.
- [x] Add a comparison utility for matching diagnostic snapshots that rejects insufficient samples, scope mismatches, missing metric pairs, and excessive p95 regressions.
- [ ] Observe hosted latency/errors, note integrity, queue age, provider costs, and context/mode quality for the representative window; exercise rollback and drain old services only after recovery evidence.
- [ ] Publish actual before/after results and unresolved items; mark alternatives adopted/deferred with measured revisit criteria.
- Done when: production meets the agreed workload objectives, preserved-feature checks pass, and rollback remains documented.
- Depends on: P20–P21 and relevant alternative decisions.

Status corrected 2026-10-11: production run #21 released bc6f3b7 and applied schema 0085; frontend/backend pair gates passed. Bounded production probes did not demonstrate improved latency. P20 representative isolated qualification, P21 accepted recovery objectives/restore evidence, and P22 controlled comparison/rollback remain open. No paid hosting or production burst load was activated. See [current audit](performance/Performance_Plan_Audit_2026-10-11.md) for each task and [release observations](performance/Production_Release_and_Latency_2026-10-11.md) for measurement limits.

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
