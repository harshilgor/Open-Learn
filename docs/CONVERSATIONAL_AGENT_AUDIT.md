# Conversational agent implementation audit

Updated 2026-10-07. This is a code audit, not a declaration that every platform milestone has shipped.

## Product contract

Buddies are the conversational entry point to general-purpose tasks. “Open YouTube”, “check my Canvas”, and requests involving other websites enter the same admission boundary. Canvas is one platform adapter; it is not the boundary of agent capability. Conversation and Ask change presentation, not available authority. Page text and attachments are data, not instructions granting tools or external-write permissions.

The authoritative execution design is [agent execution platform](../Open%20Learn%202.0/26_agent_execution_platform.md). Its existing-browser ownership requirement remains in force: browser_legacy owns browser runs; agent_v2 owns the research/analysis/flashcard runs. Admission must not create a second worker for an existing browser task.

## Documents reviewed

- `Open Learn 2.0/26_agent_execution_platform.md`: message admission, decisions, dependencies, authorization, memory, release gates.
- `Open Learn 2.0/AGENT_DECISION_WORKSHOP.md`: historical design proposals, superseded where the execution platform defines a current contract.
- `docs/BUDDY_BEHAVIOR_AND_RECOVERY_CONTRACT.md`, `BUDDY_IMPLEMENTATION.md`, `CURRENT_ARCHITECTURE.md`: mode behavior, memory, recovery, current domains.
- `docs/BROWSER_ASSISTANT_ARCHITECTURE.md`, `BROWSER_ASSISTANT_IMPLEMENTATION.md`, `AGENT_BROWSER_MILESTONE4.md`: general browser tools, website connections, companion dispatch, recovery.
- `docs/AGENT_EXECUTION_FOUNDATION.md`, `AGENT_PLATFORM_REMAINING_WORK.md`, research, Daytona, responsibility and connected-action milestone records: delivered execution domains and outstanding acceptance gates.
- Flashcard architecture and gap audit; In-Class architecture, implementation and next implementation plan; mobile milestone and loading records; reminders, settings, voice and workspace behavior records.

Older milestone completion notes are not evidence of current live acceptance. This audit distinguishes code paths, automated checks, and live tests.

## Changes implemented in this pass

| Behavior | Implementation | Verification |
| --- | --- | --- |
| Chat submits all requests through one admission endpoint | `/v1/assistant/messages`, shared client admission in both chat surfaces | Backend admission and frontend chat regressions |
| Explicit website requests cannot be vetoed into a tutor answer | Versioned admission plan; browser legacy handoff within the admission transaction | YouTube, Canvas, arbitrary domains and unknown aliases |
| Unknown institution destinations are not guessed | Alias resolution rejects ambiguity and unrelated preferred connections | Routing and owner-scope checks |
| New website connections can choose the local companion first | `OPENLEARN_BROWSER_DEFAULT_EXECUTOR=local`; existing connections retain their executor | Local/unpaired selection and replay tests; actual extension pairing pending |
| Uploaded inputs are available before admission | Owned, session-attached version references; CSV upload permitted | Client attachment envelope and server scope validation |
| Natural research and supported CSV analysis start existing runs | Existing research/lab executor ownership and capability gates | Queue admission; missing CSV requests input rather than sample-data execution |
| Flashcards use current lesson/material sources | Existing flashcard request and source resolver | Source revisions retained; source-free requests retain library flow |
| Reminders use the shared route | Existing reminder command service with stable message key | Reminder regressions |
| Explicit preferences can be saved conversationally | Revisioned source memory and deterministic derived preference | Replay, credential rejection and execution-memory scope checks |
| Bare task controls use the active execution owner | Single-task routing; ambiguity requests clarification | Agent control regression; browser commands retain existing domain path |
| New activity appears without waiting for polling | Browser/agent activity change events | Frontend regression suites |

Admission keys survive an uncertain network acknowledgment. Changing a pending request does not silently reuse its identity. Credential-like preference requests are rejected before admission payload persistence. Execution and coordination memory retrieval does not automatically include unrelated conversation text.

## Remaining implementation work

These are still required by the architecture and must not be represented as shipped:

1. A general bounded model-decision kernel and typed cross-capability registry. Current conversational selection handles explicit patterns; it is not arbitrary task understanding or an unrestricted agent loop.
2. Durable general input requests and natural reply binding, with task/request revisions, attachment bindings, ambiguity handling, and dependency wakeups across domains.
3. Natural-language preparation of connected actions and responsibilities. Admission currently guides the user to their existing configuration/review surfaces; it does not construct every proposed action or monitoring spec.
4. General analysis and verified output production beyond the existing constrained CSV/lab capability, including declared PDF/chart/spreadsheet output types.
5. Cross-capability continuations, operational memory/compaction, and skill/subagent contracts beyond the currently delivered bounded domains.
6. Browser recovery when a dispatched operation has an unknown outcome after a crash; generalized outbox/reconciliation for domain effects. Existing domain idempotency is not a general durable orchestration solution.
7. Retention, usage/operations, hosted and mobile acceptance gates identified in the platform release checklist.

## Local companion acceptance

The selected interactive executor is the paired local companion. Local `.env` now selects it for new origins. A new local connection starts unpaired; no task may use a browser device without its scoped grant and website permission. The extension opens a separate task tab and uses the browser's existing login without copying cookies to the backend.

The companion must be loaded from `canvas-extension` or the Settings download, then paired through Website connections. Browser automation in this development session blocks `chrome://extensions/`; extension installation and its permission gesture require the user's browser action. No workaround is permitted. Live YouTube/Canvas tab dispatch remains unverified until pairing is complete. The currently deployed website has not been updated by these local changes.

Local acceptance should verify: explicit open request → admission receipt → waiting-for-pairing or bounded dispatch → task-owned tab → authorized observation → sourced result. Then verify cancellation, reconnect, ambiguous destination, revoked pairing, and no access to unrelated tabs.
