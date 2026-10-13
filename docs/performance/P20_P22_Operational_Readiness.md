# P20–P22 capacity, recovery, and rollout readiness

Updated: 2026-10-11. This document records executable local qualification tools
and operator procedures. It does not claim hosted capacity or restore readiness.
Production remains on the free Render API in Oregon with Supabase in Virginia;
paid provisioning and hosted load/restore exercises remain unapproved.

## P20 — Load, resilience, and autoscaling qualification

### Safe fixture qualification

Run the three P02 concurrency profiles against disposable SQLite and a
deterministic provider:

```powershell
python -m backend.scripts.performance_qualification `
  --profiles baseline,growth,burst `
  --samples-per-scenario 100 `
  --out outputs/performance/p20-fixture.json
```

This produces one report plus per-profile artifacts. Its only chat scenarios
are greeting and short tutoring; each attempt also updates a synthetic note and
checks a stale revision conflict. The current tool can qualify local fixture
regressions, but it does not emulate provider wait, PostgreSQL contention,
separate worker pools, browser tabs, or production resource limits. The output
therefore always sets `productionQualification` to `false`.

### Hosted staging procedure

Do not run burst loads against production. Once an isolated staging deployment
exists, use the P02 workload at 1/10/50 concurrent-user profiles, at least 100
eligible samples per scenario/profile, and the actual production build,
PostgreSQL pooler, provider route, worker roles, and browser surfaces. Run a
separate test account with a provider-cost cap. Include chats, note edits during
generation, reminder/agent/class jobs, multi-tab replay, and upload work. Keep
accepted, queued, first-provider-delta, first-persisted-text, browser-first-text,
completion, and note-save timings separate. Track failures and cancellations
alongside successful percentiles.

Capture before each scenario: commit, schema heads, region, instance sizes,
pool limits, worker count, provider/model/rate version, sample count, and test
account budget. Use `/operations/performance` snapshots and the browser's
content-free timings. Label each measurement as fresh, resumed, cold, or warm.

Exercise these fault cases in staging with an explicit stop condition and
synthetic data only:

| Fault | Exercise | Required invariant |
| --- | --- | --- |
| Provider slowdown/rate limit | Inject latency and 429/5xx responses in the provider test double or controlled provider stub. | UI remains responsive; no duplicate provider charge; retryable state is durable and understandable. |
| Database pool pressure | Hold staging connections up to the configured pool budget, then release. | Bounded waits and clear retryable errors; no unbounded task/thread growth; notes and generation state remain consistent. |
| Notification loss | Disconnect the PostgreSQL listener and suppress wakeups. | Durable replay/polling catches up in sequence; reconnect does not duplicate text or cancellation effects. |
| API/worker restart | Gracefully stop, then separately hard-stop a staging process during queued and active work. | Leases fence old owners; queued work is claimed once; uncertain partial provider work is not silently retried. |
| Expired lease | Advance an isolated test clock or expire a synthetic lease. | Recovery reconciles capacity exactly once; old owner writes are rejected. |
| Rolling release | Deploy bridge backend, migrate additively, stage frontend, then interrupt each boundary. | Old and new compatible code preserve note integrity, replay, mode/context, and worker ownership; rollback never downgrades schema. |

P15–P16 service-level regressions cover pieces of these paths, but staging
fault injection and multi-process evidence are not yet recorded. Report memory,
CPU, pool wait, connection hold, queue age, active/expired leases, provider
quota, and lock wait at each concurrency point. Choose warm capacity and
autoscaling bounds from these observed limits; do not enable scaling that would
exceed the Supabase connection budget. Record cooldowns and graceful scale-down
behavior. Publish the tested maximum as a measured limit, not an unlimited
scalability claim.

### Current evidence and gate

The local fixture baseline and two hosted prompt traces are in
[hosted measurements](Hosted_Activation_and_Measurements.md). Those two
responses took about 58–60 seconds to first browser text and are not an SLO or
load qualification. No production burst test is permitted by this protocol.
The local profile runner now writes a phase-tagged artifact before SQLite
bootstrap and checkpoints after each completed sample; the supervisor allows
ten minutes per profile. This makes migration stalls observable but does not
create a passing P20 fixture result by itself. P20 remains open until that
harness completes and
isolated staging fault/load evidence, thresholds, and a costed capacity
decision are attached to the release commit.

## P21 — Restore and operational readiness

### Recovery objectives and backup scope

Workload targets in `workload.json` are engineering objectives, not achieved
SLOs. For planning, propose **RPO ≤24 hours** and **RTO ≤4 hours** for the core
learning database; a product owner must accept or revise these before treating
them as commitments. Object recovery must meet the same RPO or document a
separate one. The live database quota/backup policy and object-store versioning
and retention have not been verified; do not assume that the current free plans
provide the needed backups.

Inventory and record coverage for: Supabase PostgreSQL (schema and user data),
S3-compatible materials/recordings, encryption and access configuration,
retention, and the independent identity-revocation journal. Provider API keys,
OAuth grants, deployment credentials, and environment secrets are not restored
from data backups. Keep recovery credentials in the approved secret manager.
Portable account export is not an infrastructure backup and cannot resume
execution state; see `identity_data.py`'s compatibility manifest.

### Isolated restore exercise

Run this only with a separate scratch project/database and scratch bucket or
isolated object prefix. Do not point a restore tool at the production endpoint
or overwrite production data.

1. Record backup timestamp, source region, commit/schema heads, object inventory,
   and encryption-key references without recording credentials.
2. Restore the database into an empty isolated target using the provider's
   supported restore workflow. Restore objects into a separate bucket/prefix,
   preserving object keys, checksums, metadata, and version references.
3. Start the reviewed API build against the restored database with outbound
   notifications, email, provider execution, scheduled consumers, and every
   worker disabled. Use read-only credentials for initial inspection.
4. Verify migration heads, row counts for core tables, foreign-key/integrity
   checks, owner boundaries, and a sample of note/material/recording object
   references and SHA-256 checksums. Verify that deleted identities stay
   revoked using the independent journal before enabling any traffic.
5. With an isolated synthetic account, verify login, session read, note read and
   revision-safe save, context read, and replay read. Keep external effects
   disabled. Record elapsed restore/validation time and missing-object count.
6. Destroy the scratch resources after evidence review. Never copy user data
   into a shared preview environment.

The exercise passes only when the agreed RPO/RTO are met, core records and
referenced objects validate, revocation checks pass, and a second operator can
repeat the written steps. Current infrastructure backup/restore credentials and
an isolated recovery target are not available in the repository, so this live
exercise remains pending.

### Operational runbooks

<a id="database-pool-exhaustion"></a>
#### Database pool exhaustion

1. Check checkout p95, checked-out count, database connection count, and lock
   waiters in the performance snapshot. Separate slow SQL from pool wait.
2. Check API/worker replica counts against `deploy/connection-budget.json` and
   verify no duplicate embedded and external consumer fleet is running.
3. Stop adding replicas or jobs. Drain only a known-safe worker role; do not
   terminate active generation owners without following the lease procedure.
4. Find the longest connection holds and transaction/lock spans. Fix the
   request/transaction path before increasing pool size; preserve reserved DB
   headroom. Restart only if a connection is demonstrably stuck.
5. Confirm pool waits return to baseline and notes/chat work recovers.

<a id="slow-api"></a>
#### Slow API / event loop

1. Compare API headers, event-loop lag, SQL execution, context preparation, and
   provider first-delta stages. These overlap; never sum them as sequential time.
2. Check CPU/memory pressure, restarts, cold start, and active long-lived streams.
3. Keep accepted generation IDs and outbox drafts. Do not ask users to resubmit
   while a generation may still be running. Use durable status/replay before
   retrying a provider request.

<a id="queue-health"></a>
#### Queue delay, expired lease, or lost wakeup

1. Check oldest queued age, active counts, expired leases, worker role/commit,
   notification listener state, and DB availability.
2. Durable SQL is authoritative. Verify the queue row and lease owner before
   restarting or retrying. Never clear a lease/capacity counter by hand while
   its worker may still be alive.
3. Let the bounded poll/recovery loop reconcile a stopped listener. For an
   expired active generation, follow the explicit uncertain-provider-effect
   path; do not auto-reissue a potentially charged request.
4. Verify one terminal outcome, no duplicate effects, and queue-age recovery.

<a id="failed-note-saves"></a>
#### Failed note saves

1. Preserve the local owner-scoped draft. Distinguish cloud-save failure from
   list-refresh failure; never label a local draft as cloud-saved.
2. On a revision conflict, read the current server revision and offer recovery;
   do not overwrite with a stale retry. Retry only the existing idempotent
   existing-note update path. Do not retry note creation blindly.
3. Verify the saved body and revision after recovery; preserve local data until
   the cloud state is confirmed.

<a id="provider-outage"></a>
#### Provider outage or rate limit

1. Check provider status, 429/5xx/rate-limit headers, configured route/model,
   remaining budget, and whether any text was already persisted.
2. Keep the request's durable state and usage receipt. No automatic provider
   retry is allowed after partial output or uncertain dispatch.
3. Retry only through the learner-visible idempotent retry action after the
   prior execution is terminal and its usage reservation is reconciled.

<a id="delayed-reminders"></a>
#### Delayed reminders

1. Check scheduler/cron heartbeat, oldest due reminder, notification delivery
   status, and database pool pressure. Confirm that exactly one reminder
   consumer is active.
2. Do not replay a delivered notification without checking its idempotency key
   and delivery ledger. Recover overdue reminders in bounded batches.
3. Verify the user's timezone, next due time, and single delivery receipt.

<a id="quota-and-rollback"></a>
#### Quota or deployment rollback

1. For quota warnings, identify the owning Supabase organization/project and
   inspect database/storage/egress/backups before increasing capacity. Do not
   delete user data to fit a limit.
2. Stop release promotion. Inspect migration, backend deploy, and frontend alias
   state independently. A failed workflow does not mean nothing changed.
3. Restore the last compatible frontend alias and deploy the prior compatible
   backend commit through the release runbook. Keep additive schema changes;
   never downgrade schema as ordinary rollback.
4. For separate workers, drain/fence every role and restore matching versions.
   Check note integrity, context/mode, cancellation/replay, reminders, and queue
   ownership before declaring recovery.
5. A database/object restore is a distinct, potentially data-losing disaster
   recovery action; require the isolated restore procedure and an approved
   recovery decision.

<a id="feature-readiness"></a>
#### New feature readiness checklist

- [ ] Assign a latency budget to each user-visible stage and define the success
  and failure metrics before implementation.
- [ ] Select interactive/background queue class; define admission bounds,
  fairness, expiry, timeout, and scaling budget.
- [ ] Enforce owner authorization at every read/write boundary; test revocation
  and cross-owner access.
- [ ] Define idempotency keys, cancellation semantics, retries, fencing, and
  behavior when an external side effect has an uncertain result.
- [ ] Define data/object retention, backup coverage, deletion, and restore
  behavior; do not add a TTL that can break replay or recovery.
- [ ] Add content-free traces, queue age/failure counters, actionable alerts, and
  a linked runbook.
- [ ] Qualify migration compatibility, load/failure cases, and rollback before
  frontend behavior depends on the feature.

## P22 — Controlled rollout and comparison

`platform-release.yml` serializes releases per environment, runs quality,
performs one migration, deploys the backend first, gates a staged
frontend/backend pair, promotes only after that pair gate, then checks the
public production alias against the expected backend/frontend commits. This
preserves the expand/contract order. A post-promotion alias gate failure must
stop the release and use the rollback procedure rather than automatically
undoing an uncertain deployment. Production must set the
`OPENLEARN_FRONTEND_ORIGIN` environment variable for this check.

Before release, record the baseline diagnostics snapshot, commit and deployment
IDs, schema, queue/lease state, and frontend/API origins. After promotion,
record the production pair gate and diagnostics. Observe representative
workload for at least 30 minutes, then capture another metrics snapshot. Use:

```powershell
python -m backend.scripts.performance_compare `
  --before outputs/performance/before.json `
  --after outputs/performance/after.json `
  --minimum-samples 100 `
  --max-p95-regression-percent 20 `
  --out outputs/performance/comparison.json
```

