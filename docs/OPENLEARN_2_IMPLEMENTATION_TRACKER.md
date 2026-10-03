# Open Learn 2.0 implementation tracker

## Starting point and handoff integrity

Cloud checkout started clean at `508494ab0557fa0275431d58e196103726796a61`
(`Build quiz workflows, lecture recording, and unified Notes workspace`).
No `AGENTS.md` was present in the checkout or its workspace parents. The
checkout had migrations 0001–0027 and the existing React/Vinext, FastAPI,
SQLite/PostgreSQL, notes, assessments, streaming and lecture services.

The Windows workspace was **not imported**. Its reported migrations 0028–0034,
new modules and `Open Learn 2.0/` briefs were absent. The specification supplied
in the task is the implementation scope. New cloud migrations
`0028_execution_foundation` and `0029_decision_contracts` are independently
authored; they are not copies of the reported Windows migrations. If that work
becomes available, reconcile both histories and schemas explicitly; do not
stamp a database or concatenate migrations merely because their numbers match.

**This branch does not complete the 25-feature implementation or authorize
production cutover.** Partial contracts and passing component checks are not
integrated feature completion. No educational calibration, verified hosted
operation, imported local changes, or retention improvement is claimed.

## Delivery evidence and dependencies

| Feature | Current cloud implementation | Remaining integration / acceptance |
| --- | --- | --- |
| 01 Application foundation | Partial: existing learning jobs now have revision, attempts, backoff, progress, cancellation, queue and lease fences; short-transaction outbox and watermarks; local/external worker entry point; immutable binary adapters; lecture unit and transcription job insert commit together | All owning producer/consumer migrations; stage output fencing inside legacy lecture/concept extraction; S3 service configuration; PostgreSQL concurrency; account deletion fences; binary-path migration; operational limits |
| 02 Shared contracts | Partial: strict versioned capability, observation, assistance, source-span and decision contracts; separate confidence enums; immutable owner-scoped decisions and revision dependencies with correction invalidation | Authoritative families and downstream consumers; complete decision tracing and source ownership validation in each producer |
| 03 Identity/device sync | Safety hardening only: hosted routes fail closed; local profile guards reject hosted development headers; device-wide export/delete refuse mixed profiles | Verified OIDC flow, PKCE, device grants, offline synchronization, account packages, scoped privacy workflows and deletion-aware restoration |
| 04 Evidence ledger | Not newly implemented; legacy observations retained | Normalized producers, admission, atomic ledger/projection/progress transaction, correction and replay |
| 05 Stable concepts | Not newly implemented; legacy graphs retained | Stable registry, scope resolution, reviewed relationships, legacy mappings and historical edit UI |
| 06 Learner state/retention | Not newly implemented; legacy projections retained | Revisioned reducer, conservative admission, family/session/delay independence, unified retention and shadow comparison |
| 07 Misconceptions | Not newly implemented | Competing hypotheses, bounded analysis, validated support, diagnostic integration and learner history |
| 08 Source memory | Not newly implemented; existing material and note services retained | Shared revision/span lifecycle, eligible retrieval, preferences, corrections and dependent invalidation |
| 09 Context compiler | Not newly implemented; existing context planners retained | One authorized purpose-specific compiler, manifests, budgets, snapshot/watermark checks and cross-workflow integration |
| 10 Control plane | Not newly implemented; existing workflow and streaming lifecycles retained | Decisions integrated with compiler/state, intervention tracking, embedded assessment, cancellation/finalization journeys |
| 11 Adaptive quiz | Not newly implemented; existing author/checker retained | QuestionPlan, objective selection, quotas, family constraints, source scope and recoverable traces |
| 12 Grading/challenges | Not newly implemented; existing assessment lifecycle retained | Response spans, uncertainty validation, cross-session assistance lineage, adjudication and all dependent repairs |
| 13 Adaptive teaching | Not newly implemented | Action policy, direct-request priority, loop limits, leakage checks and linked independent/delayed outcomes |
| 14 Recording/transcription | Partial foundation improvement only: local paths preserved, shared immutable writes, manifest/job atomicity | Capture epochs and native adapters; container-aware decoding; bounded transcription windows, gaps, overlap/revision reconciliation and real platform tests |
| 15 Lecture understanding | Existing pipeline retained, not 2.0 complete | Typed timestamp support, negation/date ambiguity, coverage-only events, academic candidates and corrections |
| 16 Academic model | Not newly implemented; existing courses retained | Immutable field-specific fact reconciliation, student-specific dates, explicit scope uncertainty, manual entry and timeline |
| 17 Canvas reader | Not newly implemented | Local extension packaging/pairing, scoped read skills, navigation/sender enforcement, checkpoints, expiry and disconnect |
| 18 Readiness | Not newly implemented | Immutable scope/evidence reports, diagnostics, revision refresh and planning integration |
| 19 Task generation | Not newly implemented | Executable TaskSpec, transitions, activity linkage, obligation/evidence distinction and deduplication |
| 20 Task advice | Not newly implemented; existing recommendations retained | Hard eligibility, bounded additive reasons, cooldowns and stale-state checks |
| 21 Study planning | Not newly implemented | Availability/timezone constraints, capacity gaps, prerequisites, pinned/active tasks and controlled replanning |
| 22 Evaluation | Partial baseline: fixed original checkout regression comparison, synthetic new foundation/security cases | Expert-reviewed corpora, policy baseline configurations, audited items, delayed outcome pipeline and quality review |
| 23 API/frontend | Partial backend job response metadata and fail-closed boundary; existing screens retained | Complete identity, evidence, source, recording, Canvas, readiness, planning and accessible recovery journeys |
| 24 Operations | Partial worker CLI, polling recovery, bounded leases/retries, safe worker errors | Measurement/targets, capacity/backpressure, audited repair tooling, deletion-aware backup/restore and deployment matrix |
| 25 Migration/cutover | Partial additive SQLite migrations, legacy-job preservation and repeatable upgrades/downgrades tested | Account/concept mapping, conservative backfill, shadow comparison, count/checksum inventory and all-reader cutover |

