# Learner memory Phase D: retrieval evidence (2026-10-12)

## Evaluation

Command: `python -m backend.app.evaluation_runner --memory`. Fixture: `backend/evaluation/memory_retrieval_scenarios.json`, version 1, with 50 cases over seeded facts and episodes. Every case also seeds a shared pool of 10 distractor facts. Ranking is deterministic: lexical, concept, temporal and strength signals. The semantic signal is not enabled (§13, embeddings still undecided).

| Category | Cases passed | Recall@5 | Precision | Mean memory tokens |
|---|---|---|---|---|
| single_fact_recall | 9 / 10 | 0.90 | 0.56 | 109 |
| knowledge_update_recall | 10 / 10 | 1.00 | 0.53 | 114 |
| temporal | 10 / 10 | 1.00 | 0.67 | 103 |
| multi_session | 10 / 10 | 1.00 | 0.80 | 115 |
| retrieval_abstention | 10 / 10 | — | — | 62 |

Gates from §11.3 (recall@5 ≥ 0.8 on categories 1–3, abstention ≥ 0.95) all pass, and the extraction gates from Phase C still pass.

- **The one miss is deliberate.** "Quiz me for orgo" against "Has an organic chemistry exam…" needs synonym matching, which only the semantic signal can provide.
- **Precision is not gated.** Roughly 1 in 2 to 1 in 5 included items are topical neighbours (for example, a history-essay deadline alongside "When is my essay due?"). They stay within the 900-token retrieved budget.

## Latency

Command: `python -m backend.scripts.memory_retrieval_benchmark --out <file>`. Raw output for the 2,000-fact run is in [Phase_D_Retrieval_Benchmark_2026-10-12.json](Phase_D_Retrieval_Benchmark_2026-10-12.json). These are disposable-SQLite numbers on a development laptop.

| Corpus per learner | Warm p50 | Warm p95 | Cold p95 |
|---|---|---|---|
| 2,000 facts, 300 episodes (§8.2 stress size) | 12–13 ms | 19 ms | 75–107 ms |
| 200 facts, 40 episodes | 3.5 ms | 5.2 ms | 11.5 ms |

- **Warm:** the static ranking rows and the inverted index are cached per process. Each turn revalidates them with a version check: a primary-key read plus a count.
- **Cold:** the first turn for a learner, or the first after their facts change, reloads everything. Cold runs vary between runs on this machine.
- **How the warm number was reached.** The first, uncached implementation measured 170 ms p95. Three changes brought it down: a column-trimmed candidate query, cached tokens, and the per-owner cache with the inverted index.
- **Target:** ≤ 25 ms added p95. Met warm at the stress size, and both warm and cold at realistic sizes.
- **Not measured yet:** PostgreSQL. Run the script with `--database-url-env` pointing at an isolated `openlearn_qualification_*` database.