The diagnostics artifact records API scope and best-effort release metadata.
The comparison tool fails closed on missing/mismatched scope, insufficient samples,
missing metric pairs, or a p95 regression above the threshold. Its exit success
means only that the comparable metrics did not cross that threshold; it is not
release approval. Separately review note integrity, correctness/context/mode,
queue recovery, provider cost, and the rollback/restore evidence.

For this project, stop promotion or roll back the compatible frontend/backend
pair if the release gate fails, a required capability/schema check fails, there
is any confirmed lost acknowledged note, duplicate external effect, owner
boundary violation, unconfirmed mode transition, or unreconciled generation
lease. Investigate a sustained >20% p95 regression, >1% unexpected failure
rate, or queue age over 30 seconds; do not scale blindly past the DB budget.
Expected revision conflicts and learner cancellations are reported separately.

Keep previous deploys and matching worker commits until rollback and recovery
coverage are documented. Retire old services only after a successful rollback
exercise and an observation window with no lost notes, duplicate consumers, or
expired unexplained leases. Attach before/after reports and unresolved risks to
the release commit.

### Completion status

- P20: local fixture-profile runner and staging fault matrix prepared. Hosted
  baseline/growth/burst qualification and autoscaling sizing remain pending;
  production is not subjected to burst traffic.
- P21: operational procedures and feature checklist prepared. Accepted RPO/RTO,
  verified provider backup coverage, isolated restore exercise, and assigned
  operational owner remain pending.
- P22: same-environment serialization, backend-first staging, compatibility
  gates, and manual rollback are implemented; post-promotion production alias
  gate and measurable before/after comparison are being added. Hosted rollout,
  observation window, and rollback rehearsal remain pending.
