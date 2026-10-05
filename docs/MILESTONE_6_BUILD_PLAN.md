# Milestone 6: connected actions and bounded delegation

Authorized 4 October 2026. Milestone 5 is owned by another agent; its responsibilities, notes and notification code are not part of this change.

Build against the existing Python agent runtime and owner/session boundaries. Add Google OAuth connections with encrypted server-side tokens and account/scope metadata. Google Drive reads/downloads enter existing material intake; Gmail reads are untrusted text. Gmail send and Calendar create/update are concrete, immutable action drafts with explicit per-action approval. A draft binds account, task/input revision, recipients/event details, attachments, expiry and content hash. Changes require new review. Unattended standing write grants remain disabled.

Persist operation state before dispatch. Calendar creation uses a stable provider event ID and updates use ETag preconditions. After ambiguous Gmail sends, reconcile by a stable Message-ID when authorized; lack of evidence leaves outcome_unknown and never triggers a blind resend. Revocation, expired approval, paused/cancelled tasks and changed input fence dispatch. API/OAuth scopes do not themselves authorize writes.

Bounded children use existing task IDs and workers, inherit owner/session/source policy, cannot create connector writes or further children, and reserve parent-shared limits before admission/provider work. Parent validates final artifacts and provenance before accepting results; child claims alone cannot mark the parent successful. Propagate cancellation and report budget exhaustion truthfully.

Expose connection/readiness, action-review and child-status controls in existing assistant UI. Record durable events and owner-safe recovery endpoints. Exclude tokens/permissions/runnable records from portable export/import, revoke dispatch on deletion, and retain minimal reconciliation receipts where necessary.

Verify using deterministic adapters and mocked official Google HTTP contracts: changed approval, cross-owner denial, revoked scope, duplicate decision, crash before/after dispatch, uncertain send without resend, Calendar reconciliation/ETag conflict, bounded child reservations/cancellation and output verification. Run affected API/UI/regression/migration checks and local browser flow. Live Google OAuth/provider acceptance and PostgreSQL concurrency remain explicit release gates unless actually exercised. No real emails or Calendar changes are sent during implementation testing.

Schema must reconcile the actual concurrent migration heads without deleting or rewriting another agent's migrations. Add compatible hooks to shared files only after inspecting their latest contents.

Primary API contracts: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send ; https://developers.google.com/workspace/calendar/api/guides/create-events ; https://developers.google.com/calendar/api/guides/version-resources .

Implementation outcome: local connected reads/intake, exact-action reviews, durable recovery and bounded children are implemented. See `docs/AGENT_CONNECTED_ACTIONS_IMPLEMENTATION.md` for contracts, integration paths, setup and release gates. Local browser acceptance completed with an offline provider fixture; live Google and PostgreSQL acceptance remain pending.
