# Open Learn 2.0 evaluation record

## Frozen starting point

The feature implementation branch starts from application commit `508494ab0557fa0275431d58e196103726796a61`. The existing regression runner and fixtures are preserved. Cloud foundation PR #3 independently recorded its starting baseline as 349 passed, 14 failed, and 2 skipped backend tests; its implementation run recorded 374 passed, 14 failed, and the same 2 skipped. The original 14 failing test IDs are in `docs/OPENLEARN_2_BASELINE.json` on the merged main branch. They must remain visible in comparisons and must not be hidden by changing unrelated expectations.

The current deterministic evaluation command is:

```powershell
python -m backend.app.evaluation_runner
```

It emits machine-readable results in separate categories:

| Category | Current cases | What the result means |
| --- | ---: | --- |
| Existing regression | 6 | Deterministic recommendation, source boundary, assessment quality, grading, source support, and false-mastery checks |
| Policy | 8 | Labeled synthetic teaching-action and question-objective selection cases |
| State admission | 3 | Labeled synthetic exposure, assisted success, and unknown-assistance admission cases |

The new synthetic case corpus is `backend/evaluation/openlearn_scenarios.json`. A deterministic pass means the implementation obeys those scenario contracts. It does not show that students learn more, that generated answers are factually correct across subjects, or that a threshold is calibrated.

## Outcome data required before educational claims

Question presentations and interventions should retain their selected policy revision, objective/action, learner-state snapshot, source revisions, family, assistance, immediate result, and later result. Delayed retrieval should be grouped around one day and one week, with transfer measured on a materially different task. Intervening practice, missed follow-ups, learner effort, and dropout stay explicit. Missing follow-up is not scored as failure.

An expert-reviewed item corpus must include source passages, independently checked keys, rubric criteria, acceptable equivalent answers, known flawed items, and disagreement labels by subject and response type. Authorized de-identified learner histories are separate from synthetic deterministic cases. Model-generated labels alone do not establish ground truth.

The learner demonstration policy currently remains shadowed until reviewed labeled histories support the chosen admission rules. The system may report evidence strength, candidate status, and uncertainty; it must not present unvalidated thresholds as calibrated probabilities. Long-term retention and teaching-strategy benefits remain unmeasured until delayed outcome data are collected and reviewed.

## Repeatable comparison

For every policy change, record the source commit, Python/runtime and dependency versions, fixture versions, policy revisions, test command, pass/fail/skip counts, and exact failing IDs. Compare policy selection, generated content, grading, and learning outcomes separately. Do not attribute a before/after score change to one teaching action without a suitable comparison design and intervening-activity record.
