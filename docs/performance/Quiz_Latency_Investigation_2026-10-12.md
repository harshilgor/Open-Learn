# Quiz latency investigation

## Status

Repository audit and local instrumentation, October 12, 2026. Production settings have not been changed. No live timing baseline is claimed by this document. New spans require deployment before a hosted breakdown can be collected. Existing production observations establish successful question preparation, assisted grading and reload recovery, but do not establish stage latencies or model quality equivalence.

## Actual critical paths

1. The UI posts a durable create command, polls its job, GETs the quiz, posts a separate next-question command, polls again and GETs the quiz again. Learn launches can first save a study note. Create-to-first-visible-question is therefore several sequential requests, not just one model call.
2. Next-question preparation validates revision/timer/current answer, attempts to reuse a prefetched candidate, loads attempts and learning state, selects an adaptive objective, retrieves sources, persists a manifest and prepares shared context.
3. Authoring produces one private candidate. Deterministic source, duplication, arithmetic and schema checks precede independent model solving. Short answers and version-2 questions additionally require a solution/rubric agreement model call. Thus an accepted v2 question normally has three sequential model calls. Up to three candidate attempts are allowed; provider transport failures and durable-job retries are separate from candidate repairs.
4. Publication validates job lease, input revisions and sources, persists the approved item, private solution, presentation and exposure, finishes the job and emits an outbox event in a transaction. No unapproved candidate may become visible.
5. Choice-only grading, skipping and explicit knowledge gaps are deterministic. Written answers require model evaluation plus rubric completeness, supported credit and exact response-span validation. A selected choice accompanied by written reasoning also invokes the evaluator, and disagreement excludes learning evidence.
6. Grading publishes feedback, assistance lineage and learning evidence, then conditionally enqueues prefetch. Prefetch requires quiz-v2 session configuration, the feature flag, feedback status and a non-uncertain attempt. It begins AFTER grading, while feedback is available; it does not presently overlap the student's answer to the current question.
7. Prefetched candidates require current evidence watermarks, revision/source validation and promotion before exposure. A miss or stale candidate falls back to preparation. Preserve those checks.
8. Deferred exams release feedback/evidence only at finish. Challenges use separate independent adjudication. Pause, cancellation, timer reservations and restore must remain valid under optimization.

## Concrete findings and measurement gaps

| Finding | Evidence | Interpretation |
|---|---|---|
| 1.2-second polling interval | `web/lib/learning-workflows.ts`, `waitForJob` | Completion recognition can wait up to one polling interval plus network time per job; not a measured average. Two launch jobs can each incur this. |
| Separate create and first-next commands | `web/components/quiz-workspace.tsx` | Additional admission/queue/poll/read round trips before the first question. |
| Three serial calls for v2 | `backend/app/assessment_generation.py` | Author, independent solve, then agreement cannot all run concurrently without changing information dependencies. |
| Legacy log extras group calls by role | `backend/app/assessment_profiles.py` | Two verifier calls are indistinguishable; root logging may omit extras. New JSON spans use the existing performance sink. |
| Existing benchmark's baseline uses empty profiles | `backend/scripts/assessment_benchmark.py` | This is a legacy-vs-configured comparison, not necessarily the deployed baseline. Do not use its label as evidence of production improvement. |
| Profile snapshots are immutable per session | `backend/app/quiz_policy.py` | Configuration experiments need fresh sessions and explicit pinned settings. Old sessions must retain their profiles. |
| Broad reads during prepare | `backend/app/quiz_service.py` | Attempts, state and interventions warrant query-count/hold measurements before introducing projections or caching. |

## Instrumentation added

`assessment_timing` JSON events carry random execution/event identifiers, stage, milliseconds, status and optional attempt/command labels. They exclude user IDs, answers, sources, prompts, questions, credentials and exception text.

- `queue_age`: first-attempt created-to-claimed observation. Later attempts include backoff and prior execution; report separately. This is not a precise worker-ready-to-start metric.
- `author`, `independent_check`, `solution_agreement`: each actual provider invocation, tagged with candidate attempt.
- `grading`: model evaluation only, including choice rationale checks. Deterministic grading has no model span.
- `prepare`: next-question preparation inclusive of all model calls. Residual against child model durations includes context/data/planning and other validation, not purely database time.
- `publication`: inclusive transaction acquisition, validation, persistence and commit; failures are retained. Create work currently also lives inside this span.
- `command`: inclusive execution; errors included. Preparation/publication are nested, so do not sum them with command.

Summarize exported JSON lines with:

```powershell
python -m backend.scripts.assessment_timing_report outputs/assessment-events.jsonl --output outputs/assessment-summary.json
```

Still required: frontend click-to-visible/poll recognition/render timings; query/checkout/hold correlation; provider token/reasoning-token cost correlation; prefetch hit/stale/miss counts; precise retry-ready queue delay; structured quality-rejection categories paired with attempt timings. Raw model-call completion does not mean a candidate passed semantic validation.

## Hosted measurement protocol

Deploy instrumentation through the normal coordinated release, then capture current configuration/commit/flags and use fresh synthetic quizzes. No real classroom text or learner answers should enter exported performance reports.

Measure first question, subsequent cold question, prefetch promotion, choice-only grading, choice-plus-rationale grading, written grading, uncertain answer, deferred finish and challenge separately. Run a small sequential smoke first; expand across subject/task/difficulty only after confirming provider spend and rate limits. Include rejected/failed cases rather than calculating success-only latency. Do not report p95 from a handful of samples. Capture both end-to-end UI time and worker spans; browser wall time alone cannot attribute queue/model time.

Use randomized/interleaved baseline/candidate order and identical source fixtures. Keep a transfer holdout. Separate cold/warm and concurrency runs. Proposed evaluation corpus already contains six subjects and five tasks; independent reviewed questions/rubrics are required for grading references. Existing generic conceptual-answer fixtures cannot automatically act as ground-truth answers to arbitrary generated questions.

## Optimization order after baseline

1. Replace 1.2-second status polling with authenticated learning completion events plus reconnect/poll fallback. Preserve durable IDs and lease/revision authority. Do not blindly shorten polling across the fleet.
2. Combine create/first-question orchestration server-side without holding a transaction through model calls, preserving idempotency and cancellation. Return the committed public result where appropriate to reduce redundant GETs.
3. Tune author effort against CURRENT pinned high-effort baseline; then tune verifier and evaluator separately. Accept only measured latency/cost gains with no material correctness, relevance, distractor/rubric or grading regression on independent review.
4. Improve valid-candidate yield using rejection categories and structured repairs. Never lower gates or cap output so tightly that truncation increases retries.
5. Retain independent solving. Investigate combining the later agreement judgement only if a design preserves independent solve isolation and rubric validation; merely giving the checker the author's answer would weaken independence.
6. Overlap bounded source retrieval/planning with student work only where dependencies permit. Keep adaptive question selection after answer evidence; speculative fully authored candidates must be fenced and cost bounded.
7. Reduce repeated database reads based on traces. Cache immutable source revisions/private approved content only with ownership and revision checks; never reuse grades or stale evidence projections as authority.
8. Prioritize interactive grading/next-question work above batch tasks and cap prefetch concurrency. Separate workers only after verified whole-fleet database connection budgets and separate paid approval.

Fractions of a millisecond are not a realistic target for remote generated and independently checked questions. Near-instant already-prepared question display is a valid UX target; fresh generation and written grading need empirical seconds-scale budgets, quality guardrails and transparent progress.
