# Production browser measurements — release 23

Measured October 11, 2026 after coordinated production release 23 deployed application commit `faa19614a0dd2ed23ed18047b5266d54efc76cc2`. Chrome's authenticated production interface was used with the opt-in content-free performance diagnostics. A fresh synthetic conversation ran in Conversation/Quick mode; no model or hosting configuration was changed. Two synthetic note updates were performed while tutoring was active.

## Results

All three prompts completed with relevant two-sentence answers. The bus example retained inertia context, and the final prompt changed to linear equations.

| Scenario | Request accepted | First text committed in browser | Completed |
| --- | ---: | ---: | ---: |
| Explain inertia in two sentences | 38.599 s | 94.477 s | 114.283 s |
| Bus example contextual follow-up | 20.324 s | 68.546 s | 84.755 s |
| Linear equation topic switch | 21.195 s | 75.063 s | 93.380 s |

These timings come from frontend instrumentation, measured from submission. First received text preceded first browser commit by **5 / 7 / 7 milliseconds** respectively. This interval does not measure provider-to-browser transit or physical display paint.

| Note PATCH | API round trip | Server database checkout waits | Server SQL time |
| --- | ---: | ---: | ---: |
| First synthetic update | 15.114 s | 11.016 s | 1.506 s |
| Warm second update | 8.002 s | 5.908 s | 1.244 s |

Both note requests returned HTTP 200 and the UI showed Saved. The second update's edit-to-observed-Saved interval was approximately 17.051 seconds, including debounce, scheduling and observation overhead; it is distinct from the 8.002-second PATCH. The first save's confirmation was observed by 28.558 seconds, but the exact confirmation instant was not captured. The tab also showed temporary reconnect states, disabling send until connection recovery.

## Findings

- Production remains far above the 2.5-second short-answer first-text and 1-second note-save targets. The previous local results do not represent this hosted path.
- Admission alone took 20–39 seconds before generation acceptance. This cannot be attributed solely to model inference.
- Content-free server timings show substantial database checkout waits across account, chat, browser and note requests. For the two note writes, checkout waits accounted for roughly 73–74% of browser round-trip time. Server stage durations can overlap; do not add them into a presumed wall-time decomposition.
- Browser first-text commit was quick after receipt; frontend rendering does not explain the minute-long wait in these samples.
- Background traffic from the existing authenticated account and other open tabs was not controlled. The tab restored the existing workspace before creating a new conversation. Notes were edited during follow-up/topic-switch generation. These are representative interactive observations, not isolated load tests or a controlled causal comparison.
- The prior production observation was about 113.4 seconds before meaningful text for one inertia prompt. The current first prompt is about 94.5 seconds, approximately 17% lower in these individual observations. Different conditions and the single prior sample prevent claiming a qualified production improvement percentage.

## Next investigation

Measure generation queue/context/provider stages with matching backend traces; inspect PostgreSQL checkout saturation, query frequency and lock behavior; confirm the deployed pool and process roles and backend/database region alignment. Reduce duplicate polling/admission reads, colocate database/API and isolate generation execution when justified. Increasing a pool without a full database connection budget is not a proven fix. Repeat the same browser prompts after each controlled change.

## Evidence

Raw content-free diagnostics are retained in `outputs/performance/production-after-release23-final-timings.json`, with intermediate prompt captures. Screenshot: `outputs/performance/production-after-release23-browser-proof.png`. Three samples do not establish p95, capacity, cold-start behavior, provider-only latency or all-feature quality. No production SLO pass is claimed.
