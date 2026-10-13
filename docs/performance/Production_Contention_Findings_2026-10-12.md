# Production contention findings — October 12, 2026

## Released

Coordinated release 24 succeeded: https://github.com/harshilgor/Open-Learn/actions/runs/38214582459 . Application commit `7e4775e6816906ea82bac81508fe8b872d420bb3`; PR 28 merged. Backend/frontend quality, production build, migration check, deployment and promotion verification passed. Hosting, database pool configuration and region placement were not changed.

The release separates `database_connect` from `database_pool_acquire`, retains total checkout timing and adds protected process pool-capacity snapshots. Periodic agent/identity object cleanup is bounded to 30 seconds, preserving explicit stale-output cleanup and task polling.

## Measurements

A fresh Chrome tab restored the earlier synthetic conversation. One additional inertia prompt ran with that existing context, so this is not an identical fresh-session before/after comparison. No fleet load, p95 or complete feature qualification is claimed.

| Measurement | Time |
| --- | ---: |
| Prompt accepted | 16.819 s |
| First text received | 59.727 s |
| First text committed | 59.737 s |
| Prompt completed | 81.121 s |
| Synthetic note creation HTTP POST | 3.307 s |
| Warm note update HTTP PATCH | 7.942 s |
| Warm edit to observed Saved status | approximately 12.089 s |

The request creating the generation returned HTTP 202 in 15.827 seconds. Its trace recorded **8.304 seconds in pool acquisition**, **5.720 seconds in SQL execution**, and no connection-opening stage. The note PATCH returned HTTP 200 and recorded **5.587 seconds in pool acquisition** and **1.384 seconds in SQL execution**, also with no connection-opening stage. Pool acquisition includes pool bookkeeping and waiting; new DBAPI connection creation is measured separately. These samples point to contention for existing pooled connections, not new-connection opening, as a significant contributor. Acquisition/SQL/identity/admission stage aggregates may overlap; do not sum them as a wall-time decomposition.

The previous release's initial inertia prompt had first text at 94.477 seconds, versus 59.737 seconds here (approximately 37% lower as an individual observation). Existing context, background traffic and load differ. This does not prove the cleanup change caused that improvement. Warm note PATCH is essentially unchanged versus the previous 8.002-second observation. All remain above targets.

## Next infrastructure step

Keep the database in Virginia and prepare a colocated replacement API there. Start with the existing embedded feature set on paid API compute to measure placement/compute changes before introducing worker connection load. The proposed 1-CPU/2-GB API was previously quoted at $25/month compute; recheck the quote before provisioning. Preserve the old API as a rollback target and stage the frontend before promoting its new API origin.

Then activate independent workers with a verified whole-fleet budget and server-pool setting. The confirmed Supabase shared pool has 15 server connections per user/database, whereas the proposed full topology has 17 steady application connections. The prepared 60-total-connection checker passing is therefore insufficient for full activation. Include deployment overlap, other clients and listener sessions. Do not change pool size or add workers blindly.

Supabase organization usage is over free quotas; address the quota plan before committing to expanded hosted operation. This is a separate operational decision and not proof of the latency cause. No paid activation has been authorized or performed in this step.

## Evidence

`outputs/performance/production-release24-final-timings.json`, `production-release24-tutor-timings.json`, `production-release24-browser-proof.png` and `production-release-24-success.jpg`. Content-free API/generation timings are captured through the production UI. CPU utilization, PostgreSQL locks, per-generation provider wait and full process-pool occupancy have not yet been captured in this measurement.
