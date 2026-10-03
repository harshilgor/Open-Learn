# Pedagogical policy and adaptive teaching

Select an explicit teaching action that addresses supported needs and leads to an appropriate opportunity to demonstrate learning.

Status: Implemented with direct-request priority, bounded actions, and task scope lineage; explanation-choice browser UX and delayed causal outcome evaluation remain. See [verified coverage and remaining acceptance](LEARNING_WORKFLOWS_IMPLEMENTATION_STATUS.md). Source: section 15 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Unified learner state and retention](06_learner_state_and_retention.md)
- [Misconception hypotheses and diagnostic checks](07_misconception_hypotheses.md)
- [Shared context compiler](09_shared_context_compiler.md)
- [Learning control plane and workflow integration](10_learning_control_plane.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/learning_policy.py](../backend/app/learning_policy.py)
- [backend/app/immediate_adaptation_policy.py](../backend/app/immediate_adaptation_policy.py)
- [backend/app/teaching_prompts.py](../backend/app/teaching_prompts.py)
- [backend/app/journey_service.py](../backend/app/journey_service.py)
- [backend/app/teaching_output_limits.py](../backend/app/teaching_output_limits.py)

## Implementation sequence

1. Define eligibility, context, disclosure limits, and completion semantics for each intervention type.
2. Extend the existing Teach/Check/Repair policy with prerequisite repair, contrastive explanation, self-explanation, and transfer checks.
3. Compile the selected action into existing gear-aware prompts; bound diagnostic loops and preserve direct learner requests.
4. Record delivered intervention revisions, exposure, and linked immediate/delayed checks for evaluation.

## Detailed feature requirements

### Actions and decision inputs

Implement explicit actions for direct explanation, worked example, guided reasoning, minimal hint, prerequisite repair, contrastive explanation, self-explanation, independent retrieval check, and transfer check. Each action defines when it is eligible, what context it requires, how content should be presented, and what observation can follow it.

Inputs include learner intent, current activity, capability state, evidence strength, supported hypotheses, recent intervention history, explicit preferences, course scope, and time available. Prefer a supported reason for a targeted action. If there is no relevant evidence, teach at the requested level and offer a brief check rather than performing an extensive unsolicited assessment.

### Policy behavior

A credible blocking prerequisite gap proposes a short repair. A supported specific confusion selects an explanation that contrasts the mistaken and correct cases. Assisted success proposes an independent task. A concept recently explained but never checked can receive retrieval practice. Adequate procedural evidence with unknown transfer can receive a new application. Repeated failure during teaching can reduce the step size or change the worked example instead of repeating the same paragraph.

Place bounds on intervention loops. A learner should not be trapped in repeated diagnostics or forced guided questions. After a configured number of unproductive turns, summarize the uncertainty, offer a different explanation or direct walkthrough, and let the learner choose. Respect a declined check and record the preference without treating it as failure.

### Content generation and evidence

The model receives the selected action, source-backed target explanation, relevant learner evidence, presentation constraints, and a completion definition. For a minimal hint, specify which information must remain undisclosed. For a contrastive explanation, specify the supported error pattern and competing cases. For a worked example, identify the step that matters and follow with a distinct independent task if the learner agrees.

Store the delivered intervention and content revision. Content delivery is exposure. Lesson completion is an explicit activity state. Demonstrated learning comes from subsequent responses evaluated under the assessment rules. A learner clicking understood is self-report, not proof of transfer.

Teaching quality checks look for source grounding, incorrect claims, leakage into a requested independent check, and failure to follow the selected action. Use deterministic rules for structure and targeted evaluation calls where the risk warrants them. Avoid multiplying model calls on every ordinary Ask answer without measured benefit.

### Outcomes and completion requirements

Link immediate and delayed checks to the intervention, along with the learner-state snapshot before it. Record later intervening practice so improved retention is not automatically attributed to one earlier explanation. Compare strategies through the evaluation harness; do not infer a permanent learning style from a few successes.

The UI can explain that a prerequisite repair is suggested because of two independent errors and let the student continue directly. Test correct targeting, strong prerequisites skipped, uncertainty preserved, direct explanations honored, unproductive loops, and hint leakage. Completion requires an intervention to lead into an evaluable response and update the shared state.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
