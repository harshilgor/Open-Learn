# Remaining phase implementation — 11 October 2026

## Changes in this working tree

These changes are local. They have not been pushed or deployed, and no production speed improvement is claimed.

| Phase | New implementation |
| --- | --- |
| P03 | Tab-local profiling opt-in survives navigation/remounts and supports explicit `performance=0`; dedicated structured logger sink; bounded query-shape counts, failures, total/max duration in protected diagnostics. No SQL text or bound parameters are exported. |
| P09/P13 | Hosted note lists/pages/search decode authoritative rows from one owner-scoped query, removing per-note database reads and filesystem cache writes. Empty search uses a bounded page. PostgreSQL primary-key storage writes use one atomic upsert rather than an existence query followed by a write. Deterministic social replies return before unnecessary branch/history context reads, retaining the existing routing guards. |
| P11/P15 | Durable generation replay joins events and terminal status into one committed database snapshot, reducing repeated stream reads without replacing the durable event log. |
| P17 | Authenticated navigation summaries coordinate through Web Locks and short-lived in-memory BroadcastChannel snapshots, scoped by a digest of the existing credential/origin/header key. Mutations and account changes invalidate across tabs; snapshots are bounded and expire within 500 ms. Authority reads, mutations, streams, unauthenticated calls, SSR and caller-abortable reads remain outside this sharing path. Hidden-tab browser discovery/calendar polling pauses, resumes on visibility, and calendar operation reads cannot overlap. Active browser streams/class capture remain intact. |
| P09 diagnostics | `postgres_performance_probe` captures read-only activity/lock aggregates and a redacted note-page EXPLAIN plan, with query/lock/connect timeouts. It uses a dedicated URL variable and never exports owner values, SQL filters or credentials. |
| P18 evaluation | `model_latency_evaluation` compares explicit routes on synthetic cases with output/time/call bounds and a conservative tariff-based spend gate. It does not switch the production route or declare unreviewed answers quality-qualified. |
| P20 | Existing profile runner can use an explicitly isolated localhost PostgreSQL database. It rejects `DATABASE_URL`, hosted endpoints and database names outside `openlearn_qualification_*`. Each concurrent sample now has a distinct synthetic owner, avoiding misrepresenting one account's admission cap as a many-user profile. Added a disposable localhost-only PostgreSQL Compose environment. |
| P21 | `qualification_restore` performs dump/restore between distinct isolated localhost qualification databases, refuses nonempty targets, bounds subprocess/query durations and compares table counts and row digests. Credentials stay out of argv/output. It does not claim object recovery or production backup readiness. |

## Local environment commands

Start Docker Desktop's engine before these commands. The engine was unavailable during this implementation turn.

```powershell
docker compose -f deploy/compose-performance.yaml up -d --wait
$env:OPENLEARN_QUALIFICATION_URL = 'postgresql+psycopg://qualification:local-disposable-qualification@127.0.0.1:55432/openlearn_qualification_local'
python -m backend.scripts.performance_qualification --database-url-env OPENLEARN_QUALIFICATION_URL --profiles baseline,growth,burst --samples-per-scenario 100 --out outputs/performance/local-postgres-profiles.json
```

The local password is for the disposable localhost database, not a production credential. This profile remains an application/fixture measurement: no real provider, browser paint, external worker process, cloud network or hosted quota is emulated. The output retains `productionQualification=false`.

For an actual PostgreSQL diagnostic, supply `DATABASE_DIAGNOSTICS_URL` and `OPENLEARN_PROBE_OWNER` through the environment, then run:

```powershell
python -m backend.scripts.postgres_performance_probe --out outputs/performance/postgres-probe.json
```

For model comparison, provide a JSON list of synthetic `{ "id": "scenario", "prompt": "..." }` cases, explicit model routes and verified input/output tariff ceilings. The tool refuses a request exceeding its stated estimated budget. Review correctness/context quality separately; provider-only first text is not browser first text.

For restore rehearsal, create a second empty `openlearn_qualification_*` database and provide separate source/target URL environment variables:

```powershell
python -m backend.scripts.qualification_restore --source-env OPENLEARN_QUALIFICATION_URL --target-env OPENLEARN_RESTORE_QUALIFICATION_URL --out outputs/performance/restore-rehearsal.json
```

