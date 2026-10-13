# Remaining performance plan execution audit

> Historical snapshot: local-only and unapplied-migration status statements below are superseded by [the current audit](Performance_Plan_Audit_2026-10-11.md). Production release #21 deployed bc6f3b7 and schema 0085. Performance acceptance remains unmet.

Reviewed: 2026-10-11 against the task-wise plan, checked-in implementation
notes, local measurement artifacts, and the current workspace state.

## What has actually been executed

- P03 instrumentation is in production. It captured two successful browser
  prompts and one failed admission. These are trace samples, not a workload or
  fleet qualification. The successful prompts took 58.0–59.8 seconds to first
  browser text and 66.8–68.5 seconds to complete. The note observations were
  also slow (3.7 seconds to create, 7.8 seconds to save, and 14.7 seconds for
  one list read).
- The release workflow and hosted secrets were activated. A production pair
  gate and deployment were recorded for commit `594ed773065909e9f3a23f6288bef48d2976e620`.
  No hosted rollback rehearsal or 30-minute performance observation is recorded.
- The workspace contains a 10-attempt offline SQLite/fixture baseline and a
  separate four-attempt fixture run with no failures. They are useful local
  regression evidence only; their sample counts are below the 100-per-scenario
  percentile gate. A later P20 smoke artifact reports zero attempts and a
  failed child process. A follow-up invocation was interrupted before it
  produced a report, so it adds no passing qualification.
- P08–P19 implementation notes describe local changes. They do not show a
  deployed before/after comparison. Migrations `0084_generation_shared_wakeups`
  and `0085_object_cleanup_queue` are not applied to production.
- The normal chat admission path now uses the authenticated owner already cached
  by the browser-task request instead of making a duplicate `/v1/account` call.
  Cold local/other callers retain the fallback. This removes one avoidable
  round trip; it has not been released or measured in production.
- Chat generation now includes the selected Buddy presentation in its
  idempotent acceptance command and persists it in the same database transaction
  as the accepted message. Existing Buddy attribution is preserved; a missing
  chat attribution is resolved with the course/default Buddy. The regular
  generation path no longer waits for a separate `PUT /chats/{id}/mode`; the
  initial Learn/Journey path and explicit mode selection retain their required
  persistence. The new presentation field is excluded from the legacy request
  hash so an old accepted message can still be retried with its original key.
- Advisory mode classification remains after attachment/link preparation; its
  ordering is unchanged so failed preparation cannot leave a stale suggestion.
  Independent learner-visible effects are not reordered to make the benchmark
  look faster.
- Ordinary Ask/Learn mode classification now runs within generation admission.
  The response can accept a generation, include an advisory suggestion, or
  return a durable mode-choice receipt. A dismissed choice resumes the same
  outbox message; the dedicated browser and initial Learn Journey paths remain
  specialized. P02 replay/routing qualification remains open.
- Heavy Quiz, In-Class, Flashcards, Reminders, Visualization, and lecture-note
  components are dynamically loaded when their feature is first opened. A tab
  that has been visited remains mounted to preserve drafts and task state.
- Workspace note listing now has an owner-scoped keyset page (50 summaries by
  default, max 100) using the existing `(learner_id, updated_at)` index and an
  opaque `updated_at,id` cursor. The old full-list API remains for compatibility;
  the Notes workspace, chat picker, practice selector, and list refresh use the
  bounded endpoint. Title-repair maintenance is no longer on the synchronous
  list/open path.
- The local P20 fixture runner now writes a progress artifact before SQLite
  migration begins and after every completed sample. Timeout reports therefore
  distinguish a database bootstrap stall from a workload sample stall. Its
  supervisor timeout is 10 minutes; this does not qualify production capacity.
- The prepared Virginia Render services are grouped under a project environment
  for safer future multi-environment configuration. This YAML remains an
  unapplied paid proposal pointing at production secret-group wiring; it does
  not provision or isolate anything by itself.
- P05/P06 are active on the free deployment. The measured free service still
  uses one five-connection pool and a ten-second checkout wait. Burst behavior
  is unknown.
- Current workspace checks: frontend production build completed; changed-file
  ESLint completed with zero errors (12 warnings remain); backend Python syntax
  compilation and `git diff --check` passed. `tsc --noEmit` still reports stale
  generated `.next` route types and two existing test-file type mismatches; it
  did not report errors in the changed application modules. A complete backend
  regression run has not completed, so P02 correctness gates remain open.

## Remaining work and disposition

