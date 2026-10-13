# Infrastructure contention execution

## Confirmed hosted state

Read-only dashboard inspection confirmed Render's live `openlearn-api` is Free, Oregon, `python -m backend.app.hosted_runtime api-free`, on commit `faa1961`. Supabase's Open Learn project is Nano in `us-east-1` (Virginia). Supabase's shared pool configuration allows 15 PostgreSQL server connections per user/database combination and 200 client connections. These are different limits, neither is the application's five-connection pool. Dashboard configuration does not establish actual utilization or lock pressure.

The organization shows exceeded free usage quotas and a restriction warning for October 27 if over quota persists. Egress is 7.33/5 GB. This is not proof that quotas caused the measured latency.

## Implemented locally

- Preserve total database checkout timing and add `database_connect` for new DBAPI connection establishment and `database_pool_acquire` for acquisition excluding that establishment. The latter includes pool bookkeeping and queue waiting; it does not measure SQL execution or later pre-ping. Frontend diagnostics retain both new stages.
- Protected process performance snapshots include current pool size, checked-in/out connections and overflow, without URLs, credentials or SQL.
- Agent background cleanup is limited to one sweep per 30 seconds. Explicit stale-output cleanup remains immediate, and task polling is unchanged.
- Learning-worker identity object cleanup is limited to one sweep per Store per 30 seconds. Job pickup, recording reconciliation, material processing, usage enforcement and other existing cleanup cadences are preserved.
- Python compilation, whitespace and prepared Blueprint connection-budget checks pass. Behavioral tests and production measurements for these changes have not run. These changes are not deployed yet.

## Cutover sequence

1. Release diagnostics/cleanup changes on the current topology, collect pool/connect/query/hold/queue/context/provider timing during the same synthetic browser sequence, and inspect active PostgreSQL sessions/locks. Do not infer pure pool saturation from the older combined checkout metric.
2. Prepare a Virginia API and the existing six independent roles from `deploy/render-paid.yaml`. Keep Supabase data in place; no database migration is needed for this placement change. Provisioning must wait for explicit approval of paid resources and a current quote.
3. Resolve the Supabase quota plan before adding worker connection load. Recompute the server/client connection budget using the confirmed 15-server pool setting, all services sharing each database role, and deployment overlap. The existing 60-total-connection budget alone is insufficient to approve the shared-pool topology.
4. Keep generation notifications on a session-compatible connection; do not move LISTEN to transaction pooling. Decide workload connection modes only after validating prepared statements, advisory locks and transaction semantics.
5. Start independently supervised workers, verify readiness/heartbeats and the complete feature inventory, then switch API to external mode. Do not disable embedded workers before replacements are verified. Drain the old executor before overlapping role ownership; retain fencing and idempotency.
6. Stage the Vercel frontend against the new API, verify authenticated notes/chat/browser/In-Class/reminders/mode/context flows, then promote. Keep the old topology available for rollback, with a single authoritative writer configuration.
7. Compare identical browser prompts and note updates. Targets: acceptance p95 <750 ms, short-answer first text p95 <2500 ms, note-save p95 <1000 ms, with the plan's required sample counts. Increase replicas/pools only when connection/server budgets and measurements support it.

No hosting purchase, pool-setting change, credential change or region cutover was performed during this preparation.
