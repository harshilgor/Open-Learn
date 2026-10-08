# Browser academic assistant: implementation and operations

This implementation adds the architecture in `BROWSER_ASSISTANT_ARCHITECTURE.md` to the existing FastAPI application, shared database, durable job leases, React chats, and Chrome/Edge companion. It does not allocate a permanent machine per learner. Browser sessions consume compute only while active; academic memory and reminders remain in the database.

## Delivered user flow

1. Open **Settings → Connected websites**. Connect a Canvas institution or another HTTPS study website. Set the default university portal, and approve any document or sign-in origins explicitly.
2. For a local connection, download the companion from Settings, unzip it, load its folder as an unpacked extension in Chrome/Edge, and paste the pairing configuration into its popup. The configuration contains a revocable, scoped device credential. Canvas credentials remain in the browser.
3. In Ask/Learn chat, try: **“Go to Canvas, find my classes, save my midterm dates, and remind me two hours before.”** Ordinary teaching and quiz requests retain their existing workflow. A browser task has its own progress, source passages, coverage, pause, stop, and continuation controls.
4. Canvas imports student enrollments, maps courses, reads assignments and calendar events, and visits syllabi, announcements, modules, and relevant document links. Exact quotes support saved dates; date precision is preserved. Explicit legacy course mappings are reused when the student identity matches.
5. For another website, the model chooses bounded navigation, observation, text finding, link clicks, search-field interactions, scrolling, screenshots, and document reads. Permissions apply per connection, without a hardcoded institution allowlist. A public-page fetcher is available for simple HTML and PDFs; signed-in or interactive pages need the companion or configured cloud executor.
6. Saved facts are canonical academic entities and are also available to the existing tutoring context compiler. **“Show my saved upcoming exams”** reads memory without launching a browser. Reminder follow-ups can refer to the previous website task in the same conversation.
7. Enable academic notifications in Settings. Date-only facts require a chosen local reminder time. Conflicting dates and image-only transcriptions do not trigger precise alerts. Inbox delivery is durable; desktop alerts require the app to run. Hosted Web Push requires the configuration below.
8. Opt into daily refresh per connection, or stop it in Settings. Local refresh requires the app and browser to be available. Cloud refresh requires a verified, reusable sign-in context. External submissions, purchases, messages, and unrestricted writes remain outside this release. Explicit study-activity requests can create proposals through the existing academic planner; they do not fabricate topic scope or schedule activities without availability.

## Components

| Concern | Implementation |
| --- | --- |
| Strict browser, task, intent, evidence, and reminder contracts | `backend/app/browser_assistant/contracts.py` |
| Owner-scoped connections, pairing, cloud sign-in | `connections.py`, `routes.py`, existing identity middleware |
| Durable orchestration and recovery | `workers.py`, `service.py`, existing `WorkflowStore` leases |
| Model reasoning and bounded inputs | `intent.py`, existing provider transport with image support |
| Local browser execution | `canvas-extension/service-worker.js`, `observer.js`, `companion-policy.js` |
| Temporary cloud browser | `executors/cloud.py`, Browserbase REST, Playwright CDP |
| Simple public reads | `executors/public.py` |
| Canvas and PDF/image reading | `adapters/canvas.py`, packaged `canvas-read.js`, `adapters/documents.py` |
| Evidence validation and reconciliation | `evidence.py`, `reconciliation.py`, canonical `AcademicPlanningService` |
| Reminder outbox, inbox, desktop, Web Push | `reminders.py`, desktop main process, web notification service worker |
| Chat and settings UI | `useBrowserAssistant`, `BrowserTaskCard`, `SiteConnections`, `AcademicReminderSettings` |
| Additive persistence | migration `0041_browser_assistant`, following `0040_cloud_foundation_compat` |

The migration creates separate assistant aggregates, ordered events, fenced commands, expiring snapshots, provider leases, course links, coverage, reminder policies/deliveries, refresh schedules, and deletion queues. It preserves existing Canvas imports, course history, teaching decisions, and quiz behavior. Academic ingestion now schedules reminder rebuilding in the same transaction, including manual date corrections. Identical imports preserve the entity revision; a browser source revision supersedes its own prior value, while contradictory current sources remain conflicts and user overrides retain precedence.

