# Open Learn release failure audit and prevention plan

Audited 11 October 2026. New production workflow dispatches are paused at the user's request. The changes described below are prepared locally; this audit did not deploy or promote anything.

## What actually went wrong

The main cause was an outdated release branch combined with late, incomplete preflight checks. Local `origin/main` was stale. A fresh fetch showed that the candidate omitted the already-merged Vercel verification fixes from PR #26. GitHub runs the workflow file from the branch selected in the dispatch form, so successful fixes on `main` did not protect this older candidate.

I should have fetched and reconciled current `main` before preparing the release. My first explanation that the concurrency failure was flaky was also incorrect: the job deliberately used external workers, while the test implicitly expected embedded execution.

| Run | Confirmed failure | Production effect | Prevention |
| --- | --- | --- | --- |
| [#16](https://github.com/harshilgor/Open-Learn/actions/runs/38169766846) | The concurrency test expected `preparing`; CI's external-worker API correctly returned `queued`. | Release job skipped. | Explicit execution mode in that test; local qualification uses CI's external-worker environment. |
| [#17](https://github.com/harshilgor/Open-Learn/actions/runs/38170201687) | The attempted scheduler adjustment still could not execute work in an API configured for external workers. | Release job skipped. | Correct the test environment rather than weakening concurrency assertions. |
| [#18](https://github.com/harshilgor/Open-Learn/actions/runs/38170479333) | Missing `OPENLEARN_FRONTEND_ORIGIN` in the GitHub Production environment. | Stopped before migration/deployment. | Aggregate validation of all required configuration before writes. The origin setting was added during the preceding release attempt. |
| [#19](https://github.com/harshilgor/Open-Learn/actions/runs/38170863118) | `vercel curl ... --token=...` forwarded `--token` to native curl, which rejected it. The fix already existed on current `main`, but this candidate lacked it. | Database and API updated; staged frontend built; promotion skipped. | Fresh-main ancestry check, shared authenticated metadata reader, and the exact metadata access path exercised before migration. |

The failed pairing step did not establish an actual frontend/backend incompatibility. During this audit, the corrected metadata reader fetched the existing candidate successfully, and the real candidate/API compatibility gate returned `passed: true` with no errors. Vercel documents that native curl flags are forwarded by [vercel curl](https://vercel.com/docs/cli/curl); the wrapper now uses existing environment/local authentication and does not append `--token` to that subcommand.

## Current production state

Read-only observations during this audit:

- API: commit `9e26d74e65463f1f9362302c290a5b389eadaaba`, schema `0085_object_cleanup_queue`, compatible status, embedded workers, release-owned migrations.
- Public frontend: commit `658215528c15b1333a9ee73c155c074d98ae55bf`, previous schema contract `0083_live_branching_observability`.
- Existing staged frontend: `https://open-learn-31e3exjun-harshils-projects-a18ce240.vercel.app`, commit `9e26d74e65463f1f9362302c290a5b389eadaaba`. Its pairing check against the current API passed.
- Render service: free plan, Oregon, Docker, not suspended, auto-deploy disabled, liveness path `/live`. No hosting upgrade was made.

The public frontend was not promoted by run #19. A failed workflow is not a rollback: migration and backend deployment completed. These metadata observations do not certify every user feature or measure the performance improvement. Do not downgrade the database or restore an older backend blindly; its schema contract may no longer accept the migrated database.

## Controls prepared locally

1. **Reconcile current main.** The local candidate incorporates the latest main fixes. The workflow fetches current `main` and requires it to be an ancestor of the candidate, both before quality jobs and immediately before hosted preparation. A dirty local candidate or wrong immutable SHA fails preflight.
2. **Default to preflight.** The workflow adds an `operation` input defaulting to `preflight`. This performs configuration checks, existing-service reads, and a local compiler build. Migration, API deployment, candidate upload, and promotion require `operation=release` explicitly.
3. **Report all configuration blockers together.** The preflight validates required origins, identifiers, migration URL shape, transaction-pooler port, hook/service association, metrics access configuration, linked Vercel project, project root, Node version, and compiled public API origin. Error output names problems without exposing credential values.
4. **Exercise the same frontend reader early and late.** One reader handles baseline access, staged-candidate access, production alias verification, and standalone validation. It uses `--fail`, bounded timeouts, JSON/contract shape validation, and explicit error categories. Authentication and command errors fail immediately. Only transient read failures and expected-commit propagation get bounded retries; it never retries deployment writes.
5. **Compile before migration.** The matching Vercel environment is pulled and the frontend compiled before production writes. The preflight compiler validates routing while deferring future schema qualification to the mandatory deployed backend/candidate gates. The same compiled artifact is uploaded after the backend passes. This distinguishes a build check from a successful hosted release.
6. **Validate immutable metadata and the actual alias.** An explicit Open Learn release SHA takes precedence over inherited Vercel Git metadata. The staged candidate and public production origin must independently report the expected commit and API fingerprint. Malformed reports produce specific errors instead of an unhelpful generic probe failure.
7. **Reject workflow regressions offline.** YAML duplication, reintroduced curl token flags, missing production-write conditions, unsafe phase order, absent pairing gates, automatic alias promotion, and missing failure evidence are checked before deployment. GitHub Actions syntax is also checked with [actionlint v1.7.12](https://github.com/rhysd/actionlint/releases/tag/v1.7.12), downloaded from its official release with pinned SHA-256 verification.
8. **Reduce environment drift.** Platform jobs use Ubuntu 24.04; Node 24 is verified against project configuration; the Vercel CLI remains pinned. Quality-run cancellation groups distinguish PR/push checks from checks called by a release. Production release jobs remain serialized and are not cancelled in the middle of mutation.
9. **Explain partial failures.** A final phase summary and evidence artifacts run even on ordinary failures. They distinguish completed migrations/deployments, unstarted promotion, and writes that may have partially completed. No pulled environment files, tokens, or raw CLI credential diagnostics are uploaded. A forcibly terminated runner can still prevent final artifact collection.

## Failure coverage and recovery

| Potential problem | How it is caught or contained | Recovery |
| --- | --- | --- |
| Old branch reintroduces a fixed bug | Fetch current main and enforce ancestry before quality and preparation. | Reconcile main locally; qualify a new immutable candidate. |
| Invalid YAML, duplicate keys, unsupported Actions syntax | Local/CI policy validation plus pinned actionlint. | Repair locally before dispatch. |
| Local tests differ from CI worker/provider settings | Explicit test execution modes; qualify under CI settings. | Fix the environment or the implementation; retain the original behavioral assertion. |
| Missing/expired credentials or wrong GitHub environment | Aggregate configuration check, Vercel pull, metadata reader, diagnostics access probe. | Correct only the identified configuration; do not repeatedly deploy to discover the next missing value. |
| Wrong Vercel team/project/root/Node version | Pulled project identity/root/runtime check before compilation. | Reconcile linked settings before any production writes. |
| Stale public API URL compiled into the frontend | Compare pulled public origin with the approved release API origin. | Correct matching environment configuration and rebuild. |
| CLI argument parsing changes | Pin CLI; use one tested wrapper; exercise the exact command early; policy rejects the historical bad flag. | Change/test the wrapper once, not each workflow independently. |
| Login HTML, redirects, malformed metadata, wrong commit | HTTP failure flags, JSON/type checks, immutable commit and API fingerprint gates. | Inspect authentication/routing/version cause; never treat HTTP 200 alone as proof. |
| Temporary frontend warmup or alias propagation | Bounded read retries for transient fetch failures/expected commit propagation. | Stop after the bound; inspect the existing deployment. Do not create another deploy as a retry. |
| DB unreachable, mismatched heads, transaction pooler | SELECT-only migration-connection probe and comparison with API heads before writes. | Repair the connection; verify the approved project identity separately. |
| DB belongs to another project but has identical schema | **Not proved by matching heads.** Current preflight explicitly reports this limitation. | Add an opaque installation identity marker or provider project identity verification before approving a database cutover. |
| DDL privilege, lock timeout, unsafe migration, data shape | Static migration inventory, serialized migration ownership, migration tests; preflight cannot prove future DDL execution. | Require a bridge release and isolated PostgreSQL migration/rollback qualification for new schema work. Do not blindly downgrade production. |
| API startup, resource exhaustion, worker-role mistakes | Provider deploy qualification, `/ready`, `/release`, execution topology, connection budget, protected diagnostics. | Inspect the existing service/deploy receipt before retrying; use a compatible forward repair or reviewed code rollback. |
| Frontend compile failure | Actual target-environment compiler runs before migration/API deployment. | Fix and rebuild without production changes. |
| Candidate upload failure | Exact phase is reported; production alias is still gated. | Inspect whether a candidate already exists, then resume deliberately. |
| Pairing mismatch | Mandatory backend and staged frontend contract/commit/origin gates. | Retain the public alias; repair the staged candidate/configuration. |
| Promotion succeeds but public check fails | Read actual alias metadata; bounded propagation checks; phase report records completed promotion. | Verify or restore the prior qualified alias. Failure does not automatically undo promotion. |
| Diagnostics fail after a successful release | Early metrics authentication probe; final state distinguishes diagnostics from deployment phases. | Repair observability and run read-only verification; do not redeploy a healthy pair just to collect a report. |
| Concurrent releases or automatic provider deployments | Serialized workflow, separate quality cancellation groups, Render auto-deploy confirmed off, Vercel Git deployments disabled in repository configuration. | Keep one release owner; recheck dashboard configuration when hosting changes. |
| Dependency/tool updates change results | Node, runner and CLI pinned; lockfile-based npm install. Python dependency ranges remain a source of drift. | Produce reviewed Python lock/constraints and controlled dependency update jobs; qualify fresh installs on the target platform. |
| AI provider quota, DB quota, network outage, cold starts | Runtime telemetry and functional/performance smoke measurements after compatibility qualification. | Address the measured bottleneck or outage. A successful release check does not guarantee a latency SLO, and free hosting can still cold start. |

## Local evidence

- Current-main reconciliation completed without merge conflicts.
- Backend regression set under `OPENLEARN_WORKER_MODE=external`, deterministic provider, development identity: **131 tests passed**. Subsequent focused tests covering the final audit changes: **25 passed**.
- Frontend release metadata tests: **2 passed**. The preceding GitHub frontend quality run had **48 passed**.
- Production compiler in the preflight phase: passed after supplying matching production-shaped public/proxy origins. An intentionally mismatched local public origin was rejected before compilation.
- Release workflow policy: passed. Actionlint: passed for all three platform workflow files.
- Migration contract inventory and connection budget checks: passed (54 peak connections including reserves, 6 remaining).
- Corrected real Vercel metadata read: passed for the existing staged candidate.
- Real staged candidate/current API pairing gate: passed, with exact commit, schema, capabilities, API origin and migration ownership.

## Conditions before another production attempt

Commit and review this local candidate, including current main, then run **preflight only** with the real GitHub environment. That hosted preflight has not been executed for these new controls. It must pass without migrations, deployments or promotions. Inspect its baseline, routing, DB probe and compiler evidence before explicitly selecting a production release.

Python dependency locking, verified database installation identity, isolated PostgreSQL failure/restore drills, and full hosted user-flow/performance qualification are further protections. They are not claimed as completed by this audit. The paid/isolated hosting proposal remains unprovisioned under the existing free-hosting decision.

Unexpected provider/runtime failures will remain possible. The objective is to catch predictable errors before production changes, preserve a usable deployment when a later stage fails, and make the resulting state clear enough to recover without repeated blind runs.
