# Virginia rollback runbook

## Current authoritative configuration

Virginia API `srv-db68giu7bikc73fipn6g`: embedded workers, $25/month compute. Oregon API `srv-db1jh5c9v7es73fseqv0`: external worker mode, free compute. Both use the existing Supabase database. See `deploy/production-topology.json` for origins. Do not downgrade or restore the database merely to roll back application code.

## Trigger

Rollback when authentication, durable admission, replay, note persistence or background processing fails after cutover, or sustained latency/error measurements show an unacceptable regression. Confirm the deployed schema remains compatible with the rollback source; never start old code against an incompatible schema.

## Execution

1. Freeze release dispatches and capture deployed commits, pending/running generation and job counts, current frontend origins and execution modes. Do not retry accepted provider calls blindly.
2. Prepare Oregon on the compatible application commit in external mode. Verify `/ready`, `/release`, schema compatibility, object storage and authentication. Keep migration ownership with the release job.
3. Stop accepting new Virginia work through the coordinated traffic change; drain active tasks with leases/fencing intact. Redeploy Virginia with `OPENLEARN_WORKER_MODE=external`. Verify the old executor has stopped before enabling Oregon's embedded workers. Generation execution mode needs separate verification: `/release` workerMode alone does not prove no generation task remains active.
4. Redeploy Oregon with `OPENLEARN_WORKER_MODE=embedded`. Verify ready status and background heartbeat/job pickup. Recover interrupted tasks using existing fenced recovery; never forcibly reset all running jobs.
5. Set both Vercel Production `OPENLEARN_API_ORIGIN` and `NEXT_PUBLIC_LEARNING_API_URL` to Oregon. Create a fresh source build: prebuilt deployments cannot adopt changed settings. Stage and verify authenticated chat, replay, contextual follow-up and note save before promotion whenever the deployment mechanism permits staging.
6. Retarget GitHub Production `OPENLEARN_API_ORIGIN`, `RENDER_SERVICE_ID` and `RENDER_DEPLOY_HOOK_URL` to Oregon together. Keep hooks secret. Run operation `preflight` and verify the frontend origin fingerprint.
7. Repeat synthetic notes/chat and one queued task; inspect failures and pending jobs. Record the incident, timings and final execution ownership. Keep Virginia available until recovery is established; suspending/deleting it is a separate decision.

## Verification and limits

`python -m backend.scripts.verify_production_topology --out outputs/performance/topology.json` verifies the current Virginia topology against the deployed commit's contract. For a rollback, supply a topology file with active/rollback origins reversed and the expected mode. It does not execute a rollback or prove all job owners have drained. The earlier isolated generation fault rehearsal covers recovery mechanics; no disruptive live rollback drill has been performed. The free Oregon service can cold-start and is a degraded-speed emergency fallback.

No passwords, tokens or database contents belong in the runbook or Git. Local Vercel CLI is absent; installing `npm i -g vercel` would enable direct environment and deployment inspection. Existing CI uses its pinned CLI.
