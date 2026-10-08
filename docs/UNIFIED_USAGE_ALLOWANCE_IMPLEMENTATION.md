# Unified usage allowance: implementation specification

Date: 2026-10-05. This is the implementation specification and acceptance contract. The working tree contains the first implementation pass; it has not been deployed. Read alongside [the agent execution platform](../Open%20Learn%202.0/26_agent_execution_platform.md). This specification supersedes the earlier brainstorm of 20 messages per five hours and independent voice/browser allowances.

## 0. Implementation status and release gates

The current implementation has a five-hour account allowance, integer-credit reservations and settlement, idempotent operation keys, platform daily/monthly liability caps, versioned reference/provider rate records, overrun alerts and an operator-only reconciliation/unblock CLI. Expired reservations are reconciled by the hosted learning worker. Chat model calls default to `openrouter/free`; paid models fail closed unless explicitly enabled with an exact model allowlist, a pinned provider-rate version, conservative pre-call platform-liability reservations, and provider usage receipts. Claude Haiku 5.5 is the first reviewed paid model: `anthropic/claude-haiku-5.5`, using `OPENLEARN_HAIKU55_INPUT_USD_PER_MILLION`, `OPENLEARN_HAIKU55_OUTPUT_USD_PER_MILLION`, and `OPENLEARN_HAIKU55_CACHE_READ_USD_PER_MILLION`. The current OpenRouter listing is $0.10/M input, $0.50/M output, and $0.01/M cache-read tokens; verify the live listing before changing these values. The adapter rejects multimodal payloads until image and file cost bounds are independently reviewed. Search, embeddings, optional Jev classification, and uploaded-recording transcription require per-provider tariffs, a pinned provider-rate version and an active account reservation. The direct-to-provider realtime class-caption session is forcibly disabled until it has bounded server-visible duration and settlement. The web and mobile clients display the same allowance as a percentage and show task-grouped recent activity.

Hosted paid routes remain disabled by default. Haiku 5.5 admission is bounded by the 48,000-byte request limit, a four-times serialized-input token reservation, and the configured output-token maximum; it requests OpenRouter usage receipts and settles the actual reported provider cost, falling back to the pinned token tariff when cost is omitted. Calls without a terminal receipt retain the full liability hold as estimated spend. Enable paid chat only with explicit platform daily/monthly budgets and a new provider-rate version. Daytona currently remains unavailable even if credentials and per-unit rates are present: the installed adapter does not yet enforce provider-side CPU/RAM/disk allocation ceilings or settle delayed resource receipts, so a wall-clock TTL is not a safe spend bound. Browserbase is capped at one ten-minute session reservation and can only be settled after termination is confirmed; live provider TTL/termination behavior is still an external acceptance gate. Voice slice and utterance metering pass focused local tests, but live provider shutdown/reconnect and receipts remain release gates; STT and LiveKit slices conservatively settle their full 15-second estimate. Uploaded class-transcription adapters require account-specific rates and retain uncertain attempts as estimates.

Local migration and focused unit tests are necessary but do not satisfy PostgreSQL independent-process races, physical-device reconnect, backup-restore anti-replay, or live voice/browser receipts. Haiku chat is enabled as a narrowly allowlisted paid route only when its current rate, pinned provider-rate version, and platform budget are configured; the other paid capabilities and their acceptance gates remain unchanged. Record the approved tariff values and set a new `OPENLEARN_PROVIDER_RATE_VERSION` whenever any provider rate changes.

The first pass is not yet fully spec-complete. Agent-workspace task roots now store the learner-selected maximum in the task-creation transaction, enforce it across five-hour resets, and share it with delegated child work. Hitting the cap preserves a partial result and lets the learner continue in a new linked task with a new displayed maximum. Other durable roots receive a one-full-window hard ceiling, but the agent workspace is currently the only surface that lets learners choose a smaller task maximum. The owner-locked ledger now limits new metered roots to five admissions per rolling minute; it does not yet enforce a single active root uniformly across every task surface. The original `POST /v1/usage/estimate` remains a single-operation compatibility endpoint; the additive `POST /v1/usage/estimate/task` accepts explicit min/max bounds for up to 20 operations and returns a range, cap options and a ten-minute owner-scoped reference. `GET /v1/usage/estimate/task/{estimateReference}` retrieves that estimate. These calculations use internal reference-credit rates, mark provider cost uncertain, and do not reserve allowance or link acceptance; the exact agent task cap remains a separate atomic admission choice. The web composer does not yet call the task-estimate API, so it currently shows the selected maximum but not the estimated range. Global daily/monthly caps enforce admissions, and 50/80/95% crossings, reconciliation lag over 60 seconds, and outbox growth above 100,000 lifetime revisions are written to the restricted operator alert queue; they are not delivered to an external alerting destination. Uncertain cleanup costs do not yet have a separate contingency-accounting path. The replayable event outbox has no retention job or pruning policy yet, so it must remain unpruned until gap recovery and an approved retention period are implemented. These are build/release gaps, not reasons to relax the provider gates above.

