# Performance benchmark protocol

Source of scenario/threshold data: [workload.json](workload.json). This is an engineering qualification specification; no measured traffic supports the proposed 1/10/50 concurrent-user levels yet. Revise assumptions when actual arrival rates and geographic usage are available.

## Three distinct forms of evidence

1. **Offline regression and baseline:** CI executes deterministic context, branching, permission, mode, note, migration, and replay checks. The benchmark runner uses disposable SQLite, synthetic inputs, and fixture streaming. It measures admission -> persisted text -> completion, and note-save/revision behavior. It does not establish model quality or production latency.
2. **Isolated hosted staging qualification:** after P05–P07 provisioning, run each scenario under baseline/growth/burst profiles with real PostgreSQL, production framework artifacts, configured providers, background traffic, and multiple browser tabs. Use at least 100 eligible samples per scenario/profile; record cold starts separately. These load levels are qualification inputs, not supported-capacity claims.
3. **Bounded production observation:** use real operational traces and at most the configured small synthetic prompt budget on an approved test account. Do not run burst loads on production. Stop model probes when projected usage exceeds the configured cost budget or service failures make retries unhelpful. Retain failures in the report.

## Timing definitions

- User submission: outgoing message is enqueued locally; for requests outside the outbox, timing begins at stream start. Report that distinction. Restored outbox entries without an in-memory start begin at the current attempt.
- Acceptance: durable backend acknowledgement, including earlier preparation in the same observed submission.
- API headers: backend entry -> response headers; includes middleware/auth and service work. For SSE this excludes the streamed body lifetime.
- SQL execution: DBAPI execute wall time, including lock waits; not a precise split of server execution vs locks vs network. Connection checkout includes creating a new connection when required, excludes SQLAlchemy's later pre-ping/reset work. Connection hold measures checkout -> checkin.
- Provider first delta: entry to the provider streaming iterator -> first returned delta, before per-delta application database work. Provider adapter accounting/network work is included. It is not necessarily meaningful text. Existing durable providerTtftSeconds uses an older broader marker; report the distinction.
- First persisted text: generation runner start -> first nonempty durable text delta. Queue delay is a separate measurement.
- Browser first text received: local observed submission/resume -> first nonempty text event. Record resume separately from fresh TTFT.
- First text committed: React effect after a nonempty streamed block appears in committed state. This is not physical display paint. Current main chat is instrumented; side-chat commits and other rendering surfaces need explicit markers before reporting them as measured.
- Completion: terminal generation status; fixture benchmark also reports a combined scenario duration including note integrity work. Do not mistake that combined duration for only model completion.
- Note save: cloud operation excluding debounce; local recovery and list refresh are separate states. Expected revision conflicts are correctness checks, not service outages.

## Quality and correctness

Every benchmark report includes failures, cancellation/conflict counts, known/unknown provider usage, concurrency, region, commit, schema, sample count, and test mode. Use human-reviewed answers for real-provider comparisons. Require zero ownership violations, lost acknowledged edits, duplicate external effects, unconfirmed mode transitions, or branch/context regressions. Output length and task complexity must be matched when comparing provider speeds.

Scenario coverage includes greetings, ordinary questions, follow-ups while generating, context switches, selected passages, mode suggestions, revisions, notes while generating/offline, browser tasks, documents, in-class, reminders, cancellation/replay, long history/multiple tabs, and identity/usage. Coverage paths in workload.json specify regression evidence, not proof that all scenarios were load-tested.

## Commands

From repository root:

```text
python -m backend.scripts.performance_benchmark --runs 10 --out outputs/performance/baseline.json
python -m backend.scripts.performance_benchmark --runs 100 --concurrency 10 --out outputs/performance/growth-fixture.json
python -m backend.scripts.deployment_audit --frontend https://open-learn-eta.vercel.app --api https://openlearn-api-saku.onrender.com --out outputs/performance/deployment.json
python -m backend.scripts.performance_report --api https://openlearn-api-saku.onrender.com --out outputs/performance/dashboard.html
```

The report command requires LIVE_BRANCHING_METRICS_TOKEN in the operator environment and the new backend endpoint deployed. It never embeds that token in its generated output. It exits if the private endpoint is unavailable. Do not add the token to browser builds or committed files.

Process metrics retain the last 512 durations per fixed stage/resource and counters since startup. The dashboard requires at least 50 samples for timing alerts; that is an investigation threshold, below the 100-sample qualification gate. These diagnostics are not a fleet-wide 30-day availability measurement. Export structured stdout events to the existing operational log sink for aggregate retention. Additional observability integration adoption remains a separate decision.

Browser buffers retain at most 200 API and 200 generation observations and 100 in-memory generation tracking entries. They clear on account changes. No request bodies, response content, owner IDs, tokens, SQL, or URL queries are included. Trace IDs are random correlation values, never metric labels.

SQL/service spans overlap; do not sum them into total request time. Ordinary successful fast API traces are logged at a default 10% sample rate to limit polling-log volume; slow/error/execution traces are retained. OPENLEARN_PERFORMANCE_TRACE_LOG_RATE=1 enables full trace logging for a bounded staging run. Histogram counters still observe all operations. Generation terminal failures are counted from durable state, because an SSE HTTP 200 does not prove that an answer succeeded.

## Initial results and limits

P01 public probes on Oct 10 measured health 2362.549 ms and readiness 2415.100 ms, both 200; these are single samples, not percentiles. The live API lacks the new release/timing endpoints until deployment.

The first successful offline run used 10 scenarios at concurrency 1, with zero failed generations or note-revision checks. Acceptance p50 24.332 ms; persisted first text observed p50 84.577 ms; note-save p50 28.000 ms. Small-sample maxima/percentiles are present in the JSON artifact, but do not qualify the proposed SLOs. Synthetic provider delay is deliberately tiny and excludes the actual production bottlenecks.
