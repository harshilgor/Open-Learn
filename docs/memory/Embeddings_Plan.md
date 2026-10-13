# Learner memory: embeddings plan

12 October 2026. A build plan for semantic (meaning-based) retrieval and dedupe of learner memory facts. It extends [LEARNER_MEMORY_IMPLEMENTATION.md](../LEARNER_MEMORY_IMPLEMENTATION.md) §6.3, §8.2 and §9.3 step 3. Nothing here ships until the owner approves the §13 embeddings decision.

## 1. Why, and when

Retrieval today is lexical: BM25 over shared words, plus concept and time signals. Three things fail because of that:

| Failure | Example | Who it hurts |
|---|---|---|
| Paraphrase and synonym recall | "Quiz me for orgo" doesn't find "organic chemistry exam". This is the one retrieval evaluation case that fails today. | Learners with many facts |
| Duplicate preferences | "Prefers concise explanations" and "likes short answers" share no words, so consolidation keeps both | Everyone, slowly |
| Session-summary search | "What have I struggled with?" doesn't find "missed nested functions" | Learners with many sessions |

Embeddings don't help with dates and deadlines (the time-intent parser handles them), with core-profile facts (sent every turn), or with small accounts (word matching is enough there).

**Turn-on trigger:** build now behind a flag, and enable it when the shadow report (`backend/scripts/memory_shadow_report.py`) shows the median active learner above about 100 active facts, or when the paraphrase evaluation category (§7) misses its recall gate.

## 2. Which embedding model: buy, host, or run it ourselves

Research, 12 October 2026 (vendor and blog figures; verify prices on the provider pages before E1).

| Option | Examples | Privacy | Latency per query | Cost | Fit |
|---|---|---|---|---|---|
| **Run an open model inside our backend** | EmbeddingGemma 2 (Apache 2.0, released 6 Oct 2026; 768 dims, truncatable to 512/256/128; the text path uses a ~270M core), EmbeddingGemma 1 (308M; Gemma licence), Qwen3-Embedding-0.6B (Apache 2.0), nomic-embed-text v1.5 (137M) | Fact text never leaves our servers, so the §13 privacy question mostly goes away | Short texts on CPU: an estimated tens of ms, to be measured in E1. No network call. | No per-call cost; uses about 0.5–1.5 GB of RAM per backend process, plus model download | **Recommended.** It also works on desktop (SQLite) installs. |
| Hosted open model | Cloudflare Workers AI (`@cf/google/embeddinggemma-300m`), DeepInfra or Together (BGE-M3, Qwen3), Hugging Face endpoints | Text goes to the host | 50–300 ms network call | Very low | Fallback if backend memory is too tight |
| Commercial embeddings API | OpenAI `text-embedding-3-small` (~$0.02 per 1M tokens, already wired in `semantic_retrieval.py`), Voyage 4 / 4-lite, Cohere Embed v4 | Text goes to the provider | 50–300 ms | Very low | Simplest; zero new infrastructure |
| Full memory product | Mem0 (Apache 2.0, self-hostable; hosted from $19/mo), Zep (hosted; self-host now only via Graphiti), Letta | Every learner message goes to the vendor (or a new service we run) | Network | Per plan | **Not recommended.** We already have this layer (extraction, validator, timeline, consolidation, isolation). Switching would replace tested, education-specific rules with a generic system and add a data processor. Only the embedding model is worth buying or borrowing. |

**Recommendation:** run **EmbeddingGemma 2** in-process for text, at 256 or 512 dimensions, through ONNX Runtime (for example `fastembed` or `optimum`) rather than PyTorch, to keep the install small. Keep the OpenAI path in `semantic_retrieval.py` as a configurable alternative. Gate E1 on a benchmark of the real CPU latency and RAM on the hosted instance size. If it doesn't fit, use a hosted endpoint for the same model, so stored vectors stay compatible.

What this changes in the rest of the plan:

- Local embedding takes the query-embedding network call off the chat path, so §4.3's 15 ms wait becomes a direct (bounded) call.
- The model name and dimensions are part of the vector key, so switching later re-embeds rather than mixing spaces.
- Billing (§8) becomes server CPU, not the usage ledger.