Local verification on 2026-10-05: after the final admission limiter, the unified ledger suite passed 16 tests, agent execution/delegation passed 32 tests, the browser-assistant suite passed 24 tests, voice/class/lecture/retrieval/web-evidence suites passed 69 tests, and task estimates passed 5 tests. Allowance/admin/event-feed/mode-transition checks also passed together (38 tests) before the final rate-limit test was added. Migration `0077_usage_estimate_references` passed a disposable SQLite upgrade → downgrade → re-upgrade cycle. Web production build, targeted lint/tests, source typecheck and mobile typecheck/tests also passed. These checks are local evidence only; the PostgreSQL, live provider, device, restore/revocation and mixed-task production gates below remain open.

## 1. Product decision and economics

Give each verified free account **100 Learn credits per five-hour window**. One credit represents **$0.001 of normalized resource cost**. A full allowance therefore represents $0.10. Users see one shared **percentage of allowance used** for chat, voice, research, browser actions and sandbox work. Learn credits and microcredits are internal accounting units only; do not display a 100-credit or five-credit balance to learners. The full allowance remains equivalent to $0.10; this presentation decision changes no tariffs or financial limits. Credits are a free service allowance, have no cash value, and are not a bill or a wallet.

Do not impose an additional daily message or monthly credit quota in this first release: that would contradict the promised five-hour refill. Keep server-side concurrency, rate and platform spending limits. If a monthly user allowance is added later, disclose it as a separate product policy before launch.

The five hours describe the refresh interval, not permitted screen time or five hours of voice. Reading saved content, typing drafts, reviewing already-generated flashcards and replaying locally/cached audio use no inference credits. New generation, new synthesis and paid processing consume credits. Upload/storage limits remain separate resource constraints; no unbounded storage is implied.

100 credits is deliberately a modest beta allowance: enough for many economical text turns, but only a short voice trial. It is not a promise of a fixed number of minutes or messages. Voice can be substantially more expensive than text. Do not market unlimited voice or quietly increase voice subsidy.

At continuous use, 24/5 = 4.8 allowances/day averages $0.48/account/day and $14.40 per 30 days in normalized resource cost. In a particular 24-hour interval, five starts may occur ($0.50); a 30-day interval can contain 144 starts, or 145 when counting a window that began before it. For 1,000 users consuming one full allowance each day, the normalized monthly amount is $3,000. These figures exclude fixed hosting/subscription charges, taxes, storage, egress and exceptional cleanup cost. They are capacity planning examples, not forecast bills. Free-model reference pricing and safety multipliers normally make actual variable cost lower.

Launch as a controlled beta with platform cost ceilings: suggested variable-provider admission budgets **$10/day and $100/calendar month**, UTC. These are configuration defaults for staging/planning; production must explicitly set approved ceilings. A platform ceiling can temporarily suspend paid operations even when a user has credits, and the UI must explain this service-capacity condition honestly. Do not promise capacity to unlimited signups; admission/invite capacity must be matched to these budgets. Set provider-side caps where supported. This plan alone does not authorize purchasing a service or enabling paid routing.

## 2. One credit unit, two accounting ledgers

Maintain (a) learner credit usage and (b) actual/estimated provider liability. Never equate credit consumption with the provider invoice. Free routing, subscription inclusions, discounts and internal-error refunds produce different values.

Persist integer microcredits: 1 credit = 1,000,000 microcredits. Persist money as integer USD nanodollars, with explicit currency. No binary floating point. Aggregate quantities before rounding; round debit up once per metered operation, not once per token, audio packet or streaming event. Keep a cumulative total and apply only the delta, so reconnecting cannot change rounding.

For each component:

`normalized_usd = max(reference_quantity_cost, provider_liability_estimate_or_actual * 1.25)`

`microcredits = ceil(normalized_usd / 0.001 * 1_000_000)`

Reference rates below are **Open Learn policy**, not quoted provider prices. Pin an immutable rate-card version when reserving an operation. Include a conservative maximum liability in the reservation. If cost unexpectedly exceeds the held bound, record the full liability, block further work, alert, and absorb the excess rather than making a learner balance negative. A revised rate card applies to new operations; never silently reprice old history.

