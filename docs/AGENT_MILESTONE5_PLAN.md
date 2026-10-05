# Milestone 5 implementation plan

Scope: section 20 and milestone 5 of `Open Learn 2.0/26_agent_execution_platform.md`.

1. Add owner-scoped responsibility, occurrence and operational-note records. Preserve Buddy attribution and existing task IDs; use existing research execution and notifications.
2. Store weekly wall-clock intent with IANA timezone, one-shot wakeups, active intervals and finalized-lecture triggers. Preview three dates; deduplicate occurrences by revision, coalesce missed schedules, skip overlap and self-caused events, enforce period run budgets atomically.
3. Add revision-checked steering, pause descendants, disable future triggers only, resume and stop-all. Edits fence obsolete queued work. Notes are private operational context and never learner evidence.
4. Publish meaningful terminal/input notifications once, with owner-scoped deep links. Inbox remains visible during quiet hours. Add bounded optional Expo delivery with revoked-token handling and separate delivery state.
5. Expose controls, schedule preview, notes and inbox in current chat surfaces. Register account export/deletion and exclude runnable state from imports.
6. Verify schedule DST/missed/overlap, revision, budget, event dedupe, two-owner isolation, controls, delivery and frontend states; run existing agent regressions and production build. Record live/device gates honestly.

Initial capability is attached-only research within an owned course conversation. No scheduled external writes or automatic learner-performance credit. General connectors and delegation belong to milestone 6.
