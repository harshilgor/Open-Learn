# Newest optimization measurements — October 11, 2026

## Conclusion

The latest changes have **not demonstrated a consistent latency improvement**. The repeated real tutor calls completed successfully and retained the expected contextual follow-up/topic switch. Provider latency varies substantially; production browser latency and the platform's complete feature set are not qualified by this local measurement.

## Local load comparison

Both runs used localhost PostgreSQL, an independent generation worker, the same synthetic provider, 100 greeting and 100 short-tutoring attempts per concurrency profile. These are sequential observations, not an interleaved controlled experiment. Database contents and machine load differ between runs. The newest change immediately commits the first meaningful text fragment while retaining subsequent batching; usage telemetry also follows asynchronous context into finalization threads.

| Concurrent users | Previous first text p95 | Latest first text p95 | Latest acceptance p95 | Latest note save p95 | Latest completion p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 158.758 ms | 202.628 ms | 34.940 ms | 34.487 ms | 324.064 ms |
| 10 | 907.217 ms | 1146.235 ms | 132.016 ms | 63.011 ms | 1431.335 ms |
| 50 | 3952.065 ms | 3801.626 ms | 802.891 ms | 61.257 ms | 4119.611 ms |

All **600 latest attempts completed with zero failures**. Fifty-user first text improved approximately 3.8% in this observation, but remains above the 2500 ms objective. Acceptance at fifty users also exceeds the 750 ms objective. Lower-concurrency observations were slower. Do not attribute these differences solely to the new code or describe this as a production speedup.

Seven isolated recovery checks passed again: API-process-independent completion, ordered replay after notification loss, cross-process cancellation, partial preservation after worker crash, stale-owner rejection, no automatic provider retry and released capacity after recovery. This covers those named checks, not all product behavior.

## Real tutor measurement

A replacement OpenRouter key was explicitly approved, limited to $0.05 total and one hour. Five fresh conversation sequences ran the same three prompts against Haiku 5.5 with real context assembly, durable replay and enforced usage accounting. There were **15 completions and zero failures**. Exact per-call telemetry summed to **$0.0019899**. No alternate model, prefix cache or production traffic was used.

| Prompt scenario | Calls | First text median | First text range |
| --- | ---: | ---: | ---: |
| Initial short explanation | 5 | 2383.424 ms | 1710.103–2866.617 ms |
| Contextual follow-up | 5 | 1311.357 ms | 1223.557–2031.447 ms |
| Topic switch | 5 | 1201.943 ms | 1175.344–1879.028 ms |

The earlier three-call observation had first text of 2087.362 / 1451.368 / 1256.220 ms respectively. The latest follow-up/topic-switch medians are lower, while the initial explanation median is higher. The earlier sample is too small and provider conditions too variable to establish causality or a qualified before/after percentile.

In the first latest sequence, the initial explanation spent **2287.348 ms waiting for provider first text**, with **366.088 ms context build**. Provider waiting remains a major source of latency even when local storage is fast. These timings omit HTTP authentication, frontend proxy transit and browser painting. Five samples per scenario fall below the plan's 100-sample percentile gate. The examples retained inertia context for the bus follow-up and changed correctly to linear equations, but this is not a comprehensive quality evaluation.

## Retained evidence

- `outputs/performance/first-flush-postgres-worker-profiles.json` and its baseline/growth/burst artifacts.
- `outputs/performance/first-flush-generation-faults.json`.
- `outputs/performance/real-tutor-newest-probe.json` and repeats `-2` through `-5`.
- Prior comparator: `outputs/performance/latest-postgres-worker-profiles.json` and `real-tutor-probe.json`.

Application changes remain local. Next measurement should use the actual hosted browser/API topology, enough real-model samples and an interleaved comparison, with provider wait, context build, database wait and browser delivery reported separately. The current results do not justify promising sub-millisecond tutor responses.
