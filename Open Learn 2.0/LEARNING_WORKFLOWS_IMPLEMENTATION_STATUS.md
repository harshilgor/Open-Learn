# Learning workflows implementation evidence

Updated 3 October 2026. This records delivered code and verified behavior; it does not claim validated learning outcomes or production readiness.

| Brief | Delivered integration | Verification / remaining acceptance |
| --- | --- | --- |
| 04 Ledger | Workflow observations, immutable attempt references, reversible interpretation, latest committed correction wins while original occurrence controls learning history | Cross-session invalidation and out-of-order correction regression tests pass. Full authorized late offline device journey still needs acceptance. |
| 05 Concepts | Existing stable concepts, course mappings, reviewed relations, canonical resolution now used when reading quiz and teaching capability state | Migration chain and workflow integration exercised. Merge/split graph editor browser acceptance still required. |
| 06 State | Existing shared reducer with conservative capability attribution, distinct family/session/delayed evidence, retention; scored questions explicitly attribute validated rubric target and capability | Exposure/skip/assistance cannot demonstrate learning; deterministic replay/delayed candidate checks pass. Demonstrated promotion remains gated pending labeled calibration. |
| 07 Hypotheses | Existing analysis/diagnostic service and UI; explicit dedicated checks retain distinguishing objectives, regular diagnostic loops bounded | Diagnostic planner scope/quota tests pass. Real provider diagnostic discrimination needs labeled fixtures. |
| 10 Control | Default enabled shared compiler; immutable snapshots, exact context text in Ask/Learn/Quiz prompts, owner/evidence/source commit fences, normalized teaching gears | Cold start and concurrent evidence fence tests pass; Ask/Learn streaming and 25-turn compaction/replay pass. Teaching continuity uses canonical Journey compaction, avoiding false invalidation of its own summary. |
| 11 Quiz | Typed QuestionPlan before authoring, coverage reservations, fresh families, assisted followup/retention/transfer objectives, immutable agreed scope, trace persistence, objective UI | Scope/quota/bounds/family tests and checked question/hint/idempotency flow pass. Full course-level prerequisite objective selection and symbolic validation for supported numeric types require further acceptance. |
| 12 Grading | Existing exact private choice grading and span-checked weighted written grading; assistance disclosure; durable challenge adjudication, independent key/solution confirmation, source citation gates, uncertain review preservation, append corrections, state rebuild and downstream repair notification, public effective grades | Cross-session invalidation preserves original attempts and excludes scores. Private key safety and assistance flow pass. Real provider uphold/regrade/replace, source revision race during adjudication, complete review-player effective resolution UI and automatic replacement launch still require acceptance. |
| 13 Teaching | Explicit action policy, learner direct request priority, hint/check disclosure constraints, supported hypothesis actions, bounded repeated intervention history, declined follow-up preservation, delivered content/before-state revision and later quiz outcome lineage | Direct request, hint disclosure, loop bounds and exposure semantics tested. Browser explanation-choice UX and delayed causal outcome evaluation remain acceptance work. |

## Verified commands

`backend/.venv/Scripts/python.exe -m pytest backend/tests/test_learning_workflows.py -q -p no:cacheprovider -p work.pytest_workspace_tmp_plugin --tb=short --show-capture=log` — 17 passed.

`backend/.venv/Scripts/python.exe -m pytest backend/tests/test_adaptive_objectives.py backend/tests/test_challenge_corrections.py backend/tests/test_control_plane_integration.py backend/tests/test_assessment_quality.py backend/tests/test_assessment_context_planner.py -q -p no:cacheprovider` — 18 passed.

The workspace temporary-directory plugin avoids pytest's Windows private-directory ACL rewrite; it only overrides the test fixture, not application permissions. SQLite emits Python datetime adapter deprecation warnings. Focused tests use generated test databases and deterministic/mock providers, without paid provider calls.

## Integration boundaries

- Migration `0036_learning_workflows` follows `0035_source_memory` and adds an owner/kind/parent index for workflow lookups.
- Challenge corrections emit `assessment.challenge.resolved` with readiness and unstarted task invalidation intent. Consumers must rebuild from current accepted ledger state before decisions.
- Readiness and planning must use accepted evidence and shared capability projections; a quiz percentage is not mastery.
- Original attempts are immutable; `attempt_resolution` records provide public current interpretations.
- Definitive evidence from unverified generated lesson context is excluded even when author and checker agree.