## Validation

Baseline at the exact starting revision, in a separate detached worktree:
`python -m pytest backend/tests -q --disable-warnings`:
**349 passed, 14 failed, 2 skipped**. The baseline failures are recorded in
`OPENLEARN_2_BASELINE.json`. They remain release blockers; their presence is not
permission to weaken admission rules or invent a roadmap to pass a fixture.

The first full run with cloud foundation/contracts changes:
**373 passed, 14 failed, 2 skipped**, with the same 14 failing test IDs.
Final full backend verification after the audio manifest/job rollback change:
**374 passed, 14 failed, 2 skipped**, with exactly the baseline failing test IDs.
An additional single-profile deletion check and correction-key conflict assertion
then passed in a 10-test focused identity/contract run. Final foundation,
contracts, identity, storage, lecture, review and migration verification:
**51 passed**. New tests are synthetic and provider-free.

Frontend checks: `node --test tests/lecture-capture.test.mjs` **2 passed**;
`npm run test:tutor` **5 passed**. Initial `npm ci` failed because two nested
`@emnapi` lock entries were missing. Those entries were added without changing
existing package versions; a clean dependency installation and subsequent
`npm ci --dry-run --ignore-scripts --no-audit --no-fund` passed. No browser journey,
native device capture or frontend production build acceptance is claimed.

New foundation/contract/privacy/storage checks cover:

- SQLite competing worker claims, expired lease output rejection, replacement
  workers, cancellation, heartbeat, revision mismatch and rollback of attempted
  activity writes.
- Matching command replay, different-payload conflicts, job ownership, bounded
  transient retries and non-retryable authentication failure.
- Outbox rollback, crash between effect and acknowledgment, replay, durable
  worker dispatch and non-regressing projection watermarks.
- Additive upgrade from 0027 with an existing completed job, idempotent migration
  rerun and downgrade preserving that job.
- Strict schemas, contradictory independence, source span bounds, immutable
  decisions, owner-specific reads and revision-specific correction invalidation.
- Hosted development-header rejection and mixed-profile device export/deletion
  refusal without leaking the other profile's records.
- Concurrent immutable local writes, collisions, path/symlink escape checks,
  checksum corruption, and simulated S3 duplicate/lost-ack/provider-failure paths.
- Existing lecture and review regression coverage and audio manifest/job failure
  rollback. These synthetic bytes do **not** establish real media decoding or
  long-recording reliability.

## Next dependency-ordered work

Finish ownership first, including global legacy graph/action routes and every
service entry point. Finish stable concepts and source revisions before ledger
attribution. Then integrate ledger/state/hypotheses, shared context and decisions,
grading, planned quiz and teaching actions. Academic contracts/manual input can
proceed alongside recording. Follow with Canvas, readiness and executable
planning, and finish the full acceptance journeys, cutover and operations.

No feature row becomes complete until its interface, recovery paths, owning
data contracts and integrated acceptance evidence exist. Keep Quick the default,
preserve quiz IDs/attempts and authored notes, and never admit exposure or unknown
assistance as independent understanding.

## Unexercised external gates

No OIDC account/provider, PostgreSQL server, S3 bucket/permissions, model or
transcription credentials, real institution Canvas session, native iOS/Android
capture package/device, or production recovery environment was configured.
The authentication code and native/Canvas integrations themselves are still
unfinished; credentials alone would not make this branch complete.

Required release gates remain: full authorization/correction/replay invariants,
ordinary failure-state UX, live supported-platform recording tests, representative
database/object restoration, labeled educational review, measured runtime targets,
and all supplied integrated user journeys. **Do not deploy or cut over.**
