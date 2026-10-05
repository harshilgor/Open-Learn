# Milestone 6: connected actions and bounded delegation

Implemented locally on 4 October 2026 against `Open Learn 2.0/26_agent_execution_platform.md`, slice 6. Planning is recorded in `docs/MILESTONE_6_BUILD_PLAN.md`. This is an additive extension of the existing Python agent coordinator, database, worker, research service, material intake and assistant UI. Milestone 5 responsibilities remain separate.

## Features and flow

- Google connections: authenticated authorization initiation requests explicitly selected capabilities. Owner-bound, hashed, single-use OAuth state and PKCE expire after ten minutes. Server-side Fernet encryption protects verifier and provider tokens. The callback exchanges the code, verifies account identity and records actual granted scopes. Token refresh checks connection revision before saving. The UI identifies the account and capabilities; credentials never enter model input or public connection responses.
- Sources: Drive and Gmail reads are bounded pages of 20 with coverage and continuation metadata, classified as untrusted source content. Drive PDF, plain text and Markdown downloads are bounded to 5 MB and enter existing material intake with connection/file/content-hash provenance. Stable import identities reuse the material; changed content requires a new identity. Gmail detail reads return source data, not instructions. The current UI offers one-page inspection and file-ID import; richer source browsing remains a UI enhancement.
- Reviewed writes: prepare an immutable Gmail-send or Calendar-create/update draft. Review contains account, recipients, subject/body or event fields, attachments, expiry, canonical hash and task/input revision. Calendar updates include the original provider event and ETag. Attachments must be current, owned artifacts from the same task; bytes are hashed and revalidated before dispatch. The UI defaults to no Calendar attendees or notifications. Explicit approval queues one durable operation; rejection queues none. Stable decision keys replay the same receipt and reject conflicting bodies.
- Recovery: persist a dispatch marker before the provider call. Queued work checks approval expiry, account revision, owner, task/input revision, feature flag and cancellation/pausing. Calendar creation uses a stable event ID; updates use `If-Match`. Ambiguous writes become `outcome_unknown`. A crash after dispatch reconciles provider evidence rather than repeating the write. Gmail reconciliation requires an authorized read scope and matching Message-ID/action hash in Sent; Calendar reconciliation requires matching private operation/action markers. Missing evidence remains unknown. The UI offers a provider-outcome check and never automatically resends. Success means provider API acceptance or matching provider evidence, not confirmed email delivery.
- Standing authorization: typed recipient/calendar/expiry/action-count constraints can be stored only with `disabled` status. Neither OAuth consent nor these structures grants unattended writes. Every supported external write still requires its exact per-action approval.
- Delegation: explicit child requests reuse ordinary task records and workers. Research parents can admit research children; lab/sandbox parents can admit deterministic lab-analysis children. Children inherit owner, session, input material, CSV, constraints and source policy, cannot recursively delegate, and cannot create connector writes. A parent-input revision gets at most two children and a prospective shared budget of 24 provider calls / 50,000 conservative token units; each child is bounded to 12 calls / 25,000 units. Fresh provider attempts charge before work; cached receipts do not charge again. These limits cover future research work after the delegation budget is established, not past historical spend. Token units conservatively use UTF-8 prompt bytes plus bounded output allowance; they are not billing dollars or provider-reported usage.
- Child verification checks terminal state, owner, task/input revision, readable source lineage and immutable output hashes. Receipts identify accepted, accepted-partial or rejected outputs. Research semantic support is explicitly not independently verified; deterministic lab outputs use the existing analysis engine. A child cannot complete its parent or mark learning delivery successful. Inactive or changed parents fence child work; pausing a parent cancels the child rather than preserving a resumable child job.

## Integration map

| Area | Source |
| --- | --- |
| Strict request contracts | `backend/app/agent_execution/connected_contracts.py` |
| OAuth, token vault and Google HTTP adapter | `backend/app/agent_execution/google_connector.py` |
| Approval, dispatch and reconciliation service | `backend/app/agent_execution/connected_actions.py` |
| Drive intake receipts | `backend/app/agent_execution/connector_intake.py` |
| Child admission, shared charges and verification | `backend/app/agent_execution/delegation.py` |
| Authenticated APIs and state-protected OAuth callback | `backend/app/agent_execution/connected_routes.py` |
| Assistant review and child controls | `web/components/assistant/connected-task-panel.tsx` |
| Persistence | `backend/migrations/versions/0047_agent_connected_actions.py` |
| Backend/UI regression tests | `backend/tests/test_agent_connected_actions.py`, `web/tests/agent-connected-actions.test.tsx` |
| Isolated browser fixture | `backend/scripts/agent_connected_preview.py` |

`main.py` registers routes. Existing `worker.py` advances action and child recovery; `research.py` reserves shared call/token units before fresh provider work. `coordinator.py` blocks child follow-up paths that could escape the bound. Existing artifacts enforce ownership, hash and source-access checks. Material creation optionally shares the intake transaction so material identity and connector receipt commit together. Identity export treats credentials, approvals and standing grants as private; restore excludes connections and runnable action/delegation state. These owner-scoped tables also participate in existing account erasure. Account erasure can remove reconciliation metadata, so the product must not promise that deleting an account undoes a provider effect already in flight.

