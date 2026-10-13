# Learner memory: embeddings plan (self-hosted EmbeddingGemma 2)

13 October 2026. **Decided:** Open Learn hosts its own embedding model, EmbeddingGemma 2, on its own servers. No learner text goes to an outside embeddings provider. This plan covers how it's built and where it fits. It extends [LEARNER_MEMORY_IMPLEMENTATION.md](../LEARNER_MEMORY_IMPLEMENTATION.md) §6.3, §8.2 and §9.3 step 3, and replaces the §13 "embeddings" open question.

## 1. Why embeddings

Retrieval today is lexical: BM25 over shared words, plus concept and time signals. Three things fail because of that:

| Failure | Example |
|---|---|
| Paraphrases and synonyms | "Quiz me for orgo" doesn't find "organic chemistry exam". This is the one retrieval evaluation case that fails today. |
| Duplicate preferences | "Prefers concise explanations" and "likes short answers" share no words, so consolidation keeps both |
| Session-summary search | "What have I struggled with?" doesn't find "missed nested functions" |

Embeddings turn text into a list of numbers (a vector) so that texts with similar meaning get similar vectors. Comparing two vectors (cosine similarity) measures how close their meanings are, whatever words they use.

Embeddings don't help with dates (the time-intent parser handles those), with core-profile facts (sent every turn), or with small accounts.

## 2. The model

| | EmbeddingGemma 2 |
|---|---|
| Release | 6 Oct 2026, Google DeepMind, **Apache 2.0** |
| Checkpoint | `google/embeddinggemma-2` (pin a revision hash) |
| What we load | **Text-only**: a ~270M-parameter core. The vision (+170M) and audio (+300M) encoders are skipped with `config_kwargs={"vision_config": None, "audio_config": None}`. All configurations share one vector space, so image or audio embeddings can be added later without re-embedding text. |
| Dimensions | 768 native; **we use 256** (Matryoshka truncation, `truncate_dim=256`, `normalize_embeddings=True`). Google reports 256d keeps most of the full quality on text. Each vector is 1 KB as float32. |
| Context | 8,192 tokens (facts are ≤ 300 characters) |
| Prompts | Queries use `prompt_name="SearchQuery"`; facts and episodes use `prompt_name="Document"`. Both sides must use the same prompts and dimensions. |
| Runtime | sentence-transformers ≥ 6.1 with CPU-only PyTorch, float32 (most server CPUs lack fast bfloat16). Estimated weights about 1.1 GB, plus framework overhead. Ollama's build of this model needs MLX, which isn't available on Linux CPU servers, so we don't use Ollama. |

Not measured yet: real CPU latency and memory on our instance size. Step E0 (§6) measures them before anything else is built.

## 3. Where it runs: a private embedding service

```
                       Render private network (not reachable from the internet)
 ┌──────────────────────┐   POST /v1/embeddings    ┌───────────────────────────────┐
 │ openlearn-api        │ ───────────────────────▶ │ openlearn-embeddings (new)    │
 │  chat turn: embed the│   (query, ~1 call/turn)  │  FastAPI + sentence-          │
 │  learner's message   │                          │  transformers, text-only      │
 └──────────────────────┘                          │  EmbeddingGemma 2, 256d       │
 ┌──────────────────────┐   POST /v1/embeddings    │  weights baked into the image │
 │ openlearn-learning   │ ───────────────────────▶ │  no database, no learner data │
 │  memory_extract job, │   (facts, batched)       │  stored, no text logged       │
 │  memory_embed backfill│                         └───────────────────────────────┘
 └──────────────────────┘
          │ vectors
          ▼
   PostgreSQL memory_embeddings (owner-scoped; deleted with the fact)
```

**Why a separate service rather than loading the model in the API process:**

- **Memory:** the API is one uvicorn process on a Standard instance (2 GB). The learning worker, which runs memory jobs, is on Starter (512 MB). The model can't fit on Starter, and on the API it would compete with chat traffic. A separate service holds one copy for both callers.
- **Image size and isolation:** PyTorch and the weights stay out of the main backend image, so a model crash or memory spike can't take down chat.
- **Scaling:** the embedding service can be resized (Standard 2 GB / 1 CPU, or Pro 4 GB / 2 CPU) without touching anything else.

**Service contract** (`backend/embedding_service/`, its own Dockerfile and requirements):

- `POST /v1/embeddings` with an OpenAI-compatible body: `{"model": "...", "input": [...], "task": "query" | "document"}`. Responses are float vectors, normalized, 256d. Because it's OpenAI-compatible, `semantic_retrieval.py`'s HTTP client can call it with a different base URL.
- `GET /health` reports the model revision and dimensions, and only goes ready after the model is loaded and has done a warm-up embed.
- Auth: a shared secret header (`OPENLEARN_EMBEDDING_TOKEN`), plus the private network.
- Limits: at most 64 inputs per request and 2,000 characters per input; requests over the limit are rejected (400).
- It logs counts and timings only, never text.
- Weights are downloaded at image build time and pinned to a revision, so it never downloads at runtime and has no dependency on Hugging Face at startup.

