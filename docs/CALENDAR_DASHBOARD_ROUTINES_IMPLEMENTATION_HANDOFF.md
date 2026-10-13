# Calendar, Dashboard, Routines, and Buddy: implementation handoff

Date: 2026-10-09. Status: implementation specification, not shipped functionality.
Repository: Open Learn. Paths below are repository-relative.

## 1. Agreed product scope

Build Calendar as a dedicated desktop sidebar destination and an entry in the existing mobile menu. Dashboard shows Today using the same event data. Routines belong inside Calendar and Dashboard, without another sidebar destination. Keep reminders and delivery history accessible.

Complete scope:
- Manual events, academic schedule projections, assignments/exams, study blocks, reminders, and recurring study routines.
- Day, Week, Month, and Agenda views; desktop defaults to Week, mobile to Agenda.
- Create/edit/cancel, course links, recurrence exceptions, timezones, availability, and clear save/sync states.
- Dashboard redesign around Today, upcoming deadlines, compact review, recent learning, and routines.
- Buddy calendar reading, proposals, confirmed changes, saved calendar-scoped edit permission, receipts, and conditional undo.
- Google Calendar synchronization and authorized changes through existing connectors.
- Durable scheduling, ownership/privacy, usage accounting, migrations, tests, and verified deployment.

Build in the milestone order below. A mock calendar is not completion. Manual calendar use must not require AI. Do not expand scope into class recording, Outlook, a new paid calendar service, or generic unattended external writes. Google is a later milestone but required for this entire handoff to be complete.

## 2. Verified implementation baseline

Inspect these current files before coding. Preserve other agents' and the user's working-tree changes.

| Existing files | Integration and verified behavior |
|---|---|
| `web/components/learning-workspace.tsx` | Workspace views, course context, navigation callbacks, Dashboard and panel visibility. |
| `web/components/workspace-rail.tsx`, `mobile-header.tsx` | Desktop rail and mobile menu. Add Calendar with selected state and accessible label. |
| `web/components/study-dashboard.tsx`, `study-dashboard.module.css` | Review, courses, reminders and Coming up. Replace schedule rendering and rebalance layout. |
| `web/components/course-index.tsx`, `course-index.module.css` | Current local Courses styling; reuse theme, typography, spacing and surfaces. |
| `web/components/buddy-today.tsx` | Reads `/v1/buddies/today`; small independent event contract to replace or adapt. |
| `backend/app/buddy_service.py`, `buddy_routes.py` | Today projects `academic_entities` start/due/date facts; filters cancelled/completed facts and archived courses. Not a calendar database. |
| `backend/app/academic_planning.py`, `academic_routes.py`, `course_service.py` | Academic source facts and owned course/study planning integration. |
| `web/components/routine-controls.tsx`, `buddy-reminders.tsx`, `reminder-sidebar.tsx` | Existing reminder and routine controls; consolidate rather than duplicate management. |
| `backend/app/reminder_service.py`, `reminder_routes.py`, `reminder_schedule.py` | Owner-scoped reminders, cron/RRULE, routine policies, revision-checked edit/pause/resume/delete and idempotent admission. |
| `backend/app/reminder_actions.py`, `reminder_worker.py`, `reminder_cron.py` | Durable action/delivery pipeline; extend it, do not create another scheduler. |
| `docs/reminders.md` | Existing infrastructure, environment names, notification semantics and live acceptance work. |
| `backend/app/agent_execution/calendar_tasks.py` | Bounded Google Calendar reads and provenance. |
| `backend/app/agent_execution/google_connector.py` | OAuth/token handling, event reads, create/update and ETag protection. |
| `backend/app/agent_execution/connected_actions.py`, `connected_contracts.py`, `connected_routes.py` | Exact drafts, hashes, revision checks, decision idempotency, receipts and unknown-outcome reconciliation. Standing grants currently return disabled. |
| `web/components/assistant/connected-task-panel.tsx` | Current UI requires every write to be reviewed and says unattended grants are disabled. Update only alongside real calendar permission enforcement. |
| `web/components/ui/calendar.tsx`, `web/package.json` | Date picker plus installed date-fns, react-day-picker, Motion and Radix primitives. Date picker is not a full scheduler. |
| `deploy/render-paid.yaml` | API migration command, notification worker and backup cron; auto-deploy is not universally enabled. |

