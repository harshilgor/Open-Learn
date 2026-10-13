# Learner memory Phase A measurements (2026-10-12)

Scope: offline SQLite with the fixture provider (`backend/scripts/performance_benchmark.py`). These are not production latency numbers and say nothing about answer quality. Each run used 40 chat turns at concurrency 1: 20 greetings, which take the deterministic social-reply path, and 20 short tutoring turns, which go through the conversation path. All runs completed with 0 failures.

Command, with `--memory-preferences` added in this change to seed saved explicit preferences for each synthetic owner:

```
OPENLEARN_MEMORY_CHAT_CONTEXT=<off|on> OPENLEARN_MEMORY_SKIP_UNUSED_COMPILE=<off|on> \
  python -m backend.scripts.performance_benchmark --runs 40 [--memory-preferences 50] --out <file>
```

| Configuration | `memory_retrieve` p50 / p95 | `generation_context` p50 / p95 | first text p50 / p95 | completion p50 / p95 |
|---|---|---|---|---|
| Flags off (baseline) | (not run) | 8.6 / 115.1 ms | 125.9 / 305.7 ms | 283.7 / 432.6 ms |
| Flags on, no saved memory | 0.5 / 0.8 ms | 6.8 / 54.8 ms | 127.0 / 171.1 ms | 229.6 / 283.3 ms |
| Flags on, 50 saved preferences | 2.5 / 3.7 ms | 7.3 / 63.3 ms | 133.6 / 185.5 ms | 225.4 / 340.0 ms |

Findings:

- The memory read adds at most 3.7 ms at p95 with 50 saved preferences. The spec's target is ≤ 25 ms of added p95.
- `generation_context` p95 did not increase. It fell with the flags on, which is consistent with skipping the unused compile. At 40 samples the p95 and p99 tails are noisy, so read the lower p95 as "no regression", not as a measured speed-up.
- Still to measure: PostgreSQL (`--database-url-env`) and hosted traffic.
