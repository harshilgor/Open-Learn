# Learner memory: rollout runbook

13 October 2026. How to turn learner memory on in hosted, step by step (spec §12). Every step is flag-only and reversible, and data stays valid when a flag is turned off. Do one step at a time, and only move on when its checks pass.

## Flags

| Flag | Values | Default | What it does |
|---|---|---|---|
| `OPENLEARN_MEMORY_CHAT_CONTEXT` | on / off | off | Puts the learner memory block in chat prompts |
| `OPENLEARN_MEMORY_SKIP_UNUSED_COMPILE` | on / off | off | Skips the compile that chat turns never used |
| `OPENLEARN_MEMORY_EXTRACTION` | off / shadow / on | off | Learns facts from chats. `shadow` stores them hidden, for review only. |
| `OPENLEARN_MEMORY_EXTRACTION_MODEL` | model id | unset | Must be set for extraction to run (`anthropic/claude-haiku-5.5`) |
| `OPENLEARN_MEMORY_RETRIEVAL_V2` | on / off | off | Ranked, time-aware retrieval (needs chat context on) |
| `OPENLEARN_MEMORY_CONSOLIDATION` | on / off | off | Daily forgetting and merging, session summaries, core profile |

Set them on every service that runs the code: `openlearn-api-*` (chat path) and `openlearn-learning` (memory jobs). Templates: `deploy/hosted.env.example`, `backend/.env.example`.

The Settings → Memory page, the write APIs and forget-all work with every flag off; they only manage what's stored.

## Before step 1 (once)

- The release migration job has applied `0088_memory_sensitive_enable`. Check: `python -m backend.scripts.check_release_contract` shows exactly one head.
- CI is green, including "Learner memory evaluation gates".

## Step 1: memory in chat (no learning yet)

Set `OPENLEARN_MEMORY_CHAT_CONTEXT=on` and `OPENLEARN_MEMORY_SKIP_UNUSED_COMPILE=on` on the API.

Check after a day:
- The `generation_context` p95 in performance logs hasn't risen; the `memory_retrieve` stage p95 is ≤ 25 ms.
- A saved preference (Settings → Memory → Add a memory) shows up in the tutor's behaviour.

Rollback: set both to `off`.

## Step 2: shadow extraction (at least 2 weeks)

Set `OPENLEARN_MEMORY_EXTRACTION=shadow` and `OPENLEARN_MEMORY_EXTRACTION_MODEL=anthropic/claude-haiku-5.5` on the API and the learning worker. Learners see nothing: shadow facts are hidden and deleted after 30 days.

Review weekly, in aggregate only:

```
DATABASE_URL=... python -m backend.scripts.memory_shadow_report --days 14 --out shadow-week-N.json
```

The report gives counts only: proposed vs. accepted, validator rejection reasons, skips, and facts per kind. It never contains fact text or learner IDs, and it withholds per-kind counts below 20 learners. Don't read individual learners' shadow facts. Spot-checks use internal test accounts, or learners who have agreed.

What to look for:
- Acceptance rate is stable, and no single rejection reason dominates unexpectedly. Lots of `quote_not_learner_text` would mean the model paraphrases instead of quoting.
- `sensitive_inferred` rejections exist, which shows the filter works, but they're rare.
- Daily extraction calls per learner stay well under the cap (150), and model spend matches expectations in the usage ledger.

Rollback: `OPENLEARN_MEMORY_EXTRACTION=off`. Shadow rows purge themselves after 30 days.

## Step 3: extraction on

Gate: the evaluation gates pass (`python -m backend.app.evaluation_runner --memory`: extraction precision ≥ 0.9, false-memory rate 0, abstention ≥ 0.95), and the shadow review raised nothing.

Set `OPENLEARN_MEMORY_EXTRACTION=on`. Learners now see the "Saved to memory" chip and the one-time notice, and can review everything in Settings → Memory.

Check after a week: the share of facts forgotten (deleted) by learners. A high rate means extraction saves the wrong things; go back to shadow and tune the prompt.

Rollback: `shadow` or `off`. Facts already saved stay visible and editable.

## Step 4: retrieval v2

Set `OPENLEARN_MEMORY_RETRIEVAL_V2=on` on the API.

Check: `memory_retrieve` p95 ≤ 25 ms in hosted (local PostgreSQL measured 20.8 ms with consolidation on, 26 ms with it off). The dev context inspector's `memoryTrace` shows sensible inclusions.

Rollback: `off`; chat falls back to the Phase A block.

## Step 5: consolidation

Set `OPENLEARN_MEMORY_CONSOLIDATION=on` on the API and the learning worker. The worker queues each learner who was active recently, at most once a day and 50 learners a minute.

Check:
- `memory_consolidate_job` durations (local: 0.76 s for 2,000 facts on SQLite).
- Settings → Memory → "Recently updated" shows content-free summaries.
- "Needs your review" appears only for real conflicts.

Rollback: `off`. Chat goes back to the Phase D profile section; the stored profile is ignored.

## Owner decisions still open

- Learners under 13 or 18 (spec §13): none of these steps change it.
- Shadow review: who reviews the aggregate reports, and for how long. Recommendation: the project owner, for 2 weeks minimum.
- Embeddings: decided (self-hosted EmbeddingGemma 2), built separately; see [Embeddings_Plan.md](Embeddings_Plan.md).