Architecture: React/Next-compatible frontend, Python backend, shared database and durable jobs. Vercel serves production frontend; Render runs backend/runtime services. Confirm current configuration when implementing. No browser-owned scheduler or second frontend database.

Extend existing tests including `backend/tests/test_chat_reminders.py`, `backend/tests/test_agent_connected_actions.py`, `web/tests/study-dashboard.test.tsx`, and `web/tests/agent-connected-actions.test.tsx`. Inspect migration head and choose new IDs; do not assume a migration number.

## 3. Dashboard UX

Use existing theme variables, approximately 1080px content width, muted borders, restrained accents, and 16–24px spacing. Reduce the current oversized review/reminder panels.

Desktop order:
1. Date and short heading; Add event and Open calendar actions.
2. Today agenda (about two thirds width) beside compact review/next-study panel.
3. Deadlines over the next seven local dates, plus a distinct overdue group.
4. Continue learning: a few recent courses/conversations, not the full course library.
5. Your routines: active/paused state, next occurrence, Start/Pause and Manage routines.

Agenda rows show time or All day, title, course, type, and external source when applicable. Ongoing events appear before future ones. Countdowns derive from real timestamps. Date-only deadlines remain date-only. Review failures are not rendered as zero due. On mobile stack sections with Today first, preserving the existing menu instead of reintroducing bottom navigation.

## 4. Calendar UX and interaction

Desktop header: month/year, Today, previous/next, Day/Week/Month/Agenda, Add event and Routines. Collapsible filters: calendars, courses, event types, Show completed. Show display timezone. Filters persist per account.

Week has seven local-date columns, time gutter, all-day/deadline strip, current-time marker on today, and initial scroll near the current time. Overlaps render side by side. Month has bounded visible events and +N more to open a day's agenda. Agenda groups events by date. Tiny grid events have an accessible agenda alternative.

Select an event to open details on desktop; do not keep a third panel permanently open. Show title/type, dates/timezone, recurrence, course, source, location/link, description, reminders, editability, save/sync state and study actions. Closing returns focus to the trigger. Hide the unrelated notes workspace panel for Calendar.

Mobile defaults to Agenda with a compact month heading and horizontal week strip. Month allows date navigation; Day is an optional timeline. Details/editing use a bottom sheet or full-screen sheet on small devices. Target 44px touch controls and no horizontal overflow at 320px. Save/Cancel remain reachable with the keyboard open. Drag gestures are optional, never required.

Stable course colors reinforce labels/icons; color is not the sole indicator. Busy-only events are neutral and reveal no private title. Repeating events have a repeat icon. Reuse theme tokens and existing controls. Use short Motion transitions (roughly 120–180ms), with reduced-motion support and no looping decoration.

Implement grid presentation with CSS Grid and pure tested layout helpers; reuse installed date utilities/picker and Radix primitives. Do not silently introduce a commercial scheduler. If a library is selected instead, verify current licensing, React support, timezone semantics and accessibility before adoption.

### Event form

Fields: title, type, calendar, optional course, timed/all-day/deadline mode, dates, start/end, timezone, recurrence, location/URL, description, reminders and optional linked study activity. Study block duration defaults visibly to 30 minutes and is editable. Never assign an invented time to a date-only deadline.

Manual Save is authorization; it does not require another Buddy approval. Selecting a grid slot prepopulates the form. Move/resize uses the same revision-checked endpoint with rollback on failure. Recurring edits ask This occurrence / This and future occurrences / Entire series. Explain disabled provider actions.

Support skeletons, genuinely empty days, no filter matches with Clear filters, failed loads with Retry, stale data with refreshed time, revoked access, offline read-only state and unsaved-form recovery. Failed schedule loading must never appear as an empty day.

### Student actions

- Class: open course/materials/location or meeting link; Prepare with Buddy.
- Assignment: instructions, due date, linked materials; Plan study time.
- Exam: covered topics; Build revision plan.
- Study block: linked lesson/review/quiz; Start studying.