| Plan item | Disposition | Evidence needed to close |
| --- | --- | --- |
| P03 hosted/fleet qualification | Open | At least 100 comparable samples per scenario on the deployed pair, with cold/warm, success/failure and each request stage reported separately. |
| P04 hosted rollback rehearsal | Open | Staging rehearsal using production artifacts, including interrupted release boundaries and recovery of the compatible pair. |
| P07 paid Virginia cutover / quota remediation | Deferred by the user's keep-hosting-free decision | A new hosting/billing decision. The prepared project-environment blueprint is not an executed cutover and still references production secret-group wiring. |
| P09 indexes and pagination | Pagination implemented locally; measured indexes remain gated | Notes list paging now bounds summary/file reads at 50–100 rows and uses the existing owner/update index. PostgreSQL query plans and representative slow-query/lock traces after deployment must justify any additional index; none is added speculatively. |
| P12 unified admission contract | Implemented locally; P02 qualification remains open | Ordinary Ask/Learn mode classification now runs inside the generation admission request. The response can accept generation, return an advisory suggestion, or return a durable mode-choice receipt replayed by client message ID. Dismissing a choice resumes the same outbox message; accepted transitions retain the existing explicit confirmation flow. Buddy presentation remains part of idempotent acceptance. Specialized browser actions and initial Learn Journey planning keep their existing workflows. |
| P14–P16 external worker activation | Prepared, not active | The free Render service cannot run the proposed independent worker role. Keep embedded mode; do not deploy migrations 0084/0085 or enable PG listeners without a compatible release and pool qualification. |
| P17 cross-tab subscriptions / panel loading / virtualization | Partially optimized | Heavy workspace feature components now load on first tab use and visited tabs remain mounted. Concurrent browser-task snapshots are deduplicated for a matching session/account epoch, and streamed text batches at 40 ms locally. Cross-tab stream sharing/history virtualization still require request-volume and main-thread evidence plus replay/reconnect qualification. |
| P18 prompt caching / model benchmark | Deferred pending provider and quality evidence | Compare the current route and supported alternatives on the same P02 prompts for first-text latency, quality, reliability and cost. Keep model and context behavior unchanged until then. |
| P19 object cleanup queue | Implemented locally, release pending | Apply migration 0085 through a coordinated release, then qualify idempotent cleanup and retry recovery. |
| P20 hosted load, faults and autoscaling | Local runner made diagnosable; hosted qualification open | The local fixture now checkpoints before/after each sample. After the local Git release, create the isolated staging environment the user requested; qualify PostgreSQL, real provider, workers, multiple tabs, cost cap, fault injection, and 100+ eligible samples. Never run burst traffic against production. |
| P21 restore readiness | Open | Confirm/approve RPO and RTO, verify database and object backup coverage, and complete the documented restore into isolated scratch resources with a second operator. |
| P22 rollout comparison and rollback | Repository gates/tooling prepared; isolated rollout open | After Git release, use the isolated environment requested by the user to observe the representative workload for 30 minutes, attach before/after snapshots, verify correctness/cost, and rehearse rollback/drain. |

## Conditional architecture decisions A02–A09

| ID | Decision now | Revisit trigger |
| --- | --- | --- |
| A02 Managed workflow pilot | **Defer.** No evidence shows the existing job runner is the latency or operations bottleneck; adding a workflow service would create cost and another execution path. | A named noninteractive batch task repeatedly requires manual recovery or custom retry/scheduling work. Compare startup delay, idempotency, operations effort and total cost on that one task. |
| A03 Temporal or equivalent | **Defer.** No concrete human-waiting/compensation/versioned workflow requirement has been established. | A product feature requires durable human waits, compensations, or workflow-version migration that the current jobs cannot support safely. Reassess only after A02's pilot criteria are met. |
| A04 Read replica or cache | **Defer.** Current evidence does not identify a stale-tolerant, read-heavy query as a proven bottleneck; production context and read-your-writes require primary consistency. | PostgreSQL traces and query plans after P09 show specific read load dominates latency or pool capacity, and the owning product path accepts a documented lag policy. |
| A05 All-Vercel backend comparison | **Defer prototype until the app changes are deployable and comparable.** Production slowness is real, but current traces mix app work, database waits and provider delay; no controlled same-code host comparison exists. | After P08–P19 are released and P20 baseline is available, compare the same region/workload for first text, notes, failures, durable worker behavior and total cost. |
| A06 Managed containers/queues | **Defer.** P20 has not measured capacity limits, and the user chose to keep hosting free. | Measured queue, placement, compliance or cost limits cannot be met by the free topology; first produce a total-cost, staffing, portability and rollback comparison. |
| A07 WebSockets | **Retain SSE.** The current product needs server-to-client token/status delivery; no concrete bidirectional feature justifies replacing it. | A specific feature requires sustained client-to-server realtime messaging. Any prototype must preserve auth, replay, backpressure and reconnect semantics. |
| A08 Geographic expansion | **Defer.** We have no multi-region user latency distribution or residency requirement. The current Oregon/Virginia placement is a single-region placement mismatch, not evidence for active-active writes. | P20 measurements from actual distant-user regions show material network latency. Decide data residency, home-region routing, fencing, failover and recovery before deploying cross-region writes. |
| A09 Kubernetes, sharding or partitioned counters | **Defer.** No measured operational, database-lock or scale ceiling justifies these costs. | P16/P20 show a reproducible queue, lock or scale limit after simpler capacity tuning; document measured thresholds and migration/rollback cost before prototyping. |

## Execution boundary

The user chose to keep hosting free and said the local changes should be deployed
to Git before creating an isolated environment for P20/P22. No paid services,
production burst load, production database restore, production migration, Git
push, or deployment of current workspace changes was initiated in this pass.
P07 remains a prepared-only cutover. P20/P22 hosted work is sequenced after the
local Git release and requires the plan's correctness/recovery gates.
