# Scheduled cloud browser release runbook

October 14, 2026. Application release deployed; worker handover in progress. Incremental two-worker budget approved up to $14/month. Render inventory showed the Virginia API and the Oregon rollback API, with no Open Learn background workers.

## Stage and inspect

1. Deploy a reviewed commit containing this feature to the API with `OPENLEARN_SCHEDULED_BROWSER_ENABLED=false`. Existing embedded workers continue until handover.
2. Verify current API worker modes and inventory all execution roles. Preserve global worker mode for generation, learning, agent and class roles.
3. Create the proposed `openlearn-cloud-workers` environment group (the API currently has no linked group), then configure it with the same database, ownership/authentication settings, object storage, Browserbase settings and usage policy. No secrets in Git or reports. Shared workers do not require a new database.
4. Validate `deploy/render-scheduled-browser.yaml` with Render's current schema. Review the two services and budget, then sync only this file. Confirm both workers run the same commit as API.
5. Browser worker uses the dedicated browser role; notification worker alone runs routine actions/delivery. Observe heartbeats in authenticated `/internal/reminders/status`. One long browser operation may age heartbeat; correlate lease/queue progress before declaring failure.

## Handover

Set API `OPENLEARN_BROWSER_WORKER_MODE=external` and `OPENLEARN_NOTIFICATIONS_WORKER_MODE=external`; do not change global mode. Existing embedded browser thread must stop accepting work during shutdown; leases fence overlapping deploys. With scoped browser mode external, notification loop also leaves the API. Verify both replacement roles claim work and no API browser/notification thread remains. Check at least four additional DB pool connections fit the deployed total budget, including overlap.

External completion of previously admitted jobs remains recoverable from SQL. Enable `OPENLEARN_SCHEDULED_BROWSER_ENABLED=true` only after isolated PostgreSQL and real-provider tests pass. This gate applies to creation of new scheduled website work; existing admitted jobs are drained regardless of enrollment gate. Verify private sign-in readiness separately from public cloud browsing.

## Qualification

Use synthetic assignments and disposable accounts. Create one explicit-time read-only routine, close the app, observe due/task/ledger/conversation identities, restart browser worker during execution and recover. Expire login, resume same task with bound request/revision, then verify final summary and separate attention notice. Retry failed email transport using frozen body and idempotency key; browser task count must remain one. Confirm mobile and compact conversation results. Record exact SHA, config, timed measurements and cleanup.

Resend deduplication documentation: https://resend.com/docs/dashboard/emails/idempotency-keys (24 hours). Implementation caps automatic ambiguous resend at 23 hours from first attempt, with at most three durable delivery attempts. A provider acknowledgment is not receipt/read confirmation. Unresolved outcomes remain visible; do not blindly recreate delivery IDs.

## Rollback

Disable new scheduled-browser enrollment first. Keep external workers and compatible readers running to drain accepted jobs. To move ownership back, drain/suspend external owners before clearing API scoped overrides and redeploying embedded ownership. Verify leases, stopped Browserbase sessions and usage receipts. Never reset every run to queued. Reversing ownership does not require rollback of schema because this slice adds no migration.

## Pending external verification

Historical pre-provisioning checkpoint, superseded below: no workers provisioned at that point. The browser connection recovered after the earlier usage-limit review failure. A worker creation form is prepared; production credential access is approved and the scoped environment group has been created. No API credentials were exposed or settings changed. Isolated PostgreSQL 16 recovery and concurrent completion checks passed in GitHub CI run 38538051411. Authenticated real-provider acceptance and hosted measurements remain pending.


Local PostgreSQL qualification command (explicit disposable localhost database only): set `OPENLEARN_SCHEDULED_BROWSER_TEST_DATABASE_URL`, then run `python -m pytest backend/tests/test_scheduled_browser_jobs.py -q`. The fixture creates and drops a fresh random schema per case. Never point it at production. Without that variable, the PostgreSQL concurrency case is explicitly skipped and the ordinary suite uses isolated SQLite files.


