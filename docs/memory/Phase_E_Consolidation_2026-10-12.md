# Learner memory Phase E: consolidation and forgetting evidence (2026-10-12)

## Evaluation

Command: `python -m backend.app.evaluation_runner --memory`. Fixture: `backend/evaluation/memory_forgetting_scenarios.json`, version 1, with 15 cases (§11.3 category 9). Each case seeds facts and episodes with ages and use history. It then runs one consolidation at `now + advanceDays` and checks:

- the resulting status of every seeded row (`deleted` when the row is gone)
- the stored core profile, where the case specifies one

| Behaviour covered | Cases |
|---|---|
| Unused, low-importance facts archived (including after 365 simulated days) | 3 |
| Learner-stated constraints never archived (retention floor) | 2 |
| Tentative inference deleted after 30 days; tentative learner statement archived instead | 2 |
| Recent tentative kept; reinforced tentative promoted | 2 |
| Past deadline archived, upcoming deadline kept and profiled | 1 |
| Recently used goal and confirmed preference survive despite age | 2 |
| Near-duplicate merged into the older fact | 1 |
| Year-old episode archived | 1 |
| Shadow facts deleted after 30 days | 1 |

Result: 15 / 15 (`forgettingCorrect` = 1.0, gated at 1.0). `learnerStatedDeleted` = 0, gated at 0: no fact the learner stated or confirmed was deleted. The extraction gates (Phase C) and retrieval gates (Phase D) are unchanged and still pass.

## Latency (SQLite, laptop)

Command: `python -m backend.scripts.memory_retrieval_benchmark --core-profile --out …`, with 2,000 facts and 300 episodes for one owner. Raw report: [Phase_E_Core_Profile_Benchmark_2026-10-12.json](Phase_E_Core_Profile_Benchmark_2026-10-12.json).

| Measurement | Value |
|---|---|
| One consolidation run (background job) | 763 ms |
| Retrieval with the core profile, warm p50 / p95 | 9.7 / 14.9 ms |
| Retrieval with the core profile, cold p95 | 46 ms |
| Same seed without the flag, warm p95 | 17.5 ms |

- **The two runs differ in size.** Consolidation archived 837 of the synthetic facts (random ages up to 400 days at importance 0.5), so the run with the flag ranks fewer active facts.
- **What this shows.** The core-profile read (one indexed `context_records` lookup, through Redis when that namespace is enabled) adds no visible cost, and the 25 ms target holds.

## Latency (PostgreSQL 16, local Docker on Windows)

Command: `python -m backend.scripts.memory_retrieval_benchmark --database-url-env OPENLEARN_QUALIFICATION_URL [--core-profile] --out …`, run against the disposable `deploy/compose-performance.yaml` database. Raw reports: [without the flag](Phase_E_Postgres_Benchmark_2026-10-12.json), [with the core profile](Phase_E_Postgres_Benchmark_core_profile_2026-10-12.json).

This was the first PostgreSQL measurement of the Phase D read path, and it missed the 25 ms target: warm p95 was 34.8 ms. Profiling showed 7 round trips per turn at 1.5–3 ms each on this setup (PostgreSQL in Docker on Windows), plus about 12 ms of Python ranking. The fix cut the database work per turn to 2 round trips:

- one combined watermark query (version, active fact count and active episode count)
- the core profile cached per process behind that watermark (a profile rewrite now bumps the memory version)
- course names fetched only when a course-scoped line is rendered

| 2,000 facts, 300 episodes | Before | After |
|---|---|---|
| Mean per turn, core profile on | 27.4 ms | 15.3 ms |
| Warm p50 / p95, core profile on | 26.4 / 34.5 ms | 13.6 / 20.8 ms |
| Warm p50 / p95, flag off | 25.1 / 34.8 ms | 16.8 / 26.0 ms |
| Cold p95, core profile on | 66.6 ms | 59.9 ms |
| One consolidation run | 3.3 s | 3.0 s |

- **With consolidation on, the target holds.** That is the configuration Phase E ships. The flag-off run ranks all 2,000 synthetic facts and lands at 26 ms; with consolidation, 837 of them were archived.
- **The rest is Python.** About 9 ms of each turn is the ranking loop over every candidate fact. Cutting it would mean pre-filtering candidates in the cached index; that's left for later because the target holds.
- **Hosted numbers will differ.** Round trips to a same-region managed PostgreSQL are usually shorter than to Docker on Windows.
- **SQL compatibility.** A smoke run on the same PostgreSQL exercised the scheduler query, episode insert and coverage, review flags, the change log, profile storage and per-session episode deletion. All passed.

## Shadow review tooling

`python -m backend.scripts.memory_shadow_report --days 14` reports aggregate counts only: extraction job outcomes, skip reasons, proposed and accepted facts, validator rejection reasons, and shadow facts per kind. It never reads statements, quotes, messages or owner IDs, and it withholds per-kind counts below 20 distinct owners (§12 rollout step 3).

## Tests

`backend/tests/test_learner_memory_phase_e.py` has 28 tests (one covers the shadow report). They cover:

- each consolidation step
- idempotency and owner isolation
- that no learner-stated fact is deleted for disuse
- profile ordering, token cap and byte-stable rewrites
- the after-commit Redis bump
- the read path, including that forgotten facts leave the profile at once, assessment filtering, and flag-off fallback
- episode building, scheduling and idempotency, plus deletion with the conversation
- the scheduler and worker dispatch
- the `/profile` and `/changes` APIs
- that account erasure removes the profile and change log