| Component | Reference rate | What is measured |
|---|---:|---|
| Uncached model input | 0.5 credits / 1,000 tokens | System, history, retrieved material, tool results and user input |
| Cached model input | 0.1 credits / 1,000 tokens | Only provider-confirmed cached tokens; otherwise use uncached |
| Model output | 2 credits / 1,000 tokens | All billable output, including reasoning if billed; never add reasoning twice when included in output totals |
| Speech recognition | 10 credits / input-audio minute | Audio actually submitted/billed, including billable silence |
| Speech synthesis | 60 credits / 1,000 characters | Provider-defined billable characters, not heard playback duration |
| Voice transport/runtime | 15 credits / connected minute | Base allocation for room/agent runtime; add actual component liability if higher |
| Cloud browser | 5 credits / browser minute | Allocated billable session duration, including takeover and idle time before close |
| Local companion browser | Zero browser-hosting credits | Model/search/other remote costs still apply |
| Search, fetch, proxy, sandbox and other paid tools | Actual conservative liability × 1.25, converted to credits | Exact provider unit and configured rate; missing rate disables paid operation |

For an integrated realtime speech model or bundled voice-agent API, use its audio/text tariff as a separate adapter. **Do not also charge STT/TTS components included in that bundle.** For browser services that bundle model execution, charge the bundle once, or its itemized costs once. Record purchased plan, inclusions and overage rules. Included units do not make learner reference usage zero; track their marginal cost and fixed subscription separately.

Use actual provider model IDs after routing, including multimodal/audio tokens, cached-input and cache-write tariffs, per-request fees, and provider-billed hidden reasoning. Unsupported billing dimensions must fail closed for paid routes. Character/4 estimates may support an explicitly labeled display, never a supposedly exact cost record or an unsafe upper bound. Reserve using a model tokenizer or documented conservative maximum, including image/audio bounds.

### Worked examples (illustrative reference rates)

* One text turn with 4,000 uncached input and 800 output tokens consumes 2 + 1.6 = **3.6 credits**. 100 credits permits roughly 27 such turns, before other work. Long conversation context changes this.
* Voice with one submitted audio minute, 450 synthesized characters, one connected minute and the same model turn uses 10 + 27 + 15 + 3.6 = **55.6 credits**. This would offer about 1.8 minutes from a full allowance at that activity mix. Actual tariffs can shorten it. Quiet time may still cost transport or STT. Display a range only after measuring the configured stack.
* A three-minute browser task with five such model calls consumes 15 + 18 = **33 credits**, before search/proxy fees. Browser runtime is only one part of browser-agent cost.
* A task starting in voice and delegating to a browser consumes all those components from the same balance. The parent summary aggregates child entries for display but must not create another debit.

Free OpenRouter calls consume reference credits even when provider liability is zero. Pin free-only routing until explicitly enabled otherwise. Provider free quotas are shared service capacity and can reject requests independently of learner credits.

## 3. Five-hour window semantics

Use fixed-duration, account-anchored windows, not a sliding sum of the preceding five hours. Window starts with the first successful reservation for billable work and expires exactly 18,000 seconds later. A rejected request, opening the app, fetching allowance or merely connecting without starting work must not start a window.

At expiry, the old period stays immutable and the next accepted operation opens a new period with 100 credits. GET allowance can report a virtual fresh allowance with `startsAt: null`, `resetsAt: null`, `windowState: ready`; it must not create a period. No rollover and no multiple refills for unused elapsed periods. Use database UTC time. Display absolute local reset time and a countdown derived from `serverTime`; daylight saving, device-clock edits and timezone changes cannot alter accounting.

Available = max(0, granted − settled − held). Settling an old reservation always updates its original period even after reset. A text request admitted just before reset may finish against its old reservation; newly admitted requests use the new period. Continuous voice/browser resource slices are split at the boundary, with a fresh reservation required before continuing. Old uncertain holds cannot consume new credits, but unresolved account liability or concurrency may block new paid work with a distinct reason. Return this reason instead of falsely showing exhausted new credits.

Suspended/revoked accounts cannot refill through restore or new devices. Database/account restore must not roll back the authoritative usage ledger. Account deletion must follow documented retention requirements for pseudonymous billing/security records; restoration cannot replay old grants. New signup abuse needs verified identity, signup throttling and risk review; per-account quotas alone do not solve multiple-account abuse.

## 4. Current architecture and integration work

These paths were inspected while writing this plan; the implementation agent must recheck HEAD and concurrent edits before changing them.

