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
- **Not yet measured.** PostgreSQL is still open (as in Phase D).

## Tests

`backend/tests/test_learner_memory_phase_e.py` has 27 tests. They cover:

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