## Runtime configuration

The assistant is enabled by default locally. Set `OPENLEARN_BROWSER_ASSISTANT_ENABLED=false` to disable task creation and embedded workers. Existing database startup applies additive migrations.

For local companion acceptance, set `OPENLEARN_BROWSER_DEFAULT_EXECUTOR=local`. This selects the companion for newly resolved website origins; existing connections retain their executor. Other accepted values are `cloud` and `public_fetch`. A local connection remains unpaired until the user approves its scoped pairing in the extension. See [the conversational audit](CONVERSATIONAL_AGENT_AUDIT.md) for current shared-chat integration and outstanding gates.

Development/desktop uses `OPENLEARN_WORKER_MODE=embedded`. Hosted deployments require the existing PostgreSQL and OIDC configuration and use `OPENLEARN_WORKER_MODE=external`.

Run external assistant workers from the repository root:

```powershell
python -m backend.app.browser_assistant.workers --role browser
python -m backend.app.browser_assistant.workers --role notifications
```

Alternatively, `--role all` (the default) runs both with separate notification dispatch so model calls do not delay due reminders. `--once` provides a bounded execution/maintenance pass. Scale worker processes with the existing database lease semantics. Current admission allows two running tasks per owner, one per connection, and at most twenty queued/running requests per owner; this is bounded admission, not a benchmarked throughput guarantee.

Tasks default to 80 actions, 40 visited URLs, ten minutes of active execution, and bounded model inputs. A 100,000-token reported-usage threshold and 100 model-round ceiling stop further reasoning. Provider usage is best-effort telemetry, not a billing ledger. Snapshot text and screenshots expire after 24 hours. Evidence quotes remain with academic observations. Cleanup removes expired images and scans for objects stranded by rolled-back writes. Configure a bucket lifecycle as an additional retention boundary for hosted storage.

The companion polls in the background, briefly polls faster during active command sequences, and persists receipts across popup/worker restarts. An uncertain interaction is not blindly replayed. Reconnect pauses with an actionable state; resume re-observes where required. Debugger access is released when idle or stopped. Browser interactions block non-read HTTP methods while debugger interception is active; arbitrary website semantics and anti-automation behavior still require domain testing.

## Cloud setup and release gates

Install the optional dependencies beside the normal backend requirements:

```powershell
python -m pip install -r backend/requirements.txt -r backend/requirements-browser.txt
```

A remote CDP executor does not need a local downloaded browser binary. Browser integration tests use an installed Chromium browser; on hosts without the fixture browser they skip explicitly.

Configure the server-side `BROWSERBASE_API_KEY`; Browserbase infers the project from the API key, so no project ID is required. Temporary read-only cloud execution remains unavailable until all of its gates pass:

- `OPENLEARN_CLOUD_BROWSER_ENABLED=true`
- Enforced usage policy, an approved `OPENLEARN_BROWSERBASE_USD_PER_MINUTE` tariff, and paid provider routes
- `OPENLEARN_BROWSER_EGRESS_VERIFIED=true`, after validating provider/network isolation and private-network blocking
- `OPENLEARN_BROWSER_LIFECYCLE_VERIFIED=true`, after validating session bounds, terminal-state reconciliation, and retryable cleanup
- A positive `OPENLEARN_BROWSERBASE_USD_PER_MINUTE` tariff, pinned in `OPENLEARN_PROVIDER_RATE_VERSION`, with enforced account and platform limits. The current Render template uses `$0.002` per billable minute (the published Developer overage rate of `$0.12` per browser hour converted to minutes); review it against the Browserbase account plan before changing it.