All linked resources are ownership-checked. A deadline and the time allocated to work on it are separate records. Do not infer completed study from elapsed calendar time.

## 5. Unified source-of-truth rules

Calendar, Dashboard and Buddy consume one normalized occurrence service. Sources remain authoritative:
- New local events belong to the calendar store.
- Academic events project accepted `academic_entities` facts with provenance. Conflicting/unknown dates go to Needs scheduling, not guessed slots.
- Routine recurrence/actions remain in existing `reminder_policies`; calendar series link to one policy and do not hold a second independently editable schedule.
- One-time reminders project existing reminder records and are non-blocking by default.
- Google is authoritative for its events; local records are mirrors.

Event types: class, assignment, exam, study, reminder, personal. Source, recurrence, completion and busy/free are separate dimensions. Deduplicate with source identity and original occurrence key, never fuzzy title/time. Explicit mirror/export links prevent duplicate display. Moved occurrences retain their original identity.

Academic projections are read-only in the initial release. Link to existing source/course correction flows; Buddy cannot overwrite an imported exam date through the projection. Accepted source corrections refresh the feed and existing academic reminders. Buddy may create a separate linked study block.

## 6. Proposed schema and temporal contracts

Use existing SQLAlchemy/store/identity/migration conventions. Reconcile proposed tables with existing infrastructure before adding them. Every record and reference is owner-scoped, with account-deletion checks.

| Entity | Required fields and purpose |
|---|---|
| calendar_calendars | id, owner, local/google source, connection/provider calendar IDs, title, color, timezone, provider role, enabled/visible state, revision; idempotent default local calendar per owner. |
| calendar_events | id, owner/calendar, type/title/description/location/URL, owned course/resource links, temporal variant, busy flag, status/completion, source identity/revision, series/original occurrence key, revision, timestamps, deletion marker. |
| calendar_series | owner/calendar, recurrence and local DTSTART/zone for manual series OR routine policy link. Linked routine schedule is read from the policy. Store split lineage/termination. |
| calendar_occurrence_overrides | unique owner/series/original key; moved/cancelled/skipped/completed override, replacement values and revision. Tombstones prevent cancelled instances reappearing. |
| calendar_permissions | concrete calendar, owner, read mode none/busy_only/details, edit mode ask/allow, action scope, revision, human grant timestamp, revocation. |
| calendar_operations | owner/idempotency key/request hash, actor, proposal/hash, grant and target revisions, state, minimal before/after snapshots, provider receipt, safe errors, undo eligibility. Reuse existing connected action operations for Google execution. |
| calendar_sync_state | unique owner/connection/calendar, cursor, lease, last success, next attempt and backoff/error state. |
| calendar_change_outbox | durable committed invalidations/provider jobs, unique operation reference and claim/retry state; reuse existing suitable jobs/outbox. |

Routine payload additions: presentation kind study_session/automation, optional calendar, block duration, linked activity, pause-until and exception support. Existing routines default to automation without schedule/action changes. Study routines allow 5 minutes–8 hours. Never convert legacy cron to a guessed RRULE.

Index owner/calendar/time, owner/source identity, owner/series/occurrence, operation identity and pending job time. Verify PostgreSQL locking while preserving SQLite development. Event and calendar ownership is checked for all course, routine and resource references.

Temporal variants:
- Timed: RFC3339 start/end instants and IANA event zone; end > start.
- All-day: startDate and exclusive endDate, without conversion to UTC midnight.
- Deadline: dueAt plus zone OR dueDate, not a fake duration.

Bound occurrence queries to 93 days, 500 rows per page and bounded recurrence expansion. Return pagination and per-source freshness/partial errors. Range semantics are half-open [from,to); include timed overlaps and relevant local all-day dates. Stable cursors bind filters and snapshot; expired snapshots request a refresh, never silently omit rows.

## 7. Recurrence, routines and reminders

Account timezone governs relative dates and initial display. Never silently assume Los Angeles. Changing display zone does not move stored events or routine wall times. Changing recurrence zone is an explicit series edit.