| Existing surface | Required integration |
|---|---|
| `backend/app/usage_service.py`, `usage_routes.py` | Preserve historical analytics; add unified allowance and event-backed accounting. Current completed-generation reporting misses some failed/cancelled/tool charges. |
| `backend/app/journey_service.py`, model provider implementations | Reserve all model calls, including teaching, quizzes, planning, context compaction, verification, embeddings and retries. Inventory the actual call sites rather than assuming JourneyService covers them all. |
| `backend/app/voice/routes.py`, `store.py` | Replace the independent daily `voice_usage` allowance as entitlement source; retain duration receipts and hard session ceilings. Existing start logic reserves session seconds. |
| `backend/app/voice/coordinator.py`, `speech.py` | Meter the direct OpenRouter planner and speech-review calls as well as domain-tool calls. Current TTS character counter is not a complete billing ledger. |
| `backend/app/voice/media.py`, `worker.py` | Wire room grants, worker leases, disconnect and cleanup to funded resource slices. Current configuration names LiveKit, Deepgram and ElevenLabs; do not silently migrate providers. |
| `backend/app/agent_execution/`, especially delegation, research, sandbox and responsibilities | All descendants and scheduled runs consume the owner's shared allowance; retain existing per-task limits as additional execution controls. |
| `backend/app/browser_assistant/`, especially cloud executor and reconciliation | Meter cloud lifetime, model actions, proxies and provider receipts, including takeover and orphan cleanup. |
| `web/components/usage-settings.tsx`, `usage-analytics.tsx` | Add percentage usage overview; preserve diagnostic tokens/cost as clearly labeled details. |
| `web/components/chat-composer.tsx`, `web/components/voice/voice-provider.tsx`, `voice-dock.tsx` | Shared allowance state, warnings, paused states and recoverable drafts. |
| `mobile/src/VoiceMessage.tsx` and native task/voice clients | Same server contracts, owner fencing, reconnect snapshots; no local authoritative counters. |
| `deploy/render.yaml`, hosted runtime and Supabase/PostgreSQL | Migrations, shared policy config, reconciliation/watchdog process and alerting. Vercel serves UI/proxy only. |

Create a reusable `backend/app/usage/` package (policy, pricing, ledger, admission, reconciliation, contracts), or an equivalently cohesive module layout consistent with the repo. Preserve existing route imports or provide migration shims. Avoid a second task coordinator or parallel identity system.

Before coding, produce a checked inventory of every outbound model/STT/TTS/search/browser/sandbox call, its owner, invocation path, provider billing dimensions, admission hook, settlement hook and test. Mark inaccessible provider receipts as estimates. No paid capability is production-ready with an unmetered call path.

## 5. Database and atomic admission

Add Alembic migrations using the repository's current migration head. Do not invent a migration number without checking concurrent work.

* `usage_accounts`: owner PK, plan, policy version, current period pointer, revision, status. One row is the serialization point for account admission.
* `usage_periods`: id, owner, starts_at, expires_at, granted/settled/held microcredits; checks for nonnegative balances and `settled + held <= granted`; unique owner/start. Immutable original grant, auditable adjustments as ledger events.
* `usage_reservations`: id, owner, period, operation/attempt IDs, request hash, component, parent/root task, rate version, held amount, maximum provider liability, state, lease generation, deadlines and provider request/resource IDs. Unique owner/operation/attempt/component.
* `usage_task_caps`: owner and durable root task, immutable accepted maximum in microcredits, policy version, creation time and the originating usage period. All descendants share the same root cap. A new root is required to continue after the originating five-hour period expires; a reset never restarts old interactive work.
* `usage_events`: append-only quantities, unit, component, model/provider, source exact/estimated/pending, credit delta, cost delta, occurrence/receipt times, event identity and correlation IDs. Unique provider event or internal attempt+sequence; explicit adjustment links. Do not store prompts/audio/credentials here.
* `usage_platform_periods`: UTC day/month, settled and held liability, configured cap; separate cleanup contingency budget. Fixed subscription accounting remains separate.
* `usage_rate_cards`: immutable version, effective date, reference tariffs, provider tariff and billing granularity, source URL/date, model allowlist, maximum supported cost, currency. Unknown or stale-unvalidated paid tariff disables that paid route.
* `usage_outbox`: usage updates, cleanup work and reconciliation jobs; reuse the existing outbox infrastructure if it provides equivalent transaction guarantees.

Reservation transaction: lock platform month, platform day, account, then usage period in that fixed order; create missing rows through unique insert/upsert before lock. Validate active principal, policy, concurrency and request idempotency. Obtain database time, create/reuse the period, check credits and platform liability with a conditional update, insert reservation and durable dispatch intent, commit. Never call a provider inside a DB transaction. Idempotent replay returns the same operation; mismatched body returns 409. Advisory locks must not serialize every user globally when row locks suffice.

Worker dispatch validates the reservation, cancellation and execution lease immediately before external work. Consume each dispatch authorization once and fence stale workers. If provider idempotency is absent and dispatch outcome is unknown, reconcile rather than blindly sending again. Settlement atomically inserts a deduplicated event, consumes held credits, releases excess and emits a usage revision. Owner and platform counters must settle together.

Unknown external outcome is a real liability: do not release a hold just because a lease expired. Reconcile provider receipts/resources; if still unknown after the configured deadline, conservatively settle the funded bound and label it estimated. Credit an operator-authorized correction later if needed. Provider charges caused by infrastructure faults remain on the platform ledger even if learner credits are refunded. No refund may restore more than that operation originally debited or refill the current period using an old-period refund.

