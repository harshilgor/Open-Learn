# Hosted activation and production measurements

Observed October 10, 2026 PDT. Hosting remains free by the user's instruction.

## Activated release

The production API and frontend were both qualified at commit
`594ed773065909e9f3a23f6288bef48d2976e620` before the measurements.
Frontend deployment: `dpl_4G5ozEkWcAANW2JSxTYEwyzZpE9P`.
Production origin: https://open-learn-eta.vercel.app.
API origin: https://openlearn-api-saku.onrender.com.

The release gate passed readiness, schema head `0083_live_branching_observability`,
protocol, capabilities, both commits, and the frontend API-origin fingerprint.
The compiled browser origin was checked independently. Render auto-deploy was
disabled by deploying explicit commits. Render's probe is now `/live`.

## Real browser measurements

Three synthetic prompts were sent through the signed-in production UI. The
first greeting failed admission with the three-second candidate pool timeout.
The previous ten-second free-host timeout was restored and the next two prompts
completed. Browser timers start at enqueue, so include request preparation.

| Scenario | Accepted | First text received | First React commit | Completed |
| --- | ---: | ---: | ---: | ---: |
| Short inertia explanation | 5,591 ms | 58,013 ms | 58,030 ms | 66,784 ms |
| Context follow-up about a braking bus | 9,072 ms | 59,845 ms | 59,851 ms | 68,500 ms |

The follow-up used the preceding concept correctly. These are two observed
successful responses, **not** p95/p99 estimates, a load qualification, or proof
that every mode/recommendation path is qualified. No provider/model change was
made. The greeting failure was retained in the evidence rather than excluded.

The inertia execution trace recorded 269 SQL executions totaling 21,252 ms,
66 checkout observations totaling 43,660 ms, context preparation 26,468 ms,
provider first delta 4,804 ms, first persisted text 51,215 ms, and generation
execution 61,901 ms. Timings can overlap across lease renewal and execution;
do not sum them as sequential stages. SQL header durations are totals per
request, not a measurement of one statement. The execution's mean SQL duration
is approximately 79 ms; the distribution and causes need further profiling.

Note creation returned 201 in 3,748 ms. Existing-note autosave returned 200 in
7,811 ms and the editor displayed Saved. One note list read took 14,662 ms.
Two earlier note reads failed during the overloaded/rollout interval. The
synthetic note is named “Performance measurement — synthetic.”

Warm public probes: `/health` 200 in 112 ms (API headers 2.9 ms), cached `/ready`
200 in 43 ms (API headers 2.6 ms), `/release` 200 in 1,202 ms. These are individual
probes, not cold-start or availability statistics. Free Render can still sleep.

Content-free evidence is retained under ignored `outputs/performance/`:
`hosted-activation.json`, `production-browser.json`,
`production-browser-after-budget.json`, `production-browser-final.json`, and
`production-generation-trace.txt`. The bounded browser buffer keeps 200 API
samples; earlier note samples are in the intermediate snapshot.

## P05–P07 scope

- P05: per-role pools, zero overflow, bounded HTTP concurrency, observable waits,
  session-pooler verification and rollout budget enforcement are implemented.
  Prepared full-fleet envelope includes the backup cron: 54 of 60 connections,
  with 20 reserved. Live free API uses one shared five-connection pool and a
  ten-second wait. Burst performance remains unqualified.
- P06: cheap liveness, coalesced shared-pool readiness, startup schema checks and
  explicit deep diagnostics are live. Database degradation remains visible.
- P07: Virginia blueprint, costs, secret mapping, drain ordering and rollback
  procedure are prepared. Paid provisioning and actual cutover were deferred
  by the user. Existing Supabase quota/backup risks therefore remain unresolved.

## Release automation

GitHub Production now has the database migration credential, service-scoped
Render deploy hook, Open Learn-scoped 90-day Vercel token, and a dedicated
protected metrics token. Four non-secret host identifiers/origins are configured.
Credentials were transferred only to the requested environment and are not in
source or measurement artifacts. Vercel CLI token creation returned 403; the
dashboard's nested project selector supported the narrower project scope.

The workflow runs one serialized migration, deploys an explicit backend commit,
checks migration ownership, builds/stages the frontend, reads protected metadata
with authenticated `vercel curl`, pair-gates, promotes and captures diagnostics.
Vercel Git auto-deployment is disabled in configuration to avoid racing this job.
The first complete automated execution and its final results are recorded below
after qualification. No paid infrastructure is created by this workflow.

## Next performance work

Prioritize the existing P08–P11 tasks: remove synchronous database work from the
event loop, reduce context/admission round trips, eliminate repeated optional
fetches, and batch event/cancellation persistence while preserving fencing and
durable replay. The measurements do not support a sub-millisecond model response
goal on this hosting. Optimizing the request path remains necessary even if a
future regional/compute upgrade is approved.
