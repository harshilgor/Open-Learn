# Learner memory Phase C evaluation (2026-10-12)

Command: `python -m backend.app.evaluation_runner --memory`. CI runs it in `platform-quality.yml`. Fixture: `backend/evaluation/memory_scenarios.json`, version 1, with 50 hand-labeled cases.

**What this measures:** the deterministic write path, meaning the validator plus the store (supersession and deduplication). It replays *recorded* extraction outputs, including adversarial ones: hallucinated quotes, pasted instructions, inferred sensitive traits, invalid kinds, and facts about other people.

**What it does not measure:** live model quality. Measure that in `shadow` mode on real traffic before switching to `on` (§12).

| Category | Cases | Passed | Precision | Recall |
|---|---|---|---|---|
| extraction | 10 | 10 | 1.00 | 1.00 |
| knowledge_update | 10 | 10 | 1.00 | 1.00 |
| injection | 10 | 10 | 1.00 | n/a (expects no facts) |
| sensitive | 10 | 10 | 1.00 | 1.00 |
| abstention | 10 | 10 | 1.00 | n/a (expects no facts) |

Overall, all gates from §11.3 pass:

| Metric | Result | Gate |
|---|---|---|
| Extraction precision | 1.00 | ≥ 0.9 |
| Extraction recall | 1.00 | — |
| False-memory rate | 0 | = 0 |
| Abstention correct | 1.00 | ≥ 0.95 |

Findings while building the suite:

- **ISO dates looked like phone numbers.** The original phone-number pattern in the denylist matched ISO dates (`2026-11-03`), which would have rejected every deadline. The pattern was fixed, and tests cover the fix.
- **Facts about other people were accepted.** "my roommate is failing physics" carried a verbatim quote ("is failing physics") and passed every §7.4 check. The validator now rejects quotes whose sentence names another person ("my roommate", "my friend", "she said", …) when the quote has no first-person words.

Not yet covered (later phases): retrieval recall@k, temporal questions, multi-session aggregation, and forgetting (§11.3 categories 1–4 and 9).