SQLite may support deterministic local development; real independent-process PostgreSQL race tests are mandatory for release. Redis is optional for burst limits, never the sole balance store. If authoritative accounting is unavailable, reject new paid work and shut down resources when existing funded leases expire; keep reading saved content available.

## 6. Execution bounds and stopping rules

Suggested initial technical limits: one root AI task per free account; voice may host one active turn and its tools under that same root, not deadlock against itself. At most one cloud browser, one sandbox and two child workers under the root. Five user admissions/minute; internal calls have task limits. Default text input 12,000 tokens, output 2,000; default agent task 12 model/tool steps and two bounded read retries. Count all retry liabilities. Existing tighter limits win; expose setup constraints as availability, not exhausted credits.

Each costly task gets an initial estimate and an accepted maximum spend. Ordinary small text turns need no confirmation dialog. Tasks expected to consume over 20% of a full window allowance (20 internal credits under the initial policy) display a task estimate card before start; the user can accept the cap or narrow the request. A task cannot silently spend more than its accepted cap even after a window reset. Asking for more allowance is a persisted conversational question. Increasing the cap never bypasses external-action approval.

Voice: reserve the next 15 seconds of transport/STT using maximum configured rates, and reserve each bounded TTS segment and each LLM request before dispatch. A 30-second initial estimate is a display aid, not a full-session debit. Speech characters may be billed even when the listener interrupts: charge the produced/provider-billed amount, stop queued synthesis promptly, and do not charge cached replay twice. Never treat silence detection as proof that a connected provider stopped billing.

Browser: reserve 30-second runtime slices plus provider minimum billing quantum, and independently reserve the next action's model/tool cost. Set provider TTL before work. Takeover counts while the hosted browser remains allocated; show this before takeover. After 60 seconds waiting for user input, checkpoint and close where supported. If session state cannot safely be restored, explain that reopening may require login; do not fake a resumable state. Proxy traffic must be disabled for free beta unless bounded before dispatch with a provider/network byte cap. Post-hoc proxy reports alone cannot guarantee a cost cap.

Sandbox: reserve CPU, memory, disk and relevant egress by allocation and lifetime, not CPU activity alone. Enforce provider TTL/auto-stop and delete retained resources according to artifact policy. Include pause/stop storage liability where applicable. Public/local browsing has no cloud-runtime charge but still meters models and remote tools.

At exhausted allowance, stop before the next unfunded call, save the latest safe checkpoint, cancel queued child work and close resources. A funded in-flight model response may finish within its reserved maximum. Permit essential teardown and reconciliation under a separate bounded platform contingency even when learner credits are zero. Do not spend fresh allowance automatically on a foreground task at reset: show Resume. Scheduled responsibilities can run only under their existing consent and budget scope; skip/coalesce missed work, never catch up unboundedly.

Voice connections must actually disconnect/stop paid streams at the funded deadline; JWT expiry alone does not disconnect an existing participant. Use short room grants, server/agent watchdogs, independent reaper, provider-side duration/TTL controls and verified close receipts. Warn when estimated remaining voice time falls below 30 seconds, then show a saved-transcript/continue-by-text state if sufficient text allowance remains. Do not promise a spoken goodbye unless its synthesis is already funded.

Financial bounds have practical limits when a provider lacks hard termination or byte caps. Document the maximum exposure per concurrent resource (rate × shutdown delay + billing quantum), reserve that exposure, monitor orphans and disable that capability if a defensible bound cannot be established. Never describe application accounting alone as a guaranteed invoice cap.

## 7. API contracts and live updates

Extend existing authenticated `/v1/usage` routes:

* `GET /v1/usage/allowance`: owner inferred from principal; `policyVersion`, `rateVersion`, `windowId`, `windowState`, `serverTime`, `startsAt`, `resetsAt`, `grantedMicrocredits`, `usedMicrocredits`, `heldMicrocredits`, `availableMicrocredits`, `revision`, `availability` and reason code. Active reservations summarized without secrets. Use `Cache-Control: private, no-store`.
* `GET /v1/usage/events?afterRevision=R&limit=N`: owner-scoped, read-only replay from the transactional change log. Return stable opaque event IDs, strictly increasing owner revisions, kind and timestamp only; cap `limit` at 100. Clients persist `nextRevision`, deduplicate by event ID/revision, then fetch the authoritative allowance snapshot when they observe a newer revision. Repeated reads are safe. If a requested revision has fallen out of retained history, return `resnapshotRequired` and the current revision so the client can refresh its snapshot instead of skipping a gap. Do not expose the internal payload or acknowledge/delete events per client.
* `GET /v1/usage/activity?cursor=...`: paginated task-level credit totals with optional component expansion, timestamps, pending/estimated labels and adjustment receipts. Ownership checked in SQL.
* `POST /v1/usage/estimate`: the current first pass accepts one bounded component and its input metadata; it returns a model-operation maximum or an explicit unsupported result. Complete implementation still needs task-level estimate ranges/options, rate version and expiry. Estimates have no side effect or guaranteed capacity.
* Agent task admission accepts `acceptedUsageCapMicro` in the same request that creates the task, so task creation and cap persistence are atomic. The cap is a percentage of the full grant chosen in the Agent workspace, is checked against the policy grant, and is shared with delegated children. Other durable roots default to one full grant until each user-facing start surface supplies its own accepted cap. Clients cannot choose tariffs, owner, spent amount or grant.
* Existing event streams carry `usage.updated`, `usage.low`, `usage.exhausted`, `task.paused_for_allowance` and resource shutdown outcome, with monotonically increasing revision. Reuse existing event transport; do not create per-second polling from every client.