`pg_dump` and `pg_restore` must be installed. Synthetic source activity must be stopped during a consistent comparison. The tool never drops a schema or database.

## Completion boundaries still open

### Continuation results

The Windows sandbox blocked asyncio loop initialization in `socket.accept`, before any request ran. A bounded stack capture identified the cause. The disposable fixture ran successfully outside that restriction with provider credentials disabled. No production load or provider evaluation was performed.

The fixture exposed a roughly five-second completion delay: terminal events were committed directly to SQL, but local subscribers were not awakened. The generation executor now wakes local replay readers after its terminal commit, including when PostgreSQL notifications are disabled. The subsequent **200-attempt baseline** completed without failures (100 greetings and 100 short tutoring attempts): acceptance p95 **36.167 ms**, first text p95 **199.344 ms**, note save p95 **35.288 ms**, completion p95 **308.510 ms**. An earlier 13-attempt observation before the fix had completion p95 **5621.464 ms**; unequal sample counts prevent treating that as a qualified before/after percentile comparison.

Larger local SQLite profiles completed all attempts after the harness was repaired to count setup failures. The 10-user profile had **4 failures / 200 attempts**; the 50-user profile had **104 failures / 200 attempts**, with database-lock errors in the captured logs. These profiles **failed qualification**. They do not measure the hosted PostgreSQL/provider topology. Retained artifacts are `outputs/performance/remaining-local-profiles-baseline.json`, `remaining-concurrency-profiles.json`, its profile files and log. Timing results precede the last ownership-read batching change and are working-tree measurements, not immutable release evidence.

Additional implementation completed:

