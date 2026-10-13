# Chat reminders and scheduled activities

The Render backend owns scheduling. Vercel only submits commands and displays results.

## Enable

Apply migration `0052_chat_reminders`. Use the paid blueprint in `deploy/render-paid.yaml` to provision `openlearn-notifications` and the one-minute backup cron. Set `OPENLEARN_CHAT_REMINDERS=true` after the worker is running. The embedded browser worker also drains notifications for local development.

Required environment settings:

- `DATABASE_URL`: shared PostgreSQL database
- `OPENLEARN_CRON_SECRET`: random shared secret for the cron endpoint
- `OPENLEARN_REMINDER_API_ORIGIN`: HTTPS Render API origin
- `OPENLEARN_VAPID_PRIVATE_KEY`, `OPENLEARN_VAPID_PUBLIC_KEY`, `OPENLEARN_VAPID_SUBJECT`: web push configuration
- `OPENLEARN_EXPO_PUSH_ENABLED=true`: optional mobile push
- `OPENLEARN_REMINDER_DIGESTS=true`: optional bounded digest generation; templates still deliver without a model
- `OPENLEARN_REMINDER_EMAIL_ENABLED=true`, `RESEND_API_KEY`, `OPENLEARN_REMINDER_EMAIL_FROM`, `OPENLEARN_REMINDER_EMAIL_RECIPIENTS`: optional Resend delivery. Recipients are a server-provisioned owner-to-email JSON mapping. Each user must also opt in.

No deployment or secrets were applied by this change. Free API services can sleep and cannot guarantee anytime reminders. The backup cron claims and enqueues missed work; delivery still requires a functioning notification worker.

## Chat commands

- `Remind me tomorrow at 3pm to call Sam`
- `Remind me in 20 minutes to review my notes`
- `Remind me every weekday at 7:40am to study`
- `Quiz me weekdays at 7:40am on photosynthesis`
- `Show my reminders`
- `Cancel the Sam reminder`
- `Snooze the Sam reminder for 1 hour`

The parser accepts these explicit patterns, ISO dates, and weekday times. With a configured provider, a bounded JSON compiler can interpret broader routine requests. Ambiguous commands return a clarification instead of scheduling guessed work. Quiz routines require a conversation and a configured model to prepare questions. Weak-topic quizzes select developing or untested concepts mapped to the current conversation graph; they do not silently broaden to unrelated courses.

## API

`POST /v1/reminders` requires `Idempotency-Key`, `message`, and either `when` or `schedule`. Schedules support five-field cron or RRULE with `startsAt`. Both store an IANA timezone. DST gaps and ambiguous wall times are rejected for one-time requests; cron skips invalid wall times. Routines respect quiet hours; explicit one-time reminders retain their requested time.

`GET /v1/reminders`, `POST /v1/reminders/{id}/cancel`, and `POST /v1/reminders/{id}/snooze` are owner scoped. `PATCH /v1/reminder-routines/{policyId}` supports revision-checked pause/resume/delete. Delete disables a routine and preserves history. Preferences use `GET/PUT /v1/reminder-preferences`.

`POST /internal/reminders/tick` accepts `X-OpenLearn-Cron-Secret` and claims at most 100 general fires per call. `reminder_runtime` stores the last successful tick and counts. `GET /internal/reminders/status` uses the same cron credential and reports tick lag, overdue rows, and status counts. Academic reminders continue through their existing revision-bound path. Academic listing is also available at `/v1/academic-reminders`; `/v1/reminders` lists every kind.

## Action pipeline

Actions are limited to five per occurrence and resolved against `reminder_actions.build_registry`. Available adapters include quiz shell/first item/public descriptor; flashcard due summary/review session/generation; academic task generation/advice/view/single task; website task; learning digest; cards-due/session conditions; notify and Buddy message. Arbitrary capabilities, destructive ingestion, shell execution, research/lab agents, and tutor streaming are not admitted.

Each fire is a `reminders` row. `reminder_action_runs` records step status, job reference, artifacts, and safe error codes. A leased `reminder_actions` job runs the pipeline. Long website/flashcard work returns a job reference; each tick reconciles completed work and queues the remaining steps. This durable polling bridge avoids depending on an in-memory completion callback. Artifact-producing actions complete before notifications. Failures produce an inbox notice or suppress delivery according to `onFailure`.

Inbox is the durable delivery guarantee. Push records provider handoff rather than claiming the user saw the alert. Unknown send outcomes are retained and not blindly resent. Expo delivery records tickets and reuses the existing responsibility receipt checker. Email recipients must be provisioned by operators; account email verification is not supplied by this change.

## Remaining production work

Before enabling for users, exercise PostgreSQL concurrent tickers, actual closed-app push and desktop delivery, real provider quiz preparation, worker termination recovery under load, mobile receipt reconciliation, and a 10k-row load trial. Wire alerts for scheduler lag over two minutes and failure rate over five percent. The repository tests cover SQLite scheduling, idempotency, ownership, expiration, recurrence, DST, and academic regression; they do not establish production delivery latency.

Provider interpretation and weak-topic selection require a live provider and populated learning-state verification before production release. Routine editing is available through the API; conditions include due cards, session presence, and no recent study activity. Disable `OPENLEARN_CHAT_REMINDERS` to stop new chat admission without deleting persisted reminders; workers keep draining existing work.
