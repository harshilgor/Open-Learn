# Quiz quality implementation status

This tracker accompanies `QUIZ_QUALITY_AND_EXPERIENCE_IMPLEMENTATION_PLAN.md`.
Quiz release `fcb0056c723f47dd56733929b49bd58535deb392` is deployed to production as of 2026-10-09. Educator validation remains pending.

## Production release

- Render deployment `dep-db4k3bqd0e5s73clkfug` reports **Deploy succeeded | Live**, serving commit `fcb0056` on the existing Free service.
- Vercel deployment `dpl_E2umGYk5wZtw6P3Numr5HEv2dPRJ` is READY and promoted to `https://open-learn-eta.vercel.app`.
- Both `main` and `codex/free-render-backend` received the isolated quiz-only commit. Concurrent classification, agent-platform, chat and dictation changes were excluded.
- New v2/UI/model-profile enrollment is enabled. Sol 6.1 authors at high effort and verifies/evaluates written answers at medium effort. Prefetch remains off for this initial rollout; existing allowance and platform limits were preserved.
- Live synthetic author + independent verification passed in 52.859 seconds. Live written grading passed in 23.969 seconds after exact unique quotation anchoring was added. This validates integration, not educator-reviewed superiority or production latency percentiles.
- The isolated checkout passed 28 quiz and billing tests. An additional focused test verifies offset re-anchoring accepts only exact unique learner quotations and refuses fabricated/ambiguous quotations.
- Public `/ready` returned HTTP 200; the live OpenAPI schema includes quiz capabilities, finish, and usefulness endpoints. Production homepage returned HTTP 200 and the authenticated Practice workspace loaded.
- Tariff snapshot: `sol61-20261009-v1`, OpenRouter model `openai/gpt-6.1-sol`, USD per million tokens: input 2, output 10, cache read 0.1, cache write 2.5.
- Two live integration issues were fixed before release: strict schemas duplicated in prompts exceeded reservation limits, and role/profile metadata incorrectly changed a model's shared rate-card hash. Legacy Haiku rate-card shape is preserved.
- Rollback: disable new v2/UI/model enrollment in Render; preserve pinned tariffs and v2 readers for in-flight sessions. Prior Vercel release was `dpl_C3WH7UvDUuAhmfsrWmyPKiC2FyAv`; prior Render code was `1a5940d`.

## Implemented in the working tree

- Dedicated author, verifier, and written-evaluator profiles; credential-free snapshots; Sol 6.1 identifier `openai/gpt-6.1-sol` verified against OpenRouter's catalog.
- Configurable reasoning, strict response schemas, transport limits, explicit tariffs, and existing usage-ledger enforcement.
- Session plan v2, challenge preferences, reasoning tasks, coverage reservation, public purpose text, and bounded diagnostic follow-ups.
- Corrected learner-visible leakage checks, intentional skill repetition, private distractor explanations, and bounded arithmetic verification.
- Structured written feedback; conservative handling of choice/rationale disagreement; unverified generated-context exclusion in both evidence paths.
- Exam-deferred feedback and delayed evidence release; finish/review endpoint; explicit public serializers.
- Answering-time accounting and persisted checking reservations; invalid responses do not pause time; cancellation/failure release paths.
- One private background candidate, guarded promotion, source revalidation, and worker integration.
- Revised question card, optional choice rationale, draft/help restoration, expandable feedback/sources, mobile CSS, and results review.
- Thirty synthetic benchmark cases, held-out transfer cases, export tooling, and blinded human-review form.
- Reviewed written-grading comparison runner with status agreement, absolute score error, unsupported full-credit counts, uncertainty, and latency; unreviewed questions are refused.
- Exam feedback withheld from note drafting and voice responses; challenge review is deferred until completion, including manually requested review.
- Diagnostic follow-ups retain parent-feedback assistance lineage. Skipping a question still records exposure when its worked explanation is shown.
- Answer acceptance, finishing, pausing, and recovery share a database lock. Prefetched promotion preserves source revisions and discards stale private candidates.
- Immutable profile integrity and explicit tariff allowlists allow in-flight sessions to finish after model-enrollment rollback.
- Aggregate operator report and privacy-safe model/quality/command timing events; no learner responses or private rubrics in general logs.
- Independently stored UI enhancement version; baseline semantic controls and deferred-feedback protections remain active in both versions.
- Owner-scoped end-of-quiz usefulness feedback, separate from scored learning evidence, included in the operator summary.