- Owner-active checks reuse an already-held PostgreSQL share lock only within the exact transaction/savepoint; device revocation and expiry checks remain uncached. Graph/scope/job payload reads combine resource ownership and data retrieval in one SQL read.
- Shared generation transport is implemented behind `NEXT_PUBLIC_OPENLEARN_SHARED_GENERATION_STREAMS=true`, **off by default**. Credential/API/generation scoping, bounded replay, account-change cleanup, gap fallback, hidden-leader handoff and reader cancellation preserve the server event log as authority. Its multi-tab behavior still requires qualification before enabling it.
- Provider input-prefix caching is implemented behind `OPENLEARN_PROVIDER_PREFIX_CACHE_ENABLED=true`, **off by default**. It preserves the full current context and generates a new answer each time. Cache-read/write metrics are retained. Enabling it requires a pinned cache-write tariff; reserves and missing-cost settlement use the conservative input/write rate. The evaluator supports repeated synthetic prefixes and cache metrics; no cache benefit is yet demonstrated. See [OpenRouter's current caching contract](https://openrouter.ai/docs/guides/best-practices/prompt-caching).
- Active usage reconciliation retains event polling, visibility/focus refresh and reset-time refresh, with a slower 60-second full-snapshot watchdog to reduce duplicate polling.
- The paid proposal's connection budget now includes the previously omitted generation worker. Explicit three-connection API/generation pools match the Blueprint: **17 steady application connections, 56 peak including overlap/reserves, 4 remaining of 60**. Listener connections come from these existing pools. The quality workflow now verifies every Blueprint role against that budget. This is a sizing check, not a passing hosted load test.
- `performance_acceptance_gate` rejects missing scenario/region samples, unmet absolute latency targets, invariant violations, missing fault exercises, restore/rollback gaps and incomplete observation evidence. It never grants deployment approval.

Full frontend TypeScript checking now passes after correcting test-file type declarations. Backend compilation and the Blueprint/connection-budget check pass. Behavior regressions and shared transport/cache exercises remain unexecuted.

### Render purchase recommendation

The live service was rechecked through Render: free compute, Oregon, `api-free`, one instance, automatic deployment off. Render's **Pro workspace** is **$25/month plus compute** and does not itself give this API more CPU/RAM. A **1c-2g API** costs **$25/month**, and each **0.5c-512mb worker** costs **$7/month**. The prepared API plus six-worker topology therefore costs **$67/month base compute**, excluding database, AI, cron, bandwidth and taxes; a Pro workspace would add another $25/month. These prices were checked against [Render pricing](https://render.com/pricing) and [compute plans](https://render.com/docs/compute-plans). Paid compute removes free-service idle spin-down; Pro adds operational features such as autoscaling and isolated previews. Neither guarantees the latency objective or eliminates SQL/network waits.

Recommend the specific compute/placement/worker change before buying the workspace subscription for speed. No paid resources have been provisioned. Paid activation requires a change to the user's existing free-hosting constraint. Docker startup was attempted, but a bounded engine probe still reported its Linux engine pipe unavailable; local PostgreSQL/restore execution remains blocked on an available engine or equivalent isolated database.

- **P04/P20/P21/P22:** real fault/load/rollback/restore exercises and a controlled observation window are execution requirements, not completed by adding scripts.
- **P07/P14/P15/P16:** the live region cutover, independently provisioned roles and PostgreSQL listener are still inactive. The existing keep-hosting-free instruction remains in effect; no paid services were created.
- **P09:** actual hosted query plans/lock evidence and justified index decisions await the diagnostic connection. No speculative production index was added.
- **P17:** navigation reads and hidden polling are improved; shared generation streams and history virtualization still need their own correctness/profile evidence. The new coordination must be qualified across authentication changes and simultaneous mutations before rollout.
- **P18:** actual route/cache/quality measurements remain necessary. The evaluator can now record repeated-prefix cache reads/writes, but it does not emulate all context modes or approve a cheaper model automatically.
- **P21:** accepted RPO/RTO and verified cloud database/object backup coverage still require operational evidence and a product decision.

## Validation performed

### Updated qualification evidence

An isolated PostgreSQL 17.11 runtime replaced the unavailable Docker engine. Separate API/worker fixture profiles completed **600 attempts without failures** after queue-scan coalescing, incremental prose parsing and context batching. First-text p95 was **158.758 ms at one user, 907.217 ms at ten users, and 3952.065 ms at fifty users**. Note-save p95 was **29.411 / 64.784 / 77.301 ms**, respectively. The fifty-user first-text objective remains unmet. These are local synthetic-provider measurements, not production SLO evidence.

Seven isolated generation fault checks passed: API-process independence, notification-loss replay ordering, cross-process cancellation, worker-crash partial preservation, stale-owner rejection, absence of automatic provider retry and capacity recovery. A database restore matched integrity across **233 tables in 5.375 seconds**. Cloud recovery, object backup coverage and accepted RPO/RTO remain unqualified.

The approved restricted OpenRouter key completed three real Haiku 5.5 tutor prompts in the same conversation: short explanation, contextual follow-up and topic switch. First-text times were **2087.362 / 1451.368 / 1256.220 ms**; completion times were **2457.617 / 1960.785 / 1630.378 ms**. Exact usage-ledger cost totaled **$0.0003994**. Context remained relevant in these three examples; this small local sample does not qualify all modes, quality or hosted latency.

Following those measurements, the first meaningful text fragment now commits immediately rather than waiting for the normal token batch threshold. Subsequent fragments retain batching. Provider usage telemetry now follows the asynchronous request context into finalization threads. Compilation and whitespace checks pass. A repeat real-model probe failed at provider authentication with HTTP 401; it stopped after the first failed prompt. The temporary key is no longer usable. Neither subsequent change has a qualified real-model latency result yet. Retained evidence: `outputs/performance/latest-postgres-worker-profiles.json`, `streaming-postgres-generation-faults.json`, `postgres-restore-rehearsal.json`, `real-tutor-probe.json` and `real-tutor-first-flush-probe.json`.

The older Docker/PostgreSQL blockage and statements that no real provider or restore exercise ran are superseded by this section. Hosted role activation, multi-tab browser qualification, prefix-cache comparison, regional load and cloud recovery remain pending.

Python compilation, whitespace checks, Blueprint pool-budget matching and the full frontend TypeScript check passed. The previously reported test-file typing errors were repaired without changing their assertions. The model evaluator command imported and exposed help without calling a provider. Local load profiles were executed as recorded above: the 200-attempt baseline passed, while growth/burst profiles failed. No behavior regression suite, paid provider comparison, PostgreSQL/restore exercise or new production prompt was executed during this continuation.

Rollback for application changes: deploy the previous compatible code pair without downgrading schema. No new schema migration is introduced here. The qualification database and scripts are independent of production; do not confuse a local fixture pass with a hosted SLO pass.

For local Vercel environment/deployment/log inspection, install the Vercel CLI with `npm i -g vercel`. The hosted release workflow retains its pinned CLI and does not depend on a global local installation.
