# Production release and latency observations — 11 October 2026

## Release completed

[Production run #21](https://github.com/harshilgor/Open-Learn/actions/runs/38174094539) succeeded in 8 minutes 21 seconds on `bc6f3b78aceefe3ce2cfae3042a426933b31cb4d`, after the same candidate passed preflight run #20.

Fresh-main, quality, hosted configuration, compiler, migration, Render rollout, backend compatibility, staged frontend compatibility, promotion, public alias compatibility, and protected diagnostic capture all passed. The workflow's phase report records migration, backend deployment, frontend staging and production promotion completed; public alias verification succeeded.

Independent public metadata requests returned HTTP 200 and the same commit for both `https://openlearn-api-saku.onrender.com/release` and `https://open-learn-eta.vercel.app/api/release`. A later recheck at approximately 17:49 PDT still reported that pair. Existing free hosting remains in use; no paid infrastructure was provisioned.

## Production observations

Two synthetic messages were submitted through the signed-in Chrome production UI in a separate chat. A separate synthetic note was created. Existing user drafts were not edited. Further model probes, including the planned braking-bus follow-up, were omitted after the slow response.

| Observation | Result | Timing interpretation |
| --- | --- | --- |
| Initial greeting | Brief, relevant answer eventually displayed. It was still absent at an observation around 46 seconds and present by an observation around 104 seconds. | Setup/greeting observation interval; not an exact TTFT. |
| “Explain inertia in two sentences.” | Generation response row appeared at approximately 25.1–26.6 seconds. No meaningful text was visible at 113.4 seconds. The completed, relevant two-sentence answer was present by the later observation at 348.4 seconds. | UI observation bounds. There was a gap while server diagnostics were inspected, so **348.4 seconds is not the measured completion time or TTFT**. |
| Synthetic note edit | “Saved” appeared approximately 31.5–33.1 seconds after the body edit. Title and exact body were present in the cloud-backed note list/editor after reload. | User-visible confirmation includes debounce and UI work; not an isolated HTTP save duration. |
| Connection status | A “Reconnecting to Open Learn… Your draft is saved” notice was observed while the already completed answer and saved note were available; it subsequently cleared during note-panel interactions. | Recovery/notice handling needs investigation. This does not prove permanent service unavailability. |

The inertia answer was factually relevant: it explained resistance to changes in motion and the relationship between mass and inertia. Note content persisted. These observations do not qualify context-switching, mode recommendations, concurrency, availability or all other user flows in production; regression tests cover those contracts separately.

## Comparison with the earlier baseline

The [earlier hosted measurements](Hosted_Activation_and_Measurements.md) recorded first browser text for the short inertia question at 58.013 seconds and cloud note autosave at 7.811 seconds.

The new sample **does not demonstrate a speed improvement**. No inertia text was visible at 113.4 seconds, beyond the earlier first-text result. Do not attribute that difference entirely to this code release: account/session preparation, existing tabs, background work, network state and measurement method were not held constant. The old note figure was HTTP cloud-save duration; the new figure includes debounce/UI confirmation, so do not compute a direct speed ratio between them.

## Runtime evidence and limits

- Render's sampled CPU peak was approximately 63.5% of the 0.15-core allocation; sampled memory peak was approximately 35.3% of the 512 MiB limit. These minute samples do not rule out brief CPU bursts, throttling or database waits.
- A bounded access-log sample showed repeated calendar, usage, account and assistant polls, together with class reads/finalization requests. This is evidence of active background traffic, not proof that one specific poll caused the delay. Do not interrupt a user's class recording to manufacture a quiet benchmark.
- Targeted Render log queries returned no `openlearn.performance` lines. Verify structured log export/configuration and use the protected operational snapshot before assigning provider-versus-database causality. Missing lines are not zero elapsed work.
- The `performance=1` query flag disappeared during chat initialization and the built-in timing panel stopped being available. Exact browser timing buffers could therefore not be exported through the supported UI. DOM observations were used and are labelled as bounds.
- Browser visibility was checked later and reported visible. Visibility was not recorded continuously during the earlier samples.
- The optional browser download of the already-produced diagnostic artifact stalled despite its requested timeout. No release was retried because of that failure. [The evidence artifact remains on GitHub](https://github.com/harshilgor/Open-Learn/actions/runs/38174094539/artifacts/11715800189).

## Next investigation, before claiming improved performance

1. Keep the profiling opt-in available across initialization/navigation and verify first-text/React-commit buffers in the actual production framework build. Confirm the structured log sink emits the existing content-free stage records.
2. Correlate durable acceptance, queue wait, context preparation, database checkout/query time, provider first delta, first persisted text and browser delivery for the same synthetic trace. Retrieve the existing protected diagnostics through a reliable operator path; do not create broader credentials or repeatedly redeploy to download a report.
3. Investigate background polling cadence/coalescing across existing tabs and repeated class-finalization status handling. Preserve terminal-state reconciliation and active class work while reducing unnecessary requests.
4. Inspect database connection pressure and long transactions alongside generation admission/worker recovery. CPU/memory samples alone do not justify treating a compute upgrade as the solution.
5. Repair the persistent reconnect-notice behavior based on real transport/account state. A successful answer/note save must be reconciled with current connection status.
6. Repeat the bounded, comparable prompt/note scenarios with exact tracing, then use isolated hosting for the larger P20/P22 load and failure qualification. Keep free-hosting and paid-provisioning decisions explicit.

## Retained local evidence

Ignored files under `outputs/performance/` retain public release metadata, UI observation intervals, a sanitized runtime/request-category summary, and screenshots:

- `production-bc6f3b7-release.json` and `production-bc6f3b7-current-release.json`
- `production-bc6f3b7-ui-observations.json`
- `production-bc6f3b7-runtime-summary.json`
- `production-bc6f3b7-success.jpg` and `production-bc6f3b7-app.jpg`

No credentials, private note bodies or raw owner identifiers were added to these artifacts. The synthetic note is named “Performance check — bc6f3b7 synthetic.”
