# P01 deployment and request-path inventory

Observed Oct 10, 2026 PDT; public probe timestamp 2026-10-11T03:51:01Z. Read-only hosting inspection; credentials were not exported.

| Layer | Verified observation | Evidence / boundary |
| --- | --- | --- |
| Frontend | open-learn-eta.vercel.app; READY deployment dpl_CREZ2Pia6HECsCbP6Le3KYGG3F3E; iad1 functions | Vercel CLI inspect; created Oct 10 19:31 PDT |
| API | openlearn-api-saku.onrender.com; srv-db1jh5c9v7es73fseqv0; Free, Oregon; main; f53b96fa0859d992960f2208a07054ddc5468fd2 | Render deployment/settings |
| Runtime | python -m backend.app.hosted_runtime api-free; deploy/Dockerfile; repository build context; /ready health path | Render Settings |
| Runtime flags | AI_TUTOR_ENV=production; OPENLEARN_WORKER_MODE=embedded; OPENLEARN_MIGRATE_ON_START=false | Selected non-secret environment values read and re-hidden |
| Model | openrouter; anthropic/claude-haiku-5.5 | Selected non-secret configuration; no key/tariff exported |
| Storage | OPENLEARN_OBJECT_BACKEND=s3 | Live configuration and adapter source |
| Database | Open Learn apxwjejimdzcvyosejzy; Virginia us-east-1; t4g.nano; healthy | Supabase overview |
| DB snapshot | CPU 4%, RAM 58%, disk 15%, 16/60 connections | Not sustained capacity or application pool occupancy |
| Quota | Organization restriction warning from Oct 27 if still over quota | Organization-wide; project attribution unavailable |
| API pool | Five connections, zero overflow, ten-second checkout timeout per process | Deployed source; upstream pooler mode requires P05 verification |
| Trigger drift | Render dashboard shows On Commit; YAML specifies off | Reconcile before coordinated release activation |
| Group drift | Live service has no linked environment group; service-local variables | Templates reference openlearn-production; do not assume provisioned |
| Builds | Local vinext/Vite versus production Next.js/webpack | P04 adds production build/asset parity |
| CI | Previously desktop/release workflows only; now platform workflows added | Hosted environments/secrets remain unconfigured by this work |

## Request paths

Public production JavaScript contains the Render origin in compiled API configuration (chunk 2009-e82a55da1b79e4aa.js for the inspected deployment). apiBaseUrl prefers the desktop bridge, then a valid public origin, then fallback. This supports the default hosted-browser direct path; authenticated runtime network capture was not taken. Do not assert every request follows it.

The same-origin /v1/account proxy also exists: an unauthenticated GET returned 401 and proxy_upstream timing. Its existence does not prove normal browser usage. Direct path: browser -> Render Oregon -> PostgreSQL Virginia/provider/storage. Proxy path: browser -> Vercel iad1 -> Render Oregon -> PostgreSQL Virginia/provider/storage. Both cross regions on SQL work.

Identity resolution may first call /v1/account; API authentication and ownership checks then run. Browser/mode admission can precede generation submission. Durable acceptance, branch/context preparation, model call, replay-event persistence, and SSE follow. Generation and embedded background work currently share the API process.

Notes use owner-scoped workspace-note routes and revision checks. Local recovery, cloud save, list refresh, and tutor requests are distinct operations. Notes do not inherently require model inference. Existing material/object adapters handle uploads.

## Public probes

| Probe | HTTP | Total |
| --- | --- | --- |
| API /health | 200 | 2362.549 ms |
| API /ready | 200 | 2415.100 ms |
| API /release | 404 | 51.023 ms |
| Frontend /v1/account, unauthenticated | 401 | 1044.268 ms; proxy_upstream 160.6 ms |

Single samples include transit; they are not percentiles. Health/readiness call no model. The new metadata/timing endpoints are not live until deployment. These probes do not establish successful generation TTFT or a cause split. Reproduce with backend/scripts/deployment_audit.py; local output: outputs/performance/p01-public-deployment.json.

## Unresolved work

P05/P20 must verify pooler mode, SQL/pool/lock distributions, memory, provider headroom, and geographic traffic. The prior missing-schema PostgREST messages are not proven chat failures. Supabase dashboard request ratios are not application SLOs. Resolve quotas and backup capacity in P07/P21. Reconcile trigger/group drift when activating releases. Collect successful production chat/note traces after deploying instrumentation.
