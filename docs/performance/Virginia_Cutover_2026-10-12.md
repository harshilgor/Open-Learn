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

GitHub Production release variables and its Render deployment hook must be retargeted to the new service before the next coordinated release. Existing release automation still targets Oregon; do not dispatch it until this is reconciled. Full feature qualification, additional prompt/note measurements and independent-worker activation remain outstanding. Rollback requires restoring frontend origins to Oregon and transferring execution back, rather than merely promoting the old frontend while Oregon remains external.
