# P01–P04 implementation record

Repository implementation and local validation complete; hosted instrumentation/pipeline activation and hosted rollout qualification remain pending. No production deployment, paid hosting change, or live migration was performed.

| Task | Delivered | Validation boundary |
| --- | --- | --- |
| P01 | Live runtime inventory, request-hop map, public audit script, drift findings | Hosting/CLI/public probes; pooler mode and authenticated runtime routing still explicit unknowns |
| P02 | 16 scenarios, load/quality assumptions, benchmark protocol, fixture baseline runner | Ten completed generation/revision scenarios, zero failures; real-provider/hosted load qualification later |
| P03 | Correlation, API/SQL/generation/browser spans, loop-lag sampling, protected queue/pool/lock diagnostics, private dashboard and threshold signals | Bounds/privacy/thread/stream checks and isolated API dashboard verified; production traces/fleet aggregation pending |
| P04 | Production build parity, quality/release workflows, schema/capability/commit gates, migration ownership, immutable backend deploy helper, staged frontend promotion and rollback runbook | Compiler and local pair gates passed; mismatch rejected; hosted CI/secrets/triggers and hosted rollback not activated |

## Code map

- backend/app/performance.py: fixed-label bounded registry, ASGI/SQL timing, content-free trace logs; metrics failures are best-effort.
- backend/app/release.py: explicit schema/capability metadata, guarded operator diagnostics, queue state and event-loop sampling.
- database.py: reviewed schema-head compatibility and instrumentation; original pool limits retained.
- generation_store/routes/service and identity_middleware: durable correlation and stage timing; existing context, accounting, cancellation, leases, and replay retained.
- web/lib/api-performance.ts, api.ts, generation-stream.ts, account-session.ts, hosted-api-proxy.ts: bounded content-free measurements and correlation propagation.
- use-chat-outbox.ts / learn-chat.tsx: enqueue origin and React first-text commit. Later chunks avoid history scans when no commit marker is pending.
- backend/scripts: deployment_audit, performance_benchmark, performance_report, check_release_contract, release_gate, release_migrate, render_release.
- deploy/release-contract.json, Dockerfile, Render proposals, desktop packaging: ship the contract and control migration ownership.
- web/scripts/build-production.mjs, package.json, vercel.json: shared asset preparation and production Next.js compiler.
- .github/workflows/platform-*.yml: offline quality, explicitly dispatched coordinated release, read-only pair validation.

## Evidence

Public health/readiness took about 2.4 seconds with no model call. No production speedup is attributed to this implementation because production has not changed.

Offline benchmark: 10 attempts at concurrency 1, zero failures; acceptance p50 24.332 ms, durable first text observed p50 84.577 ms, note-save p50 28.000 ms. Small-sample SQLite/fixture results do not qualify production latency or provider quality. Artifact: outputs/performance/p02-p03-offline-baseline.json.

Broad backend selection initially had 104 passes and five stale-fixture failures. Fixtures were updated for asynchronous execution and the current calendar routing contract; the follow-up selection passed 51 checks, including corrected cases and timing/release controls. Replay fixtures needed real sessions and accepted/queued events; all six replay checks passed after correction. Application behavior was not changed to satisfy stale assertions.

Broad frontend selection initially had 44 passes and three stale-fixture failures. Updated tutoring fixtures isolate browser admission, use the scoped storage key, and reflect current note formatting behavior. The affected follow-up passed all 18 checks; initial focused timing/transport selection passed 21. Runs overlap; do not sum into a fabricated unique total.

Production Next.js compilation, TypeScript, and static generation passed. Existing chart-size prerender warnings did not fail the build. Windows sandbox temp/socket/SWC restrictions required local temp paths or approved unsandboxed verification; those were environment issues.

An isolated loopback API with disposable SQLite, no model provider, external background mode, and explicit release SHA passed pair checks with the compiled frontend. An incorrect SHA was rejected. Schema drift and Render failure paths are covered. Private diagnostics generated an HTML/JSON dashboard; small sample count is not proof of health at load.

## Activation

Final follow-up: all 47 checks in the selected frontend suite passed. The final timing/retry/release selection passed 19 backend checks; API-origin pair-gate coverage then passed all 11 release checks. The diagnostic frontend selection passed four checks, including the added origin fingerprint case. An additional four-attempt fixture run at concurrency 2 had zero failures. These counts overlap earlier runs. API-origin validation, trace-log sampling, and final fixture results are recorded separately from production qualification.

The final rebuilt frontend used an explicit loopback staging API origin. Its origin fingerprint, protocol, capabilities, schema, SHA, and migration-owner pair gate passed against the restarted isolated API. A real HTTP note create/update/stale-write/read sequence preserved the newer body/revision and exposed content-free timing headers. Unauthenticated metrics access was rejected; authorized queue diagnostics succeeded. Artifacts: outputs/performance/final-staging-verification.json and .html. This is a local rehearsal, not a hosted rollout.

Follow [Release_Runbook.md](Release_Runbook.md) before applying templates. Configure matching hosted CI environments/credentials, reconcile dashboard auto-deploy and variable-group drift, bootstrap new metadata, and perform staged hosted validation. The production frontend build now deliberately requires a compatible backend endpoint; avoid frontend-first rollout.

P03/P04 live qualification stays open in the execution plan. Next: P05 process/connection budgeting, P06 cheap probes, P07 always-on Virginia placement and quotas. Independent generation remains P14. No claim of restored production latency, independent generation execution, or fleet-wide SLO achievement is made.