Use 429 + stable `usage_window_exhausted` and reset timestamp/Retry-After for learner exhaustion; 429 `usage_rate_limited` for burst limits; 409 `usage_operation_conflict` for conflicts; 503 `usage_capacity_unavailable`, `usage_accounting_unavailable` or `usage_provider_unavailable` for service conditions. Include safe user message and retryability. For a streaming response already started, send the corresponding terminal/paused event rather than trying to change HTTP status. Never treat quota errors as generic automatic retries.

On reconnect/login/app foreground, fetch a snapshot. Ignore older revisions; reset cache on account switch and fence late responses by owner/session generation. Poll only as fallback while work is active (e.g. 15 seconds); timer expiry triggers a fresh snapshot, never an optimistic refill authorizing work. Cancellation must remain available while quota is exhausted.

The current client contract is replayable polling, not server push: the outbox is the durable notification source and the allowance endpoint remains authoritative. Events contain no learner text, provider receipts or balance values. No retention job is enabled yet; preserve events until an approved retention window and gap-recovery policy are implemented, and monitor row growth. A future pruning change must keep the `resnapshotRequired` behavior and must never silently skip missing revisions.

## 8. UI/UX implementation

Use **Usage** or **AI allowance** in learner-facing copy, with one shared percentage meter across web/mobile. Default display: `Usage · 32% used` and `Refreshes in 2h 15m`; include the absolute local reset time in details. Help text: `Chat, voice and agent tasks share this allowance. Longer responses and tools use more.` Do not expose internal Learn credits, dollar conversion, or a five-credit scale in the main interface.

Calculate settled used percentage as `100 × usedMicrocredits / grantedMicrocredits`, held percentage as `100 × heldMicrocredits / grantedMicrocredits`, and available percentage from the authoritative available amount. Always use the current policy grant as denominator; do not hardcode 100 internal credits into client calculations. Clamp visual values to 0–100. Keep exact quantities in the API/ledger; percentages never authorize work and are never written back as accounting inputs.

Show whole percentages. For settled use strictly between 0 and 100%, display a rounded value capped at 99%; use `<1% used` when rounding would produce zero. Display `100% used` only when settled use has actually consumed the full allowance. Admission can still reject a task that cannot fit into the remaining fraction: explain `Not enough allowance for this task` and offer a smaller task or the reset time. A balance held by running work is not settled use: show a separately styled reserved segment and details such as `32% used · 10% reserved · 58% available`. If holds occupy all remaining allowance, show `Remaining allowance is reserved for ongoing work`, not `100% used`.

Refresh the meter after completed replies/settlement and on server usage events. During ongoing voice/browser work, coalesce visual updates to at most once every five seconds, while applying exact backend admission continuously. Important exhaustion, shutdown and reset events update immediately. Do not animate individual tokens or audio packets, intentionally delay accounting, or smooth away real large consumption. Preserve revision/owner fencing. At refresh show `0% used` only after an authoritative snapshot confirms the new/ready period; a ready period says `Your five-hour window starts when you use AI`.

Task estimates use percentage points of the **full window allowance**, not a percentage of the current remainder: `This may use 10–15% of your allowance`. Accepted caps similarly say `Maximum: 20% of your allowance`, and the backend retains the exact accepted microcredit cap even across reset or later policy changes. Task receipts show `Used 3.6% of this window's allowance`; one decimal is permitted in task-level details and estimates even though the primary meter uses whole percentages. For tasks spanning periods, show separate per-window entries rather than aggregating percentages across different grants.

Usage settings: a compact percentage summary card, refresh time, activity list grouped by user task, and expandable Text / Voice / Browser / Tools breakdown. Token and dollar diagnostics are secondary and labeled provider estimates/actual costs, not learner charges. Do not expose other users or global budget values. Empty-ready state says `0% used · Your five-hour window starts when you use AI`.