**Desktop and local installs** (SQLite, no Render): embeddings are off by default and retrieval stays lexical, as today. Optional later: the same service run as a local sidecar process, or a llama.cpp/GGUF build, so the PyTorch dependency stays out of the desktop installer.

## 4. How it fits the memory architecture

### 4.1 Configuration

| Setting | Meaning | Default |
|---|---|---|
| `OPENLEARN_MEMORY_EMBEDDINGS` | `off` / `write` (vectors written, not read) / `on` | `off` |
| `OPENLEARN_EMBEDDING_URL` | Base URL of the private service, e.g. `http://openlearn-embeddings:10000` | unset (off) |
| `OPENLEARN_EMBEDDING_MODEL` | Model key stored with each vector, e.g. `embeddinggemma-2@<rev>/256` | — |
| `OPENLEARN_EMBEDDING_TOKEN` | Shared secret | — |

All are read through `learner_memory/policy.py`. The existing `AI_TUTOR_EMBEDDING_MODEL` (OpenAI, used for notes and materials) is unchanged.

### 4.2 New code

| Module | Responsibility |
|---|---|
| `backend/embedding_service/app.py` | The service in §3 |
| `learner_memory/embeddings.py` | The client (HTTP with a short timeout and a circuit breaker: after 3 failures, skip for 30 s). Builds the text to embed (`kind: statement`; episodes: `summary + topics`). Hashing, vector packing (float32 → base64), and upsert or delete of `memory_embeddings` rows. |
| `retrieval.py` | Adds the semantic score to `rank()` |
| `consolidation.py` | Adds cosine dedupe |
| `jobs.py` | Embeds after extraction; the `memory_embed` backfill job |

### 4.3 What gets embedded

- Active and tentative facts, and active episodes.
- **Never** sensitive facts, even when the learner enabled them for prompts (§2 rule 6). They stay lexical-only. Never shadow facts.
- Archived and superseded facts: their vectors are deleted.
- `content_hash` = sha256 of the exact input text. `model` is part of the primary key, so changing the model or dimensions re-embeds rather than mixing two vector spaces.

### 4.4 Write path (background only)

1. **After extraction:** the `memory_extract` job (learning worker) commits facts, then embeds the new ones in one batched call and upserts vectors in a second short transaction. A failure leaves the fact without a vector; it's still searchable by words, and backfill retries it.
2. **Learner actions** (Phase F add, edit, or confirm-to-active): the route enqueues a `memory_embed` job for that fact (no call on the request path).
3. **Backfill:** consolidation enqueues `memory_embed` for owners with eligible items that have no current vector, at most 200 items per run and 64 per call. This also covers first rollout and model changes.
4. **Deletes:** existing code already deletes vectors with the fact, episode, forget-all and account erasure. Consolidation deletes vectors for facts it archives or supersedes.

### 4.5 Read path (per chat turn)

1. When context building starts, the API sends the learner's message to the service (`task: query`) **in a background thread**, so it runs alongside sources, notes and course context.
2. Memory retrieval waits for it at most **`SEMANTIC_WAIT_MS = 40`** (to be tuned after E0). If the vector isn't back, the turn ranks lexically, as today, and the trace records `semantic: "late"`.
3. It skips waiting when the owner has fewer than 30 eligible facts, or when the lexical match is already confident (top score ≥ 0.6).
4. Vectors load with the per-process static fact cache, revalidated by the same version watermark, so there's no extra database round trip per turn.
5. Cosine scoring uses **numpy** (new API dependency, small) over the in-scope candidates. 2,000 × 256 is about 0.5M multiply-adds: well under 1 ms with numpy, versus tens of ms in pure Python.
6. `RELEVANCE_WEIGHTS["semantic"] = 0.45` turns on when a vector is present; otherwise the weights renormalize as today.
7. Any failure means lexical only, logged without content (§2 rule 9).

**Latency effect:** the embedding call overlaps other context work, and the wait is capped. The worst case adds `SEMANTIC_WAIT_MS` to the memory stage, which is why E0 must confirm typical query latency well under that. The 25 ms memory read budget (database plus ranking) is unchanged.

### 4.6 Consolidation

`duplicate_pairs` adds cosine ≥ `DEDUPE_COSINE` (0.92) for the same kind and scope. Existing guards stay: sensitive facts never merge, different `event_date`s never merge, and merges supersede rather than delete. Semantic-only merges are counted separately (`mergedSemantic`) so false merges can be measured.