Keep existing one-time DST gap/ambiguity validation: ask for a different wall time or explicit offset. For recurring schedules, skip nonexistent local times and choose the first offset once on ambiguous dates. Extend/test the existing scheduler to match the calendar expansion exactly before enabling this rule. Monthly day 31 skips months without that date. All-day dates remain stable across zones.

Support daily, weekdays, weekly selected days, monthly day, interval, until/count, and never-ending series through bounded expansion. Keys represent original local occurrence identity and disambiguation, not moved time. Future editing splits series while preserving past history and exception lineage. Entire-series editing does not silently rewrite completed history.

Study routines occupy time. Automations remain in the Routines list, with optional non-blocking run markers. Start launches existing owned review/lesson/quiz/chat actions. Complete is an explicit student action or verified completion from the precisely linked activity occurrence. Starting and elapsed time are not completion.

Skip cancels one occurrence's unclaimed work; pause stops future scheduling; resume starts with the next future occurrence and never replays a backlog of paid AI actions. Pause-until resumes through durable worker logic. Editing invalidates future fires by revision. Workers recheck before effects; already dispatched work may finish and must be reconciled honestly.

Use one occurrence identity across display, reminder fires, action execution and completion. Extend the existing action registry only deliberately; calendar integration does not authorize new arbitrary runtime capabilities.

Reuse reminder_service and notification workers; no second ticker. Notification identity includes event revision/occurrence/offset/channel. Academic projections do not create duplicate reminders alongside academic scheduling. Advance reminders and routine-start actions are different triggers; one must not execute the other's AI actions.

Local reschedule/cancel and reminder invalidation are transactional. Quiet hours may delay notification but never move the event. Preserve channel consent and service-worker integration. Inbox is durable; push provider handoff does not prove a notification was displayed.

CRUD, deterministic reminders, sync and display use no AI allowance. Buddy planning and AI routine work use existing unified reservation/settlement. Exhaustion shows the event but blocks paid work with a clear status, without a repeated spend/retry loop. Manual calendar remains usable.

## 8. Buddy consent and saved permissions

First read consent offers busy/free or event details by calendar. Default Buddy read is none and edit is ask; direct owner access is separate. OAuth scopes and app-level Buddy permission are both required where applicable. Saved edit permission never overrides no-access or provider read-only roles.

First edit card shows exact before/after, selected calendar/account, timezone, conflicts, recurrence scope and external notification effects:

> Allow Buddy to make this change?
> [ ] Don't ask again for changes to my Open Learn calendar
> Allow this change · Cancel

For Google substitute the exact calendar/account name. Checkbox starts unchecked. Only authenticated Allow creates permission; checking alone, cancelling, model arguments, or text inside an event cannot grant access.

Unchecked authorizes one exact proposal. Checked authorizes it and atomically persists a concrete-calendar grant. If the provider subsequently fails, retain the visibly saved permission with a revocation control. Multi-calendar plans authorize each calendar separately. A saved grant allows ordinary user-requested create/edit/single-event cancellation; it does not invent ongoing background scheduling. An automation requires its own explicit admission.

Always ask for invitations/notifications to others, attendee-impacting edits, entire recurring-series deletion and calendar-sharing/permission changes. Explain these exceptions below the checkbox. Use sendUpdates=none unless notifications were explicitly approved; calendar permission does not authorize email actions.

Settings → Buddy permissions → Calendar exposes No access, Busy/free, Read details, Ask before editing and Allow ordinary edits, per calendar, with grant date and Revoke. Permissions are consistent across the owner's Buddies. Revocation increments revision, invalidates proposals and unauthorized queued work, removes private cached context from future agent use, and is checked immediately before dispatch. Already dispatched effects need reconciliation, not a false cancellation promise.

Existing standing grants are disabled: implement a calendar-specific evaluator, not a global unattended-write switch. Preserve Gmail/browser and delegated-child write restrictions. Child agents may propose; the owning authorized execution path applies changes. Update old connected-action copy/tests that unconditionally require exact approval only for the newly supported calendar cases.

## 9. Agent tools and execution protocol

