# Evaluation and learning outcome instrumentation

Establish a reproducible baseline and measure policy, question, grading, operational, and delayed learning outcomes separately.

Status: planned. Source: section 22 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Shared data contracts and architecture decisions](02_shared_data_contracts.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/tests](../backend/tests)
- [web/tests](../web/tests)
- [backend/app/evaluation_runner.py](../backend/app/evaluation_runner.py)
- [backend/app/adaptive_observability.py](../backend/app/adaptive_observability.py)
- [backend/app/generation_service.py](../backend/app/generation_service.py)

## Implementation sequence

1. Freeze representative current histories and configurations before replacing policy behavior; label synthetic cases and authorized de-identified examples.
2. Create expert-reviewed policy/context and audited question/rubric corpora, including adversarial authorization and source-injection cases.
3. Record decision inputs, family and intervention metadata, assistance, immediate and delayed outcomes, and intervening practice.
4. Run comparisons and define release thresholds with reviewers. Report missing follow-up explicitly and avoid claiming retention gains before data exists.

## Detailed feature requirements

### Establish the baseline before replacing behavior

Build a regression corpus from representative learning histories before enabling the new policies. Include clearly labeled synthetic histories for deterministic coverage and authorized de-identified real examples for realism. Freeze the current context, quiz-selection, state-reduction, and teaching behaviors as comparison configurations. A baseline must be reproducible from fixed input histories and provider settings.

Evaluate policy decisions separately from generated content and learning outcomes. A correct choice of prerequisite check does not guarantee a valid question. A valid question does not establish improved delayed retention. Separate measures let the team identify which component caused a regression.

### Policy and context evaluation

Create labeled scenarios for assisted-only success, conflicting results, strong prerequisites, an unknown transfer capability, stale recall, misread questions, corrected sources, and uncertain exam scope. Record acceptable next actions and prohibited conclusions. Expert reviewers establish labels; model judges can assist review but do not define the truth alone.

Measure concept-resolution accuracy, context relevance, required-evidence inclusion, invalid-source admission, diagnostic appropriateness, unnecessary repetition, and correct uncertainty handling. Include privacy adversarial cases and prompt injection in source documents. Deterministic scenarios must also verify the exact contributing event IDs and reason codes.

### Question and grading evaluation

Maintain an audited item set with source passages, verified keys, acceptable equivalent written answers, rubric criteria, and known flawed examples. Evaluate factual validity, solvability, answer leakage, duplicate families, rubric coverage, and grade agreement with reviewers. Require challenge workflows to repair dependent state correctly.

Run content checks across the supported subjects and response types. Report disagreements by concept and item type rather than hiding them in one average. A high overall pass rate can mask a broken equation parser or consistently unfair short-answer grading.

### Learning outcomes

Store the intervention, learner-state snapshot, immediate assessment, delayed checks, assistance, and intervening activity. Delayed outcomes include retrieval after approximately one day and one week, and longer checks where students return. Transfer uses a materially different task rather than repeating the original example. Participation and missing follow-up are reported, not interpreted as failure.

Use these observations to compare the old and new policies without claiming causation from a before-and-after score alone. Where practical and authorized, randomize among educationally reasonable interventions, record assignment probability and eligibility, and evaluate matched outcomes. Prefer independent later checks. Measure student effort, interruptions, and dropout alongside correctness so an adaptation does not improve scores merely by making the experience burdensome.

### Calibration and strategy data contracts

For each presented question, store question family, content revision, target capabilities, requested complexity, response type, source basis, validation history, learner-state snapshot before presentation, assistance, outcome, timestamps, and selection policy. Distinguish observed latency from active response time when available. Preserve privacy by separating identifiers from analysis extracts.

For each intervention, store action type, eligibility basis, learner choice, decision revision, generated content, exposure, immediate outcome, delayed outcome, and subsequent practice. These records support future question calibration and strategy comparison. They do not fit an IRT model or a personalized RL policy in this implementation.

### Release acceptance

Require all authorization, deduplication, correction, replay, and dependency-invariant tests to pass. Require zero unauthorized cross-account admissions in the security test corpus. Use expert-reviewed scenarios to set educational quality thresholds before rollout; do not invent a universal percentage from unlabeled examples. Compare latency, cost, and user effort against the baseline and review material regressions explicitly.

Educational outcome evidence develops over time. Functional completion requires a working measurement pipeline and a documented baseline comparison; improved long-term retention must be reported only after the corresponding follow-up data exists. The team should never claim a measured benefit based solely on architecture completion.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