Chat: keep the new compact mobile composer. No permanent large quota banner. Show a quiet warning at 80% used and a clearer warning at 95% used, once per threshold/window. Trigger from exact settled percentage rather than rounded display; after reconnect show only the highest applicable warning. If reservations leave very little available, explain that ongoing work has reserved it rather than claiming it is spent. At exhausted allowance, keep the draft editable, disable only actions needing new credits, and show `Your allowance refreshes at 3:00 PM. Your work is saved.` Preserve attachment references and partial results. Avoid upgrade buttons until an actual paid plan exists.

Voice dock: before connection show approximate percentage range per minute for the configured stack and shared usage meter, not a guaranteed duration. During the call show percentage used and a subtle warning. Reconnecting resumes the same server session/usage history and must not mint allowance. The background app and network loss must trigger bounded server termination. A voice task that opens a browser displays both components in one task receipt.

Browser task card: estimated percentage range and maximum before launch; live used/reserved percentages; Stop; needs-input state; allowance-paused state with Resume after refresh. During takeover show `Hosted browser time uses your AI allowance`. Hide raw tokens/infrastructure details from the main flow. Distinguish successful task completion from cleanup failure; the latter should trigger operational handling, not silently drain learner balance indefinitely.

Accessibility: labeled meter with textual percentage used and reserved value, no color-only warnings, screen-reader announcement once per important threshold, keyboard/focus restoration for sheets, reduced-motion support and 44px targets. Test 320/390px mobile, desktop and keyboard-open layouts. Do not announce each tiny debit through an aria-live region.

Class capture UI is outside this work. Inventory any existing transcription/derivation routes and ensure they cannot bypass shared paid-work admission; preserve raw recordings when processing pauses. Local capture is not an inference charge. Retention/upload controls stay separate.

## 9. Deployment, rollout and monitoring

Supabase PostgreSQL stores authoritative balances. Render API and every learning/agent/browser/voice worker use the same policy/rate version and database. Vercel renders the UI and forwards authenticated requests; neither public environment variables nor client storage carry provider keys or trusted balances. Native mobile uses the identical contracts.

Configuration names: `OPENLEARN_USAGE_MODE=off|enforce`, `OPENLEARN_FREE_CREDITS_MICRO=100000000`, `OPENLEARN_USAGE_WINDOW_SECONDS=18000`, `OPENLEARN_USAGE_POLICY_VERSION`, `OPENLEARN_USAGE_RATE_VERSION`, `OPENLEARN_PLATFORM_DAILY_BUDGET_USD`, `OPENLEARN_PLATFORM_MONTHLY_BUDGET_USD`, and `OPENLEARN_USAGE_PAID_ROUTES_ENABLED=false`. A shadow mode is rejected until it has a separate non-blocking ledger path; never treat an enforcement ledger as observational. Validate positive limits and complete tariffs at startup. Off is never an acceptable paid public-production configuration. Do not silently fall back to unrestricted execution if config is missing.

Rollout: additive migration; deploy the ledger with paid routing still disabled and enforcement enabled for the free model route; compare its activity records against provider receipts and existing analytics; deploy frontend compatibility; prove live bounded cleanup in staging; enable a small beta cohort; only then consider paid economical model routes. Policy changes are audited and versioned, preserving existing periods/reservations. No client rollout can bypass an enforced backend.

Metrics: normalized credits and provider liability by capability/model; active users and exhausted windows; cost per active user; held/settled discrepancies; reconciliation age; refunds; duplicate events; quota rejection reasons; provider 429s; concurrency; voice/browser orphan age and cleanup failures. Alert at 50/80/95% global budget, any invalid negative ledger balance, missing cost dimension and sustained reconciliation lag. Log identifiers and quantities, not full prompts or audio.

A watchdog scans expired resource leases at least every 15 seconds; actual shutdown deadlines must be verified with provider controls. Reconciliation retries use bounded backoff. Delayed invoice reconciliation may take longer; retain uncertainty explicitly. Implement audited operator commands for inspect, reconcile, refund and disable capability, with restricted authentication and no arbitrary balance mutation endpoint for learners.

Rollback: disable new paid admissions first, drain/close resources, keep settlement and cleanup running. UI rollback must tolerate usage errors. Do not drop ledger tables or restore an earlier database snapshot as a quota rollback. Backup/restore acceptance must prove balances, grants, revocation state and already-dispatched work cannot be replayed.

## 10. Implementation sequence and acceptance

1. Inventory call paths, current voice agent process/plugins and provider billing contracts; establish rate-card fixtures and checked example arithmetic. Capture the exact dependency versions and billing granularity. Missing live rates are explicit configuration gates.
2. Add migrations, ledger, pricing and reservation/settlement APIs. Implement deterministic clock injection for tests and database time in production.
3. Integrate every model route and background job, then voice resource slices, browser/sandbox runtime and paid tools. Remove competing entitlement gates while retaining stricter resource ceilings. Map old records to historical analytics without retroactively consuming a new allowance.
4. Implement shared frontend allowance state, Usage view, composer, voice dock and agent cards; integrate native equivalents. Reuse current visual styles and compact composer.
5. Add watchdog/reconciliation, configuration validation, operator observability, deployment documentation and production gates.
6. Run below acceptance matrix, attach evidence and leave unverified live/device checks explicitly pending. Do not claim finished until all enabled capabilities pass.