Trace the actual conversational tool registry and register typed tools there. No separate Calendar chat mode:
- calendar.list_events: bounded range and privacy-filtered calendars.
- calendar.find_availability: duration/range/preferred hours; reports source completeness.
- calendar.propose_changes: typed local/external/series/routine actions with base revisions.
- calendar.apply_proposal: proposal/hash plus authenticated approval or evaluated saved grant; model cannot assert permission.
- calendar.get_operation and calendar.undo_operation.

Resolve ambiguous event names, target calendars, recurrence scope and dates before writes. Read-only/no-access responses explain the missing permission. Event descriptions/imported content are untrusted data, not instructions. Busy-only fields never enter prompts or tool artifacts.

Lifecycle: draft → awaiting_confirmation OR authorized_by_grant → executing → applied/failed/conflict/outcome_unknown. Queue acceptance is not success. Provider-confirmed effects may have mirror-refresh pending. Emit accurate progress such as Checking your schedule, Waiting for approval, Updating Physics revision and Checking whether the update succeeded.

Local mutation, audit/revision, reminder invalidation and job enqueue share a transaction. Provider I/O uses durable leases outside long DB transactions. Revalidate account, grants, task and target revisions, provider capability/ETag and edit scope before dispatch. Recheck conflicts on stale plans; ask when new conflicts arise instead of silently choosing a new time.

Idempotency keys bind immutable request hashes. Retry the same logical request with the same key. Unknown provider outcomes reconcile using known provider IDs/operation markers, not another blind create. Local batches are atomic. Google batches return item-level partial results; never report whole-plan success for a partial save.

Applied receipt: actual action, dates, View in calendar and Undo if eligible. Undo is a compensating authorized revision-checked operation. Offer a 10-minute window only for supported changes; reject after intervening edits. Do not claim invitations can be unsent or external recurring deletions safely reconstructed. Retain minimal before snapshots securely under existing retention policy.

## 10. API contracts

All endpoints authenticate owner from session, never body. Writes use Idempotency-Key and expectedRevision as relevant. Structured errors include code/message/fieldErrors/currentRevision. Use 409 for stale versions/hashes, 403 permission, 422 invalid inputs, 503 dependencies. Follow existing API wrappers.

| Proposed endpoint | Contract |
|---|---|
| GET /v1/calendar/calendars | Source/role/visibility/Buddy permission and freshness metadata. |
| GET /v1/calendar/occurrences | from,to,timezone,calendarIds,courseIds,types,cursor; items,nextCursor,snapshotRevision,generatedAt,sourceStates,partial. |
| GET /v1/calendar/events/{id} | Owned event, revision, recurrence/source, supported actions. |
| POST /v1/calendar/events | Typed manual creation; operation and confirmed event or pending status. |
| PATCH /v1/calendar/events/{id} | Expected revision, changes, recurring scope/original occurrence key when required. |
| POST /v1/calendar/events/{id}/cancel | Revision/scope; durable cancellation and tombstone. |
| POST /v1/calendar/occurrences/{id}/completion | Revision, complete/incomplete; validate linked completion evidence. |
| POST /v1/calendar/availability | Range/duration/hours/calendars; slots and source completeness. |
| GET/PUT /v1/calendar/preferences | Account zone, default view, week start, working hours and duration. |
| GET/PUT /v1/calendar/permissions/{calendarId} | Human-only grant/revocation and expected revision; not an agent tool. |
| POST /v1/calendar/proposals | Exact bounded plan with revisions/hash and 15-minute expiry. |
| POST /v1/calendar/proposals/{id}/decision | Revision/hash, allow/cancel, rememberPermission and concrete scope; authenticated human UI action. |
| GET /v1/calendar/operations/{id} | Durable item statuses, safe receipts and undo eligibility. |
| POST /v1/calendar/operations/{id}/undo | Current revisions and independent idempotency key. |
| POST /v1/calendar/calendars/{id}/sync | Rate-limited deduplicated refresh operation. |

Reuse GET/POST /v1/reminders and PATCH /v1/reminder-routines/{id}. Extend routine contracts for skip, occurrence moves, future splits, pauseUntil and calendar metadata without breaking legacy clients. Add detail/occurrence routes under that domain as needed. Legacy connected-action routes must share authorization and operation logic rather than bypass it.