## 3. Owner decisions needed before E1

| Decision | Recommendation |
|---|---|
| Approve sending fact text (≤ 300 chars, never sensitive) and the learner's message to an embeddings provider | Not needed if we self-host (§2). If we use a hosted API: yes, with a privacy-policy line. |
| Provider and model | EmbeddingGemma 2 running in our backend (§2), so no text leaves our servers. Alternative: the existing `AI_TUTOR_EMBEDDING_MODEL` path (`text-embedding-3-small` at 512 dimensions). |
| Who pays | Same as extraction: the learner's allowance through the usage ledger. Cost is negligible (§7). |
| Memory-specific opt-out | A separate flag (`OPENLEARN_MEMORY_EMBEDDINGS`), so memory embeddings can be off while note embeddings stay on. |

## 4. Design

### 4.1 What gets embedded

- Active and tentative facts: `statement`, prefixed by the kind ("goal: Wants to pass AP Calculus BC."), because the kind is part of what a query matches.
- Active episodes: `summary` plus topic labels.
- **Never:** sensitive facts, whether or not the learner enabled them for prompts (§2 rule 6); shadow facts; archived or superseded facts (their vectors are deleted).
- `content_hash` = sha256 of the exact text sent. A changed hash means re-embed, a model change means re-embed, and vectors are keyed by `(owner, item_type, item_id, model)` as in the Phase B table.

### 4.2 Write side (background, never on the chat path)

- **After extraction:** `jobs.py`, after `write_extracted` commits in mode `on`, embeds the facts it created in one batched call. A failure (provider down, allowance exhausted) leaves the fact searchable by words only; there are no retries in the chat path.
- **Learner actions** (Phase F add, edit, confirm-to-active): embed in the same request, after the commit. Same failure rule.
- **Backfill and repair:** a `memory_embed` batch job per owner, enqueued by consolidation when an owner has eligible items with no current vector. Bounded at 200 items per run, and 32 per provider call, as `similarity_scores` does.
- **Deletes:** `delete_fact`, `delete_episode` and `forget_all` already delete `memory_embeddings` rows. Consolidation deletes vectors for facts it archives or supersedes.
- **Storage:** JSON text in `memory_embeddings.vector` (works on both dialects), at 512 dimensions about 5 KB per fact. Move to pgvector (E4) only when needed.

### 4.3 Read side (the per-turn query embedding)

This is the only latency risk. The 25 ms p95 budget can't absorb a 50–300 ms network call, so the plan is to avoid making one:

1. **Share one query vector per turn.** Notes (`automatic_note_context.py`) and materials (`context_service.py`, `material_index.py`) each embed the learner's message today. Add a per-turn memo, `semantic_retrieval.query_vector(message, model)`, keyed by `(model, sha256(message))` with a short TTL. Notes, materials and memory all read from it. Where note embeddings are on, memory adds **no** network call, and the turn makes one call instead of two or three.
2. **Start the call early, without waiting for it.** Start the query embedding in a thread when context building begins. Memory retrieval waits at most `SEMANTIC_WAIT_MS = 15`. If the vector isn't ready, the turn ranks lexically, exactly as today, and the trace records `semantic: "late"`.
3. **Skip when words are enough.** If the best BM25 score is already confident (top normalized lexical score ≥ 0.6), or the owner has fewer than `SEMANTIC_MIN_FACTS = 30` eligible facts, don't wait at all.
4. **Ranking:** turn on the reserved `semantic: 0.45` weight in `RELEVANCE_WEIGHTS` when a vector is present; otherwise renormalize over the other weights, as today. Cosine is computed over the cached per-owner vectors, loaded with the static fact cache and revalidated by the same watermark.
5. **Fail soft:** any error means lexical only, logged content-free (§2 rule 9).

### 4.4 Consolidation (dedupe)

`duplicate_pairs` adds `cosine ≥ DEDUPE_COSINE (0.92)` for same kind and scope, alongside the lexical checks. Existing guards stay: sensitive and non-sensitive facts never merge, and different `event_date`s never merge. Merges above 0.92 that aren't lexical matches are logged with a new `mergedSemantic` count, so the change log and the evaluation can measure false merges.

