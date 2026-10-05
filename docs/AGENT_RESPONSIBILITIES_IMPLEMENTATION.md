# Milestone 5: responsibilities and notifications

Implemented locally on 2026-10-04 against `Open Learn 2.0/26_agent_execution_platform.md`, with the build plan in `docs/AGENT_MILESTONE5_PLAN.md`. This is local implementation evidence, not hosted or physical-device acceptance.

## Behavior

- Owner-scoped ongoing responsibilities retain course/conversation scope, revision, schedule, active interval, run cap and notification policy. Weekly IANA wall-clock schedules preview three occurrences. One-shot and event-only schedules are available through the API.
- Weekly DST gaps advance to the first valid minute; folds fire once. Missed periods coalesce, overlapping work skips, source identity plus generation/revision deduplicates finalized lectures, and self-caused triggers do not run. Durable `last_checked` provides fair bounded scans across worker restarts.
- Scheduled and lecture-triggered work launches the existing attached-only research task and its existing source/artifact/learning continuation flow. Each task receives a bounded snapshot of private operational notes. Notes do not create learner-performance evidence or expand source access.
- Pause fences current descendants and future triggers. Disable stops future work while leaving the current task alone. Resume restores paused work. Stop all cancels both. Editing fences obsolete tasks and rejects stale revisions and course-scope changes.
- Weekly run caps include tasks from older responsibility revisions. Existing task tool/resource limits and owner task capacity remain in force. The initial run cap uses fixed UTC seven-day accounting buckets; monetary provider admission remains governed by existing capability policy.
- Inbox notices deduplicate terminal and input-required states and link to the owning conversation/task. Optional Expo delivery honors quiet hours, expires delayed notices, records tickets and receipts separately, revokes invalid tokens, and avoids replaying unknown sends. A provider handoff is not proof the learner received a notification. See [Expo delivery semantics](https://docs.expo.dev/push-notifications/sending-notifications/).
- Existing chat surfaces provide schedule preview/save, explicit controls, goal steering, note inspection/correction/deletion, inbox and acknowledgment. API additionally exposes one-shot/event-only intent and token registration. The native client and permission flow belong to milestone 7.
- Account export includes owned records; account deletion removes them. Imports exclude runnable responsibility state. UI responses are fenced when the account changes.

## Code

- `backend/app/agent_execution/responsibilities.py`: schedules, dispatch, controls, notes, inbox and Expo receipts.
- `backend/app/agent_execution/responsibility_routes.py`: strict authenticated APIs.
- `backend/app/agent_execution/worker.py`: periodic responsibility scan before task dispatch.
- `backend/migrations/versions/0046_agent_responsibilities.py`: additive tables. The concurrent milestone 6 branch merges this revision at `0047_agent_connected_actions`.
- `web/components/assistant/responsibilities-panel.tsx`: current chat integration.

Set `OPENLEARN_AGENT_ADMISSION_ENABLED=true` to admit responsibility tasks. Push is off by default; set `OPENLEARN_EXPO_PUSH_ENABLED=true` only with configured native credentials and registered owned tokens. Inbox requires no push token. Run the existing supervised agent worker for schedules to progress; merely opening the web UI does not run a hosted scheduler.

## Verification

Commands from repository root:

```powershell
python -m pytest backend/tests/test_agent_responsibilities.py -q -p no:cacheprovider -p no:tmpdir
python -m pytest backend/tests/test_agent_responsibilities.py backend/tests/test_agent_execution.py -q -p no:cacheprovider -p no:tmpdir
```

- Final responsibility suite: **10 passed**, covering DST, task outbox dispatch, dedupe, overlap/caps, controls, owner/revision boundaries, lecture events, HTTP integration, quiet hours, invalid tokens, receipt failures, restart fairness and account export/delete.
- Foundation plus responsibility suite before the last two added cases: **17 passed**, including the additive migration downgrade/upgrade roundtrip.
- Earlier foundation/research/sandbox plus responsibility regression run: **58 passed**; that run contained the first six responsibility cases.

From `web`:

```powershell
npm run test:agent
npx tsc --noEmit
npx eslint components/assistant/responsibilities-panel.tsx tests/responsibilities.test.tsx
npm run build
```

Agent UI suite: **20 passed**. TypeScript, focused lint and production build pass. Repository-wide `npm run lint` reports **10 errors and 20 warnings** in other existing/shared files; it is not a clean repository-wide result. No whole-repository test-pass claim is made.

## Remaining acceptance gates

Hosted PostgreSQL concurrency/restart evidence, supervised deployed workers and S3 integration remain unverified. Physical iOS/Android push permission, receipt, notification-open/deep-link and revoked-device journeys require signed native builds and devices. No live Expo notification was sent by these tests. General connected actions and external writes are milestone 6; hosted mobile release is milestone 7. This milestone is implemented and locally verified within the first-release responsibility scope, but is not released.