Feed item minimum: id,calendarId,sourceType/sourceId,occurrenceKey,seriesId?,routineId?,revision,title (or Busy), temporal variant,type,courseId?,busy,status,canEdit,permittedScopes,linkedActivity?,syncStatus. Agent and owner GUI reads use explicit different privacy projections.

## 11. Google synchronization

Reuse GoogleConnections/GoogleAdapter and encrypted token storage. Before implementation consult current official Google Calendar API documentation for calendar discovery, freeBusy, incremental sync, recurrence and deletion. Existing event scopes do not prove discovery/freeBusy permission; request minimum additional scopes incrementally and handle denied scopes explicitly.

Discovery lets users select calendars, see provider roles, opt into sync and choose Buddy read/edit scope. Existing Google connections do not automatically enable persistent Buddy writes. Busy-only access must redact before model/tool output, including logs/artifacts.

Persist provider IDs, ETags, cursors and tombstones. Implement initial pagination, incremental sync, expired-cursor full refresh, cancelled/moved recurring instances, revoked/expired tokens and bounded Retry-After/backoff. One sync lease per calendar. Never expand already-expanded Google instances again.

Use durable polling initially (target every five minutes, configurable) with rate-limited manual refresh. Webhooks are optional, not required for correctness. Show stale status on worker outage. Reconcile on reconnect before writes. Disconnect stops jobs and revokes grants; remove mirrors from active views by default and require an explicit choice to retain independent copies.

Writes enforce role, OAuth capability, app grant, ETag and recurrence scope. No success claim until provider confirmation. Deletes, all-day mappings, series operations and unknown-outcome recovery require implementation, not just create/update. Disable unsupported controls until their provider path is complete; do not claim the milestone complete while advertised operations are unsupported.

## 12. Implementation structure

Suggested frontend files under `web/components/calendar/`: calendar-workspace, toolbar, filters, week, month, agenda, event-sheet, event-form, routines, permissions and action-card. Add `web/lib/calendar-client.ts`, calendar-types and pure calendar-layout helpers; `web/hooks/use-calendar.ts` owns range cache/request cancellation.

Add shareable `/calendar` routing following the current workspace architecture, with date/view query parameters and Back/Forward support. Do not put private titles/descriptions in URLs. Reminder links open the exact occurrence/date. Calendar shows no unrelated notes panel.

Lazy-load the full workspace; Dashboard uses bounded agenda data. No per-event request waterfalls. Cache keys include owner, permissions, range, filters and zone. Drop stale responses after account/permission changes and clear private caches on sign-out. Refresh after committed changes, on focus and every 30 seconds while visible with backoff/no overlapping requests, or reuse an existing suitable event transport. No new permanent WebSocket requirement.

Suggested backend `backend/app/calendar/` modules: contracts, repository, service, routes, occurrence expansion, source adapters, permissions, proposals/operations, sync and worker handlers. Register in existing API and hosted jobs. Centralize privacy/authorization/recurrence; reuse identity, encryption, allowance and notifications.

Extend account export/deletion/restore for events, overrides, preferences, routine links and safe operation metadata. Never export secrets. Restored accounts must reconnect providers and reauthorize saved Buddy grants. No new blanket 30-day calendar deletion policy. Respect existing retention; redact sensitive logs. Course deletion resolves links without deleting unrelated personal events.

## 13. Recommended build order and gates

1. Inventory actual route/tool/schema/scheduler/grant paths; record deviations from this baseline, finalize temporal and occurrence contracts.
2. Local foundation: migrations, default calendar, CRUD, owner isolation, recurrence/overrides, idempotency and academic/reminder projections. API acceptance passes.
3. Calendar UI: navigation, four views, forms, filters, recurrence scopes, deep links and mobile/error/offline behavior against the real backend. Writes survive reload.
4. Dashboard: shared Today/deadlines, compact review/recent learning/routines. Existing course/review/reminder actions still work.
5. Routines: canonical policy integration, skip/move/split/pauseUntil/resume, reminder deduplication, completion and allowance enforcement. Prove no duplicate fires.
6. Buddy: typed read/availability tools, consent/privacy, ambiguity handling, study planning and exact one-off approved writes.
7. Saved permission: agreed checkbox, scope/revocation/exception rules, receipts, undo, races and restart recovery. Do not enable auto-authorized writes before this passes.
8. Google: discovery/scopes, sync, roles, recurring read/write/cancel, saved grants, unknown outcomes and revoke/reconnect. Live isolated-calendar acceptance required.
9. Release: migrations, API/workers, flags, production canary and visual/device verification; verify actual deployed revisions.