## Verification during resumed implementation

- Final production build and focused lint passed, including the usefulness control and mobile math changes. Build emits its existing large-chunk warnings.
- Final focused assessment run: 38 passed, including owner-scoped usefulness feedback. The quiz-specific suite previously passed all 20 tests before the final recovery/usefulness additions.
- Six question-card component tests and focused frontend lint passed.
- Shared review/classroom/notes/reminders/model-usage/voice run: 68 passed, four Review tests failed with HTTP 401 in standalone fixtures that do not establish the required principal. An explicit local-principal diagnostic run passed five of seven; its two isolation tests still expect an older header-based identity contract. No authentication behavior was weakened to make these fixtures pass.
- Browser preview: no horizontal overflow at 320, 390, 768, or 1280 pixels; readable dark theme; semantic radio selection enables submission; keyboard Tab moves from selected option to rationale input.
- Long inline equation exposed a mobile overflow bug. Fixed global KaTeX selectors and bounded inline math scrolling; verified a 495-pixel equation scrolls inside its 262-pixel container at 320-pixel viewport width.
- Final grading retry exhaustion releases its persisted reservation and resumes answering time; an expired answering timer completes without fabricating attempts. Both new recovery tests passed.
- Two final targeted tests passed: cancelling during grading fences the late result and resumes answering; deleted source material prevents deferred exam finalization from releasing evidence. A source-invalidated exam remains unfinalized and needs a new quiz from current sources.
- Browser checks use synthetic content with the real question component. They do not establish a successful live provider-to-browser journey.

## Verification recorded before interruption

- 31 focused backend tests passed, including profiles, quality, context, adaptive objectives, timer reservation, candidate promotion, and source deletion.
- Six new question-card component tests passed.
- Focused frontend lint passed.
- Wider quiz/shared workflow run: 33 passed; two existing Journey tests failed on missing `JourneyCommand.selected_text` / context-inspector behavior. These shared files have concurrent work; investigate before attributing or changing them.
- Full TypeScript check has errors in generated `.next` route types and a browser-assistant test mock; no quiz errors were reported in that run.
- Initial build failed because sandbox filesystem permissions blocked Vite package resolution; retry with normal filesystem permissions is pending.
- Live Sol request reached OpenRouter and returned HTTP 402 Payment Required. No successful live question generation or grading comparison has been established.
- Visual preview revealed low contrast because the synthetic preview set `data-theme=dark` without the application's `.dark` class. The preview now applies both; visual recheck is pending.

## Configuration defaults and rollback

The template/rollback defaults below disable new enrollment. Production overrides enabling v2, UI v2 and model profiles are recorded above:

```dotenv
AI_TUTOR_QUIZ_V2=false
AI_TUTOR_QUIZ_UI_V2=false
AI_TUTOR_ASSESSMENT_MODEL_PROFILES=false
AI_TUTOR_QUIZ_PREFETCH=false
AI_TUTOR_QUIZ_TIMING_V2=true
AI_TUTOR_QUIZ_DIAGNOSTICS=true
AI_TUTOR_QUIZ_AUTHOR_PROVIDER=openrouter
AI_TUTOR_QUIZ_AUTHOR_MODEL=openai/gpt-6.1-sol
AI_TUTOR_QUIZ_AUTHOR_EFFORT=high
AI_TUTOR_QUIZ_AUTHOR_OUTPUT_TOKENS=6000
AI_TUTOR_ASSESSMENT_VERIFIER_PROVIDER=openrouter
AI_TUTOR_ASSESSMENT_VERIFIER_MODEL=openai/gpt-6.1-sol
AI_TUTOR_ASSESSMENT_VERIFIER_EFFORT=medium
AI_TUTOR_WRITTEN_ANSWER_EVALUATOR_PROVIDER=openrouter
AI_TUTOR_WRITTEN_ANSWER_EVALUATOR_MODEL=openai/gpt-6.1-sol
AI_TUTOR_WRITTEN_ANSWER_EVALUATOR_EFFORT=medium
```

