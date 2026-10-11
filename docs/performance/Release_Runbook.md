# Coordinated platform release and rollback

The [11 October release audit](Open_Learn_Release_Failure_Audit.md) records the recent failures and controls prepared locally. The revised workflow defaults to `operation=preflight`; production writes require `operation=release`. The new hosted preflight has not yet been dispatched. Always reconcile current main before selecting a release candidate.

P04 implements the pipeline, contract, and probes. This document distinguishes repository implementation from activating hosted CI/secrets or deploying to production. No live settings were changed during P01–P04 implementation.

## Release components

- platform-quality.yml: offline backend feature regressions, fixture baseline artifact, frontend regression checks, and production Next.js/webpack build with locally bundled visual assets. Local development retains its existing vinext workflow.
- platform-release.yml: explicitly dispatched staging/production preflight or release; fresh-main gate -> quality -> configuration/authentication/current-state probes -> matching frontend compiler -> one serialized PostgreSQL migration -> immutable Render API commit -> backend compatibility gate -> upload prebuilt frontend -> pair compatibility gate -> production promotion -> actual public alias gate.
- platform-release-validation.yml: read-only verification of an already deployed backend/frontend pair.
- deploy/release-contract.json: protocol/capabilities, required schema heads, explicitly approved compatible head sets, and migration ownership.
- /release: backend commit, supported capabilities, actual schema, migration ownership, and current execution topology. This is an explicit diagnostic call, not the routine health path.
- /api/release: frontend commit, required contract, and a fingerprint of the effective API origin. No keys or private configuration values are returned. Pair gates reject a frontend still pointing to a different API even if its version matches.

## Activation prerequisites

Create/use matching GitHub environments named staging and production. Configure existing credentials as environment secrets: DATABASE_MIGRATION_URL, RENDER_API_TOKEN, VERCEL_TOKEN. Configure variables RENDER_SERVICE_ID, OPENLEARN_API_ORIGIN, VERCEL_ORG_ID, VERCEL_PROJECT_ID, and (for production only) OPENLEARN_FRONTEND_ORIGIN. The frontend origin must be HTTPS with no path or query. The migration connection must point to the same approved database as the target API and use a connection mode suitable for Alembic/advisory locks. Never copy production data into staging without its separate data policy.

Where preview protection is enabled, provide the existing approved VERCEL_AUTOMATION_BYPASS_SECRET for read-only verification. The gate sends it only to the frontend origin; it never persists it. Missing/unusable protection access fails the probe; do not disable protections to make it pass.

Before enabling the release-managed runtime, validate the quality workflow on the candidate commit, run the single migration job, and set OPENLEARN_RELEASE_MIGRATIONS_EXTERNAL=true plus OPENLEARN_MIGRATE_ON_START=false on the target service. The revised free template retains embedded workers; the paid proposal explicitly uses external workers and shared migration flags. No paid proposal is provisioned by this work. Remove the old paid pre-deploy migration command when adopting the coordinated pipeline.

Existing free services without the new external-migrations flag preserve their bootstrap behavior. The new pipeline requires the deployed metadata to confirm single-release-job ownership before building/promoting the frontend. A bootstrap release of the new backend is needed because the current production API returns 404 for /release. Keep the existing frontend serving throughout that first activation.

The pipeline initially deploys the current single API service. When independent workers are provisioned in later tasks, extend the release job to deploy/drain all configured roles with the same immutable commit before publishing dependent frontend behavior. Generation still runs in the API at this stage and is reported honestly in metadata.

Production Git-based frontend auto-promotion and Render On Commit deployment must not bypass qualification. P01 observed the Render dashboard setting differing from YAML, and no linked shared variable group. Reconcile both before activation. Select the coordinated pipeline as the release owner or configure hosting deployment checks. Adding files does not change dashboard settings. Production builds also require matching public/proxy API configuration and a compatible live backend, guarding against frontend-first merges and stale origins.

## Expand/contract procedure

1. For an additive schema change, first publish a bridge backend that tolerates both current and reviewed next schema shapes; list those exact head sets in compatibleSchemaHeads. Update schemaHeads to its code migration head; CI checks inventory consistency. Never approve an unknown head automatically.
2. Validate the bridge against both shapes and record rollback compatibility. Perform the single migration job.
3. Deploy compatible backend/workers, then dependent frontend behavior. Frontend gates require its target schema, not merely an old compatible shape.
4. Retain old fields and behavior until rollback is no longer required and old consumers have drained. Remove them in a later contract release.

P01–P04 needs no new database migration. Its compatibility changes are additive headers/metadata and diagnostics. Unknown or unapproved schemas fail closed. A manifest assertion does not prove behavioral compatibility; staging regressions and restore checks remain required.

## Verification and rollout

Run platform-quality. Validate a representative staging pair with:

```text
python -m backend.scripts.release_gate --api https://STAGING_API --expected-sha FULL_BACKEND_SHA --frontend https://STAGING_FRONTEND --expected-frontend-sha FULL_FRONTEND_SHA --require-external-migrations
```

Run the workload scenarios before qualifying a production performance improvement. P04's compatibility probe is not a full functional, cost, availability, or load certification. The initial private dashboard and SQL/stream trace collection must be exercised on the hosted services after deployment.

Record prior backend commit/deploy ID, prior frontend deployment, schema heads, queue/lease state, and compatibility evidence. Release concurrency does not cancel an in-progress deployment/migration. Render deploy POSTs are not blindly retried: if transport fails after submission, inspect Render for the existing deploy before creating another.

Stage production frontend using --prod --skip-domain and promote only after pair gates succeed. Production configuration is used for that staged build. The release workflow then checks the promoted public frontend alias against the exact backend/frontend commits and API origin before capturing protected diagnostics. If that check fails, stop and follow the rollback procedure; do not assume promotion was undone. Publish the observed latency/error/cost comparison and retain the workload artifact alongside the commit.

## Rollback

1. Stop further release/promotion work. Inspect whether migration or backend deployment already changed state; a failed workflow is not an automatic rollback.
2. Restore the previously validated frontend deployment alias using Vercel rollback. Select the deployment built for the correct environment.
3. Deploy the previous compatible backend commit through Render after checking compatibility with the current schema. An expand migration normally remains in place; never downgrade schema or restore over live data just to recover code.
4. For separate workers, drain/fence consumers and restore matching compatible roles. This requires later generation-worker/lease qualification; the current API still owns generation lifetime.
5. Run compatibility plus note integrity, context/mode, cancellation/replay, and reminder checks. Monitor errors and queues through recovery. Record the incident and any user-visible interrupted work.

If the prior code cannot read the current schema, use a forward repair/bridge release. Backup restore is a separate recovery operation with RPO/RTO and data-loss consequences, covered by P21. Do not treat it as ordinary deployment rollback.

## Evidence from this implementation

The production compiler build succeeded. An isolated loopback API using a disposable migrated SQLite database and the compiled frontend passed protocol/capability/schema/full-commit/migration-owner checks. An intentionally incorrect commit was rejected. Unit integration checks exercise schema drift and Render failure so failed backend work cannot proceed to frontend promotion. Hosted secret activation and actual hosted rollout/rollback have not been executed.

Official references: [Render deployment API](https://api-docs.render.com/reference/create-deploy), [Vercel staged deployment](https://vercel.com/docs/cli/deploying-from-cli), [Vercel deployment checks](https://vercel.com/docs/deployment-checks).