## October 14 activation findings

The approved `openlearn-cloud-workers` environment group was created in Render (`evg-db7k000473hc73dltn2g`). Five unrelated voice/media/metrics credentials were excluded; values were not copied into source or reports. At this historical checkpoint workers were not yet provisioned; the handover record below supersedes it.

The implementation is published on `codex/scheduled-cloud-browser-jobs`, including current main through da89556. Live `/release` reported deployed commit ece49127d2ea678d6a06d04949677d0ad4ba85d3, actual/expected schema 0088_memory_sensitive_enable, embedded worker mode. Current main/release branch expects 0091_class_evidence_indexes. These intermediate migrations belong to earlier In-Class work; this browser slice adds no migration. Do not start workers from the new branch against schema 0088 and do not weaken startup schema checks. Qualify and perform the existing coordinated migration/API release first, then verify both workers on the same schema/commit. Standby prevents claiming jobs, but it does not bypass database compatibility.

Worker Blueprint defaults `OPENLEARN_CLOUD_WORKER_STANDBY=true`; after qualification remove standby only during the owned handover. Disable API embedded browser and notification execution using the scoped overrides, preserve all other execution owners, then verify replacement heartbeats and claims. Keep scheduled-browser enrollment disabled until live authenticated acceptance passes.

## Scoped connection envelope

Run `python -m backend.scripts.check_connection_budget --budget deploy/scheduled-browser-connection-budget.json --blueprint deploy/render-scheduled-browser.yaml` before syncing. The proposed workers use three steady pooled connections; allowing deployment overlap, two migration and two listener connections, and thirty reserved connections yields forty against the configured sixty-connection envelope. Verify the actual production database limit and current role pools before handover; this prepared envelope is not an observed database capacity measurement.

## Provisioned topology and handover record

Production release 38541099134 passed, deploying 12c40b21f332016c85a73fdbc600fc83a784a45f and schema 0091_class_evidence_indexes. The two approved Virginia Starter workers are browser srv-db7rkek9v7es73d3h76g and notifications srv-db7rkek9v7es73d3h760 ($14/month combined, excluding usage/taxes). Both passed live startup at that SHA in standby. Blueprint auto-sync is off; service auto-deploy is off.

The bootstrap Blueprint deliberately retains standby=true. Active service overrides must be documented and reapplied deliberately after a manual Blueprint sync. Never sync the bootstrap file onto active owners without accounting for the resulting pause.

Handover completed: API scoped overrides are external, global mode remains embedded, both worker runtimes have standby=false on commit 12c40b21, and fresh running heartbeats were verified.

The Oregon rollback API was not updated in this release. Before routing traffic there, deploy a reviewed schema-compatible image; the old 0088 image is not a verified rollback against schema 0091. Do not weaken the schema gate.

## Current delivery configuration

In-app inbox and conversation delivery are active and passed the hosted synthetic probe. Email activation is deferred until the user owns a dedicated verified sender domain. Keep OPENLEARN_REMINDER_EMAIL_ENABLED disabled. Do not reuse the Morni integration key or sender. Preferences report emailAvailable=false until the flag, API key, sender, web origin and owner recipient are configured. Verify sender DNS before enabling email and qualify delivery to the opted-in user address.

## Verified private-profile candidate

PR #52 fixes current Browserbase Live View host compatibility. Isolated hosted candidate probe passed owner denial, profile persistence and clearing, termination, deletion, settlement and real signed-link expiry (old link denied after 65 seconds; new link connects to same session). Cost $0.008. Before Canvas qualification deploy the reviewed candidate, verify matching API/browser commits, and activate the private-profile readiness flag only against this evidence. Scheduled-browser enrollment stays off until the actual authenticated routine/restart acceptance passes. Obtain explicit consent to store the user's Canvas sign-in with Browserbase and let the user complete campus login/MFA; never request the password in chat.