Required tests:

* First accepted operation starts one window; denied requests and GET do not. At exact expiry one new period is created under race. UTC/daylight-saving/client-clock changes do not affect it. No accumulation or old-period refunds into a new grant.
* Two devices and two independent PostgreSQL worker processes compete for the last credit: at most one succeeds. Global cap and account cap reserve atomically. Deadlock retry is bounded and idempotent.
* Duplicate HTTP command, SSE reconnect, provider webhook, settlement, crash recovery and child completion each debit once. Body mismatch under the same idempotency key fails.
* Long output, reasoning/cached tokens, multimodal inputs, silent audio, TTS interruption, minimum provider billing increments and unknown costs produce the expected ledger values. Chunk size does not affect rounded totals. Exact zero cost is distinguishable from unknown cost.
* Text, voice and browser in one task reduce one balance. Bundled providers and parent aggregates do not double charge. Tool retry and context compaction are included.
* Crash before dispatch releases only proven-unused work; crash after dispatch preserves uncertain liability. Stale worker cannot dispatch again. A cleanup failure cannot be disguised as a settled resource.
* Exhaustion during voice, browser takeover, sandbox execution and agent delegation stops unfunded work, retains results, tears down resources and resumes only under correct consent. Reset does not silently resume an interactive task.
* Network loss, room-token expiry, app background and worker termination demonstrate bounded live provider shutdown. Measure actual orphan exposure; a mock close response is insufficient.
* Database unavailable: no new paid calls; existing slices terminate. Provider throttling is distinguished from learner exhaustion. Global cap may reject a funded user with a service-capacity message.
* Ownership, account switch, revoked account, export/restore and role-restricted operator actions cannot transfer/recreate allowance. Scheduled responsibilities obey account caps and avoid catch-up storms.
* Percentage conversion tests: arbitrary grant denominators, sub-1% use, 99.6% versus true exhaustion, exact 80/95% warning thresholds, held-only exhaustion, zero/invalid grant handling, cross-period task receipts, and no rounding-driven authorization. Missing or invalid grant data shows usage unavailable and never a fabricated full allowance. Verify coalesced updates do not delay backend enforcement or urgent events.
* UI empty/normal/held/low/exhausted/reset/pending-cost/provider-outage states; 320px/390px/desktop; keyboard, screen reader, mobile reconnect; saved notes/history and cancellation remain accessible.

Deliver code, migration upgrade/downgrade evidence on disposable databases, unit/integration tests, independent-process PostgreSQL tests, UI screenshots, one live text+voice+browser mixed-task receipt with a pre-approved small provider cap, reconciliation report, operational runbook and documented remaining gates. Passing local tests alone is not hosted financial enforcement proof.

## 11. Research sources and remaining provider decisions

Reviewed 2026-10-05. Official pages are evidence about billing dimensions; account contracts and current selected model tariffs must be checked at implementation/deployment. Promotional credits are not sustainable free-tier economics.

* [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting): obtain model usage/cost receipts rather than relying only on successful visible text.
* [OpenRouter limits](https://openrouter.ai/docs/api_reference/limits): provider free capacity and key limits are separate from our learner allowance.
* [Browserbase pricing](https://www.browserbase.com/pricing): Developer lists $20/month, 100 included browser hours and $0.12/hour after that; proxy traffic and other services have separate rates. Our 5-credit/minute reference is a policy buffer, not this published tariff.
* [Deepgram pricing](https://deepgram.com/pricing): STT, TTS and bundled voice-agent services have distinct billing units. Do not charge a bundled voice service plus the components already included in it.
* [ElevenLabs API pricing](https://elevenlabs.io/pricing/api): verify the chosen voice/model/plan rate and any multipliers. The current code requires ElevenLabs; this document does not replace it with Deepgram TTS.
* [LiveKit billing](https://docs.livekit.io/deploy/admin/billing/) and [pricing](https://livekit.com/pricing): account for the actual deployment's runtime, connection and inference components. A cloud-hosted agent tariff must not be charged as an actual fee when the agent runs on our Render worker.
* [Daytona billing](https://www.daytona.io/docs/billing): CPU, RAM and disk quantities and delayed billing require durable resource receipts and reconciliation.

Open questions are deployment inputs, not unspecified product behavior: actual provider plans/tariffs, supported hard resource shutdown bounds, approved global spend ceilings and beta cohort size. Until configured and verified, corresponding paid capabilities remain unavailable. The user-facing decision is fixed for this proposed release: one 100-credit allowance, refreshed every five hours, shared across supported AI capabilities.
