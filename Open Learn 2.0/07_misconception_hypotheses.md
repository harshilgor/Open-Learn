# Misconception hypotheses and diagnostic checks

Preserve possible explanations for errors and use distinguishing checks to support, contradict, or resolve them.

Status: planned. Source: section 9 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

Implementation: migration `0034`, hypothesis analysis/diagnostic service, durable worker integration and learner UI added. See [implementation notes](../docs/MISCONCEPTION_HYPOTHESES.md). Runtime acceptance checks remain pending.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Evidence ledger and reversible observations](04_evidence_ledger.md)
- [Stable concepts and course mappings](05_stable_concepts.md)
- [Unified learner state and retention](06_learner_state_and_retention.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/state_service.py](../backend/app/state_service.py)
- [backend/app/assessment_generation.py](../backend/app/assessment_generation.py)
- [backend/app/immediate_adaptation_policy.py](../backend/app/immediate_adaptation_policy.py)

## Implementation sequence

1. Extend hypothesis records with competing explanations, supporting and contradicting event IDs, expiry, and status history.
2. Reuse rubric error analysis; request bounded model interpretation only when meaningful learner reasoning requires it.
3. Validate cited response spans and concept IDs, then update support through deterministic diagnostic outcomes.
4. Connect hypothesis state to question planning and teaching actions; expose tentative wording, student corrections, and diagnostic results.

## Detailed feature requirements

### Value and representation

An incorrect answer can result from a misconception, arithmetic slip, missing prerequisite, misreading, or ambiguous question. We will preserve possible explanations and gather discriminating evidence rather than treating the first generated diagnosis as a personal fact.

Each hypothesis stores type, target concept, concise description, support category, supporting and contradicting event IDs, proposed distinguishing observation, status, analyzer revision, and dates. Status is proposed, supported, contradicted, resolved, or expired. Hypotheses are not mutually exclusive; a learner can have an arithmetic issue and a conceptual confusion simultaneously. Their support scores need not sum to one.

### Analysis and updates

Run analysis for meaningful rubric-level errors after an answer is accepted. Reuse structured error analysis from grading when possible. Make a separate bounded model call only when the response contains reasoning worth interpreting and existing output is insufficient. Simple choice errors usually justify a candidate diagnosis, not a detailed claim about the learner's thought process.

Provide the analyzer with the question, rubric, learner response, assistance, source-backed expected reasoning, and relevant prior events. Require a small set of hypotheses, citations to response spans or prior events, competing explanations, and an appropriate follow-up. Validate concept ownership, source references, and supported error categories. A model cannot create evidence IDs or assert that a learner performed an unobserved reasoning step.

A deterministic updater changes support when a diagnostic distinguishes explanations. Correctly solving the isolated null-space step contradicts a null-space weakness hypothesis while leaving eigenvector interpretation unresolved. Failing the isolated step supports the prerequisite hypothesis. A recently taught explanation followed by assisted success does not immediately resolve the hypothesis; an independent check is needed.

### Teaching and assessment integration

The assessment planner can choose a diagnostic objective that compares plausible causes. The pedagogical engine can select a contrastive explanation for a supported confusion. Tentative hypotheses can shape a short clarifying question without being stated as established truth.

Use a cap on active hypotheses per concept and an expiry rule for unsupported old candidates. Keep previous evidence and status history so a hypothesis can be reopened when the same pattern returns. Avoid carrying a permanent negative label from one historical error into every future lesson.

### UI and completion requirements

Say, for example, that the answer suggests a possible mix-up between eigenvalues and eigenvectors and offer a short check. Allow the student to identify a misread question or typo; record that explanation as self-report and evaluate it alongside task evidence. Test competing explanations, analyzer hallucination, contradiction, resolution, expiry, and reopening. Completion requires a diagnostic to visibly change the teaching action and the hypothesis history.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
