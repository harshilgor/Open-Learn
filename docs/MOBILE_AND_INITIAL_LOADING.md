# Mobile and initial loading improvements

## Production release — October 6, 2026

The mobile/loading release is live at https://open-learn-eta.vercel.app.
Vercel deployment `dpl_2KArWaD9rdMLvsBENSxtq4P6B6wy` is READY and was promoted
after its Next.js production build and TypeScript checks passed. The live domain's
deployment ID and mobile stylesheet were verified; its homepage returns HTTP 200.
The configured direct backend returns HTTP 200 for health and HTTP 401 for an
unauthenticated account request, as expected.

An isolated release snapshot at `outputs/mobile-production-release-20261006` uses
the previous production commit `dd2f4f6b9919fa712eb36ae62e18694caf552c8e` plus
the mobile/loading and supporting UI changes. The parallel dictation code was
excluded; the production-baseline composer avoids the shared file's encoding issue.
No dictation source files or backend features were overwritten. Thirty focused
tests passed against this isolated release. Its `release-manifest.json` records
source-file hashes and the prior deployment for traceability.

Production currently uses the configured direct API URL. Its same-origin `/v1`
proxy returns 503 in both the prior and new deployments because no server-side
proxy origin is configured; this release does not change that routing setup.

The implementation and earlier working-directory verification notes follow below.

Implemented in the shared working directory, without editing the dictation composer,
chat implementation, microphone capture, worklet, or backend feature files.

## Changes

- An isolated mobile stylesheet owns the shell, header and composer layout at widths
  below 1024px. Secondary Buddy controls remain available in the Buddy sheet.
- The writing field and action buttons use separate rows. Dictation, voice, send and
  attachment buttons remain present, with 44px touch targets on mobile.
- The shell follows the visual viewport when the keyboard opens; bottom navigation
  hides while keyboard space is needed. Long drafts scroll inside the writing field.
- The collapsed mobile Today section no longer mounts or fetches its schedule.
- Notes and the study panel mount on their first opening and remain mounted afterward,
  preserving editor drafts across closing and navigation.
- Reminders, settings, course home, review, course dialogs and sign-in forms use dynamic
  imports. Other existing static imports still make quiz/reading code candidates for a
  later bundle review once the parallel chat changes settle.
- Concurrent first authenticated requests share one account initialization. Individual
  cancellation does not cancel authentication for other callers. Old account responses
  cannot publish identity after an account switch. An explicit first account read reuses
  the initialization response instead of fetching it twice.
- Browser JSON reads share concurrent requests. Courses, Buddy profiles, Today and review
  summaries have a 15-second memory cache; authority snapshots, jobs and balances have
  no retained cache. Responses are copied so consumers cannot mutate shared cache data.
- Writes invalidate the cache before and after completion. Account changes, focus,
  reconnects, chat history/title changes and voice refresh events also invalidate it.
  Aborted requests, explicit reload/no-store requests and server-side reads bypass sharing.
- Removed the redundant session-position lookup in LearningWorkspace; its existing
  header/session effect already supplies the course identifier.

## Measuring the next live load

The proxy now returns `Server-Timing: proxy_upstream;dur=...`, retaining upstream
Server-Timing values when present. Compare these timings with total request durations
in browser developer tools to distinguish backend wait from browser/proxy overhead.

`getApiPerformanceSnapshot()` in `web/lib/api-performance.ts` exposes the last 100
actual requests in memory, including identity initialization, duration and status.
It does not record tokens, query strings, learner identifiers, bodies or response content.
No analytics requests or external telemetry were added.

Measure a fresh authenticated production load with mobile throttling, then compare:
account lookup count, duplicate reads, JavaScript transfer/parse cost, time until the
composer is ready and API response durations. The isolated local preview had no
reachable local API, so no live-server speed improvement has been measured yet.

## Verification

- 51 focused tests passed across loading, identity, keyboard viewport, draft preservation,
  tutor, notes, dictation, hosted proxy and authentication checks.
- Additional timing instrumentation passes application TypeScript checking and lint
  (existing warnings remain). The subsequent full-suite retry timed out at automatic
  permission review and did not execute.
- The earlier full suite passed 114 tests and found three failures in compact tutor chat
  and Buddy retry behavior, plus one incomplete transport mock. The mock was updated
  and its focused tests passed. The three other failures reproduce with the original API
  implementation and remain outside this change.
- Browser checks at 320x568, 390x844, 768x1024 and 1024x768 found no horizontal overflow.
  A six-line mobile draft caps at 112px, scrolls internally and does not overlap navigation.
- Application TypeScript checking passes. The original whole-workspace check reported
  three errors in `tests/agent-execution.test.tsx`; that file is being edited elsewhere.
- Production build remains blocked by invalid UTF-8 in `web/components/chat-composer.tsx`.
  That file was left untouched because it belongs to the parallel dictation work.

The screenshot in `outputs/mobile-layout-390.png` shows the actual local mobile layout
with a long draft. Its offline notices reflect the unavailable local API.

## Remaining integration work

After the dictation agent saves its composer as UTF-8, rerun the production build and
the full frontend suite. Measure the deployed authenticated cold load before changing
backend hosting. Moving optional chat-restore transition/note work out of the blocking
restore path remains deferred because it requires editing the shared chat implementation.
