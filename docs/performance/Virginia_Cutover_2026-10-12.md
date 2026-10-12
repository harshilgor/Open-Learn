# Virginia API cutover — October 12, 2026

Approved recurring cost: $25/month for one Render 1-CPU/2-GB Virginia API. No additional workers or database subscriptions purchased.

New API: https://openlearn-api-virginia.onrender.com (`srv-db68giu7bikc73fipn6g`). Old free Oregon API remains available for rollback, in external worker mode. Virginia runs embedded execution. Both Vercel production API origin variables now reference Virginia. Fresh source deployment used commit `e91b4038cc4b76496fb32c1f40a4643299d70d87`; frontend/backend commit, API-origin fingerprint and pinned schema contract were verified. Supabase data was not migrated.

## Initial production browser measurements

| Prompt | Accepted | First text committed | Complete |
| --- | ---: | ---: | ---: |
| Inertia, two sentences | 0.917 s | 2.990 s | 3.661 s |
| Bus contextual follow-up | 0.536 s | 3.161 s | 3.599 s |

Prior single observation on Oregon: 16.819 / 59.737 / 81.121 seconds for inertia. Latest first text is approximately 95% lower (20 times faster) in this observation. Different machine/region/background conditions and two samples do not establish p95 or causal separation of compute versus placement. First-text target of 2.5 seconds remains unmet in these samples. Evidence retained in `outputs/performance/virginia-cutover-timings.json` and `virginia-cutover-proof.png`.

## Operational follow-up

GitHub Production API origin, service ID and existing scoped deployment hook have now been retargeted to Virginia after GitHub reauthentication. Release #27 successfully deployed commit `d752c0f30404815b737902c057cdddb8472a6299`, including schema 0087, after all three quality gates passed. Staged and promoted frontend/backend checks passed. Oregon was refreshed to that exact commit in external mode; the full topology verifier then passed, including rollback schema compatibility. The previous preflight passed all three quality gates, then stopped before production writes because another agent merged newer main work; the release candidate incorporates that main commit.

Additional captures contain 11 completed generations: acceptance median 696 ms (517–1,813), first committed text median 2,496 ms (2,259–6,670), completion median 3,432 ms (2,954–7,539). Two successful synthetic note writes took 503 and 529 ms; persistence was checked after reload. Mixed scenarios, overlapping requests and small sample sizes do not qualify production percentiles. See `backend/scripts/summarize_browser_timings.py` and the ignored content-free captures under `outputs/performance`.

A permitted brief In-Class recording uploaded and transcribed three slices; capture was stopped and the short recording completed with partial coverage. This is not full lecture qualification. Pre-release browser/reminder/quiz checks exposed an outbox shortcut forcing ordinary tutor generation and skipping action admission. The release restricts the shortcut to plain Ask turns, preserving the normal mode/action paths; 32 focused frontend cases and TypeScript passed locally. Hosted browser admission successfully opened example.com. The chat-reminder flag was absent, was enabled on the pinned release, and a synthetic reminder appeared in the workspace with its scheduled time, then became delivered with an unread Buddy reminder badge. Quiz mode created and persisted a five-question activity, but first-question preparation logged `QualityRejected`; that flow is not qualified. Source-grounded comparison remains in progress; do not bypass assessment quality checks to claim success.

Independent workers remain unactivated. The prepared roles need 17 steady connections and a conservative overlap/reserve budget of 37, exceeding the observed shared server pool of 15. `check_shared_pool_cutover.py` blocks activation until the pool sizing or connection strategy is reconciled. Supabase quota warnings also require capacity review; no upgrade was purchased.

Rollback requires restoring frontend origins to Oregon and transferring execution back, rather than merely promoting the old frontend while Oregon remains external. Refresh Oregon to schema-compatible code after the release migration before calling it a ready fallback; `verify_production_topology.py` checks that compatibility. See `Virginia_Rollback_Runbook.md`. No disruptive production rollback drill has been performed.