### 4.5 Scale path (E4, only if needed)

- Under about 5,000 facts per owner: an in-process cosine over cached vectors. 2,000 × 512 dims is about 1M multiply-adds: well under a millisecond with numpy, but likely tens of milliseconds in pure Python (the current `_cosine`). numpy isn't a backend dependency today, so E2 either adds it or scores only the top ~200 lexical and recent candidates. Measure both.
- Above that, or if the per-process cache uses too much memory: pgvector on PostgreSQL (a `vector(512)` column, an HNSW index, and a `ORDER BY embedding <=> :q LIMIT 50` prefilter). SQLite (desktop) keeps the in-process path.

## 5. Build steps

| Step | Scope | Size |
|---|---|---|
| **E1** Write side | Flag `OPENLEARN_MEMORY_EMBEDDINGS` (off/on). `learner_memory/embeddings.py`: eligible text, hashing, batched embed via `semantic_retrieval._embed` (ledger-billed), upsert and delete. Hooks in the extraction job and the Phase F write routes. The `memory_embed` backfill job, plus deletion in consolidation. Tests: sensitive is never embedded; delete, forget-all and erasure remove vectors; owner isolation; a provider failure leaves the fact intact. | 1 day |
| **E2** Read side | Shared per-turn query-vector memo, used by notes, materials and memory. Early start, 15 ms wait, and the confident-lexical skip. Semantic weight in `retrieval.rank`. Vectors in the per-process cache. The `semantic` trace field. Tests: frozen fake vectors give the expected top-k; a late vector falls back to lexical; no extra provider call when notes already embedded the message. | 1 day |
| **E3** Dedupe and evaluation | The cosine dedupe in consolidation. Evaluation: a `paraphrase` category (≥ 15 cases with recorded vectors, so CI stays offline) and a `semantic_dedupe` category (true and false pairs). Latency benchmark with vectors on PostgreSQL. | 0.5–1 day |
| **E4** pgvector | Only if the trigger in §3.5 fires. | 1 day |

## 6. Flags and rollout

| Flag | Values | Default |
|---|---|---|
| `OPENLEARN_MEMORY_EMBEDDINGS` | off / on | off |
| `AI_TUTOR_EMBEDDING_MODEL` | model id (existing) | unset |

Both must be set for anything to be embedded. Rollout:

1. Write side on, read side off (vectors are written and backfilled, nothing reads them). Watch cost and backfill progress.
2. Read side on for internal accounts. Compare the evaluation results and the `semantic` trace counts (used, late, skipped).
3. Read side on for everyone.
4. Cosine dedupe on, after the false-merge rate in the evaluation is 0.

Rollback is flag-only: with the flag off, vectors are ignored and ranking is lexical.

## 7. Evaluation gates

- Paraphrase recall@5 ≥ 0.8 (today: the "orgo" case fails).
- Existing categories don't regress: recall@5 ≥ 0.8 on categories 1–3, abstention ≥ 0.95, assessment isolation 1.0.
- Semantic dedupe: false merges = 0 on the labeled set.
- Latency: `generation_context` added p95 ≤ 25 ms on PostgreSQL with 2,000 facts and vectors cached; the embedding call itself is off the critical path by design (§4.3).

## 8. Cost

At current small-embedding-model prices (verify before E1), facts under 300 characters cost cents per 10,000. The per-turn query embedding is the main volume: one call per chat turn, already paid when note embeddings are on, and shared after E2. Backfill for an owner with 2,000 facts is about 63 batched calls, once.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Fact text leaves for the provider | Owner approval, a privacy-policy line, sensitive facts never sent, a memory-specific flag |
| Wrong semantic merges lose a fact | Supersede, never delete; history is kept; the evaluation gates false merges at 0; `mergedSemantic` count in the change log |
| Provider latency spikes | The chat path never waits more than 15 ms; lexical fallback |
| Vector drift after a model change | Model is part of the primary key; the backfill job re-embeds |
| Memory use of cached vectors | 512 dims; LRU of 64 owners already bounds the cache; pgvector if needed |