### 4.7 Storage and scale

- `memory_embeddings.vector` holds base64 float32, 256 dims (about 1.4 KB as text), on both dialects. 2,000 facts per owner is about 3 MB per owner in the cache, and the LRU of 64 owners bounds it.
- pgvector (E4): only if owners pass about 5,000 facts, or the cache grows too large. A `vector(256)` column, an HNSW index, and a prefilter of the top 200 by vector distance. SQLite keeps the in-process path.

### 4.8 Notes and materials (optional, later)

Notes and materials embed with OpenAI today when `AI_TUTOR_EMBEDDING_MODEL` is set. Once the service is proven, point them at it too. That removes the last external embedding call, gives one shared query vector per turn, and needs no migration, because their caches are keyed by model.

## 5. Privacy, cost, operations

- **Privacy:** text stays on our infrastructure. No new data processor and no privacy-policy change for embeddings. Sensitive facts are still never embedded.
- **Cost:** one more private service, about $25/month on Standard or $85 on Pro if E0 shows it's needed. No per-call fees and no usage-ledger entries. Embeddings aren't billed to learner allowances.
- **Operations:** health checks, a deploy that waits until the model is loaded, and performance stages `memory_embed_query` (API) and `memory_embed_job` (worker). The release topology (`deploy/production-topology.json`, `render-paid.yaml`) gains the service. It holds no database or Redis connections, so the connection budget is unchanged.

## 6. Build steps

| Step | Scope | Gate | Size |
|---|---|---|---|
| **E0** Service and benchmark | `backend/embedding_service` (FastAPI, text-only model, 256d, health, auth, limits), Dockerfile with baked weights, a benchmark script. Deploy to a Render private service on Standard. | Single short query: p50 and p95 latency; batch of 64: throughput; resident memory. Go if p95 ≤ 40 ms and memory ≤ 1.6 GB on Standard, otherwise try Pro. | 0.5–1 day |
| **E1** Write side | `embeddings.py` client and storage; the extraction hook; `memory_embed` job and backfill; vector deletes in consolidation. Flag mode `write`. | Tests: sensitive never embedded; deletes, forget-all and erasure remove vectors; owner isolation; service down leaves facts intact. | 1 day |
| **E2** Read side | Query embedding in a background thread with a bounded wait; vectors in the cache; numpy cosine; semantic weight; `semantic` trace field. Flag mode `on`. | Paraphrase recall@5 ≥ 0.8; no regression in other categories; PostgreSQL p95 of the memory stage unchanged with the service slow or down. | 1 day |
| **E3** Dedupe and evaluation | Cosine dedupe; evaluation categories `paraphrase` (≥ 15 cases) and `semantic_dedupe`. CI uses recorded vectors (fixtures), so it stays offline. | False merges = 0 | 0.5–1 day |
| **E4** Optional | pgvector; move notes and materials onto the service | Only if needed (§4.7, §4.8) | 1 day each |

## 7. Rollout

1. E0 deployed; nothing calls it yet. Run the benchmark.
2. `OPENLEARN_MEMORY_EMBEDDINGS=write`: vectors are written and backfilled, nothing reads them. Watch service CPU, memory and backfill progress.
3. `on` for internal accounts. Compare the evaluation and the `semantic` trace counts (used, late, skipped).
4. `on` for everyone, then cosine dedupe once the false-merge rate is 0.

Rollback is flag-only: with `off`, vectors are ignored and ranking is lexical.

## 8. Risks

| Risk | Mitigation |
|---|---|
| CPU latency too high on Standard | E0 gate; Pro instance; 128d truncation; the wait is capped, so chat never blocks |
| Service down or redeploying | Circuit breaker, lexical fallback, health-gated deploys |
| Wrong semantic merges | Supersede, never delete; the evaluation gates false merges at 0 |
| Model change | Model key in the primary key; backfill re-embeds |
| Memory of cached vectors | 256d; the LRU of 64 owners; pgvector if needed |
| Pickled or untrusted weights | Load safetensors only, from a pinned revision, at build time |

## 9. Alternatives considered

- **Commercial API** (OpenAI `text-embedding-3-small`, Voyage, Cohere): the simplest option, but learner text leaves our servers on every turn, with a network round trip.
- **Hosted open model** (Cloudflare Workers AI runs EmbeddingGemma 1, DeepInfra): same privacy trade-off.
- **A full memory product** (Mem0, Zep, Letta, Cognee, Supermemory): these replace the whole memory layer, not just embeddings. We already have that layer, with education-specific rules (learner-only provenance, assessment isolation, add-only timeline). See the comparison in the PR discussion; not adopted.