Each milestone includes implementation, meaningful tests and docs. Completing local UI is not completing this specification.

## 14. Acceptance matrix

Functional: create on desktop, reload and observe on mobile/Today; update once across views. Cover leap days, month/year boundaries, overnight/all-day spans, date-only deadlines, multiple zones and DST. Verify overlap layout, availability completeness, filters/no results, month overflow, keyboard focus, mobile safe areas and keyboard. Linked resources open correct owned activities; stale/deleted references fail gracefully.

Routines: existing entries display once; no duplicate notifications. Skip/move one, edit future recurrence, pause-until, resume after outage and complete linked practice without corrupting history. In-flight actions reconcile rather than falsely cancel. AI exhaustion preserves manual calendar and non-AI notifications.

Permissions: unchecked first approval asks again next time; checked approval persists only for that calendar across devices. Cancel never grants. Stale proposal rejects. Cross-account/calendar/provider permissions cannot leak. Revoke blocks queued work. Invitations, attendee edits and whole-series deletion still ask. Gmail/browser grants stay unchanged. Busy-only prompts, artifacts and logs contain no private event contents.

Reliability: duplicate create/approval/retry produces one effect; changed request under same key rejects. Concurrent editors conflict instead of losing changes. Two PostgreSQL workers claim once. Kill a worker between provider effect and local receipt: recovery does not create duplicates. Cover provider 429, expired sync cursor, revoked token, read-only role, timeout after success, recurring exceptions and partial batch results. Stale/offline states never imply empty schedules or successful writes.

Live checks: dedicated Google test calendar with no real attendees; verify create/update/cancel/recurrence/consent/dedup/disconnect. Verify inbox and actual browser/device push where supported, distinguishing handoff from display. Capture desktop dark/light and mobile 320/390/768px layouts. Exercise a busy month with at least 500 occurrences, bounded pagination and no clipped controls. Measure latency and worker lag under realistic load.

## 15. Deployment, observability and completion

Add documented backend/frontend flags for Calendar UI/reads, local writes, Buddy writes, saved grants and Google sync. These are proposed flags, not currently verified names. Server enforcement is mandatory. Reuse existing reminder settings. Expand-only migrations and backward-compatible defaults precede feature activation. Deploy compatible API/workers before frontend enablement; retain old reminder routes during transition.

Check shared DB, notification/sync workers and actual scheduler health. Do not silently upgrade paid hosting. Observe agenda latency/errors, sync age, pending-operation age, reminder lag, permission conflicts, duplicate prevention and unknown outcomes. Alert on sustained sync failures, existing reminder lag thresholds and stuck operations. Logs contain IDs/safe codes, not calendar descriptions or tokens.

Canary a test account before broad enablement. Rollback disables admission of new writes/jobs while letting dispatched effects reconcile; preserve schema/data. A Git push is not proof of deployment: verify frontend and API/worker commit IDs and health. Re-evaluate known type errors rather than ignoring validation. Preserve unrelated local changes and coordinate shared-file edits.

Coding agent deliverables: code/migrations, API and permission documentation, meaningful tests, screenshots, live acceptance evidence with secrets redacted, deployed commit IDs, and a runbook for stale sync, unknown writes, reminder backlog, revocation and rollback. State unavailable credential/provider checks honestly.

Definition of done: students manage a real cross-device calendar and routines; Dashboard reflects it; Buddy reads and performs appropriately authorized changes with the agreed Don't ask again option; ownership, time, notification, usage and recovery behavior all have evidence. A calendar grid and permission checkbox alone are not completion.