Set `OPENLEARN_ASSESSMENT_RATE_VERSION` and `OPENLEARN_ASSESSMENT_MODEL_TARIFFS` to reviewed current prices before enabling profiles. The JSON tariff key for this route is `openrouter/openai/gpt-6.1-sol`; fields are `usd_per_million_input`, `usd_per_million_output`, `usd_per_million_cache_read`, and `usd_per_million_cache_write`. Existing paid-route and platform-budget enforcement stays active. Do not raise allowances or bypass billing to make the integration pass.

API: `GET /v1/quiz-capabilities` advertises v2 setup support; create accepts optional `challengePreference` and `feedbackPolicy`; `POST /v1/quizzes/{qid}/finish` uses expected revision and an idempotency key. Existing sessions retain their stored legacy policies. New session plans snapshot v2 decisions. No new tables are required for the current versioned artifact implementation.

Offline benchmark export:

```powershell
python -m backend.scripts.assessment_benchmark --output outputs/quiz-quality-baseline
```

After educator-reviewed questions and response references exist, run the metered grading comparison:

```powershell
python -m backend.scripts.assessment_grading_benchmark --input PRIVATE_REVIEWED_CASES.json --owner AUTHORIZED_OWNER --output backend/data/quiz-grading-comparison
python -m backend.scripts.quiz_quality_report --owner AUTHORIZED_OWNER --output backend/data/quiz-operations-summary.json
```

Reviewed input format is documented in `backend/scripts/assessment_grading_benchmark.py`. The script requires explicit `humanReviewed: true`, a valid written Candidate, response IDs/text, and consistent expected scores/statuses. Do not approve generated references automatically. Keep the detailed grading artifacts private. Operator summaries contain aggregates only. General timing events are `assessment_model_call`, `assessment_quality`, and `assessment_command`.

Metered provider check after credits are available:

```powershell
python -m backend.scripts.assessment_live_smoke --output outputs/quiz-sol-smoke
python -m backend.scripts.assessment_live_smoke --generate --output outputs/quiz-sol-generation
```

## Outstanding requirements: do not mark the whole plan complete

- Broader live author/verifier/evaluator acceptance across subjects and long sources; the first live generation and grading contracts passed.
- Blind educator comparison and execution of the reviewed grading report; runner implemented but no reviewed references or successful provider calls established.
- Full screen-reader validation and a complete live UI-to-API journey; synthetic component checks and durable API tests have passed.
- Resolve the outdated Review/Journey fixture contracts with their owning workstreams. Final production build passed.
- Race acceptance tests across PostgreSQL connections; SQLite persistence tests cover distinct-job ownership, finish guards, source deletion and timer reservations.
- Real process-restart acceptance journey; final-exhaustion, expiry, persisted checking-reservation, cancellation, and deferred-finalization source-change tests passed.
- Confirm every external context consumer honors deferred exam feedback; identified note, voice and challenge paths are fixed.
- Full operational measurements from real sessions: cost per presented question, discarded-prefetch costs, waiting-time percentiles, coverage displacement, and learner usefulness. Summary/collection code exists; actual values require real sessions.
- Full production rollback exercise and measured enrollment expansion. Production v2/UI/model routing is enabled; background prefetch remains disabled.

Rollback disables new v2/model/prefetch enrollment through configuration; already-created sessions still need their stored contracts and model profiles to finish. Never remove the v2 deserializers as a flag rollback.