These flags attest to completed deployment checks; changing a flag is not the check itself. Browserbase sessions disable recording, logging, and CAPTCHA solving and have a ten-minute expiry. The published `allowedDomains` setting restricts top-level navigations only; Open Learn also intercepts browser requests and blocks non-public addresses, while the egress-verification gate remains closed until that full boundary has been accepted in the deployed runtime. The current cloud launch path is temporary and read-only: non-GET/HEAD/OPTIONS requests are blocked, and saved sign-in is not available. `OPENLEARN_BROWSER_PRIVATE_VERIFIED=true` is a separate, additional gate for persistent profiles and must follow two-account isolation, live-view expiry, shutdown, and deletion acceptance. “Remember sign-in” is explicit and off by default; opting in creates an owner-scoped context, and Open Learn deletes it after 30 days without use. Revocation and account erasure queue context/session deletion for retry during provider downtime.

For hosted image evidence, set `OPENLEARN_ASSISTANT_S3_BUCKET`; runtime IAM needs immutable put/get/delete and prefix-scoped list permissions. The assistant uses the `assistant/` prefix. Local evidence otherwise lives beside the database under `assistant-objects`, or at `OPENLEARN_ASSISTANT_OBJECTS_DIR`.

Configure Web Push with `OPENLEARN_VAPID_PUBLIC_KEY`, `OPENLEARN_VAPID_PRIVATE_KEY`, and `OPENLEARN_VAPID_SUBJECT`. The frontend gets only the public key. Subscription endpoints are limited to supported browser push services. Policy/entity revisions are rechecked before delivery, and a unique inbox row prevents duplicate internal notifications. An uncertain external send is recorded without blind retries; neither push acceptance nor desktop dispatch proves a user saw an alert. Deleting or disabling a policy suppresses stale deliveries. Opt into push through Settings on an HTTPS deployment.

Cloud adapter endpoints were checked against [Browserbase session creation](https://docs.browserbase.com/reference/api/create-a-session), [session release](https://docs.browserbase.com/reference/api/update-a-session), and [context deletion](https://docs.browserbase.com/reference/api/delete-a-context). Deployment credentials and real private sessions were not exercised here.

## Verification and remaining live boundaries

Verified in this workspace:

- 53 backend tests across the assistant, academic planning, identity/privacy, and context compiler: course discovery, saving versus summarize-only, request idempotency, command fencing, duplicate receipts, timeout and worker-crash recovery, ownership, event replay, reminder revision/deduplication, manual corrections, DST/date uncertainty, visual review, source supersession/conflict, refresh scheduling, credential redaction, account deletion, and existing regressions.
- Controlled real Chromium browser tests exercise the actual Playwright/CDP adapter against fixture pages: unfamiliar layout, links, lazy container scroll, text finding, screenshots, scoped controls, cleanup, and the packaged authenticated Canvas reader. Browserbase REST/session provisioning and university authentication are replaced by fixtures in this suite.
- Eight React tests cover existing tutor components and assistant results/controls. TypeScript, targeted lint, syntax/compile checks, and the application production build pass.

Run the backend contract/regression suite with:

```powershell
python -m pytest backend/tests/test_browser_assistant.py backend/tests/test_academic_planning.py backend/tests/test_local_identity_boundary.py backend/tests/test_context_engine.py -q
```

Run controlled browser tests after installing the optional runtime:

```powershell
python -m pytest backend/tests/test_browser_assistant_browser.py -q
```

From `web`, run `node node_modules/vitest/vitest.mjs run tests/tutor-components.test.tsx tests/browser-assistant.test.tsx`, `node node_modules/typescript/bin/tsc --noEmit`, and `node scripts/run-framework.mjs build`.

Still requiring deployment/live verification: Browserbase tenant isolation and credential lifecycle, real Canvas/SSO accounts, the installed extension’s complete browser-to-hosted-API flow, PostgreSQL concurrent workers, notification arrival while the desktop is closed, managed-browser extension restrictions, a real second LMS, and arbitrary-domain success/accuracy/cost benchmarks. Cross-origin embedded content, CAPTCHA challenges, unusual file types, and layouts that cannot be read through the supported tools return partial results or require user action. Recurring calendar occurrences can be imported as supplied by the source; free-form recurrence text is retained without inventing future occurrences.

This is an integrated implementation with tested local components and controlled browser execution. It is not a claim that the brief’s production release gates or every website are already verified. Keep cloud/private release gated until the listed checks pass.