The migration merges `0046_agent_responsibilities` and `0046_buddy_navigation` without rewriting either branch. A disposable SQLite database passed upgrade to 0047, explicit downgrade to `0046_agent_responsibilities` (restoring both prior heads), and re-upgrade to the current head. Relative `-1` is ambiguous across this merge; use explicit revisions. Later concurrent migrations remain intact.

## API contracts

Authenticated routes use existing owner/session middleware. Stable `Idempotency-Key` is required for draft creation, approval decisions, child admission and Drive intake.

| Method and route | Behavior |
| --- | --- |
| GET `/v1/assistant/app-connections` | Safe account metadata and enabled/readiness flags |
| POST `/v1/assistant/app-connections/google/authorize` | Explicit capabilities, authorization URL |
| DELETE `/v1/assistant/app-connections/{id}` | Disable local connection, erase tokens, invalidate pending approvals |
| GET `/v1/assistant/app-connections/{id}/sources` | `kind=drive|gmail`, optional source ID / page token |
| POST `/v1/assistant/app-connections/{id}/drive/{sourceId}/import` | Existing material identity and provenance |
| GET/POST `/v1/assistant/tasks/{taskId}/actions` | Recover reviews / prepare exact draft |
| POST `/v1/assistant/approvals/{id}/decision` | Approve or reject matching revision and hash |
| POST `/v1/assistant/approvals/{id}/reconcile` | Read-only provider evidence check for unknown outcome |
| GET/POST `/v1/assistant/tasks/{taskId}/children` | Child receipts, budgets / bounded admission |
| POST `/v1/assistant/standing-authorizations` | Store constrained, disabled proposal |

`GET /oauth/google/callback` intentionally sits outside `/v1`, protected by single-use owner-bound OAuth state instead of weakening `/v1` identity requirements. Callback query values are redacted from the Uvicorn access logger; production ingress/proxy logging must also redact them. Disconnect currently revokes Open Learn's local access, not the Google-side grant: users can separately remove the grant in their Google account.

## Setup and remaining release gates

Install `backend/requirements-connectors.txt` in the backend environment. Existing requirements supply HTTP and identity dependencies. In the server environment configure:

```dotenv
OPENLEARN_CONNECTORS_ENABLED=false
OPENLEARN_DELEGATION_ENABLED=false
OPENLEARN_GOOGLE_CLIENT_ID=
OPENLEARN_GOOGLE_CLIENT_SECRET=
OPENLEARN_GOOGLE_REDIRECT_URI=https://YOUR_API_HOST/oauth/google/callback
OPENLEARN_CONNECTOR_VAULT_KEY=
```

Generate a Fernet key securely outside version control and retain it in the secret manager; losing or rotating it without a migration makes existing encrypted tokens unreadable. Register the exact redirect URI in a Google OAuth web client and enable Drive, Gmail and Calendar APIs. Production redirects require HTTPS. Enable flags only after setup and acceptance; hosted mode rejects test adapters. Keep the existing worker running to process queued actions and recover stale dispatch markers. Turning connectors off stops new queued dispatch but still permits uncertain-outcome reconciliation reads.

Local verification uses mock HTTP/provider adapters and durable SQLite persistence. Browser acceptance used an isolated database and conspicuously labeled offline account: approved a message with an attachment, completed/verified a child task, simulated provider effect plus timeout, reconciled without a second send, and reloaded durable receipts. No real Google messages or Calendar changes were made. Screenshot: `work/agent-connected-browser.png`.

Final verification: 81 backend tests passed across connected actions, foundation, research, sandbox/learning and responsibilities; the subsequently added child-output integrity rejection test passed separately (82 total checks). Four frontend suites passed all 14 tests. TypeScript and targeted ESLint passed. The production web build passed before the final account-reset cleanup; that cleanup passed frontend tests and TypeScript. SQLite migration upgrade/downgrade/re-upgrade, Python compilation and scoped `git diff --check` passed. Existing SQLite datetime deprecation warnings remain. The sandbox regression initially failed because this environment lacked the declared Daytona SDK; installing `backend/requirements-daytona.txt` restored the pinned SDK and the complete rerun passed. Pip also reported unrelated existing scientific-package dependency conflicts. Temporary preview servers and the acceptance browser tab were stopped. No commit, push or deployment was performed.

Live Google OAuth/scope verification and controlled Gmail/Calendar acceptance remain unperformed. PostgreSQL concurrent approval/budget/revocation races, production secret/ingress setup, provider permission verification, operational monitoring and a priced monetary budget policy remain release gates. Full autonomous tool selection and unattended writes are not enabled by this milestone: the existing UI/API requests concrete drafts and bounded children explicitly. Sandbox/browser children and arbitrary external actions are outside this supported slice.

Google contracts used: [Gmail send](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send), [Calendar event creation](https://developers.google.com/calendar/api/guides/create-events), [Calendar version preconditions](https://developers.google.com/calendar/api/guides/version-resources).
