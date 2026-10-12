# Redis cache-aside implementation

Handoff specification, 11 October 2026. Written for a coding agent working in this repository. Read the whole document before writing code. Verify every file and line reference against the current checkout; references were correct when this was written but the code moves.

## 1. Summary

Add Redis as an **optional, disposable read cache** in front of PostgreSQL using the cache-aside pattern. PostgreSQL stays the only source of truth. Every code path must produce correct results with Redis absent, slow, empty, or failing.

```
read:   generation = GET gen key ──▶ GET data key ──hit──▶ return
                                         └─miss─▶ load from DB ─▶ SET data key (TTL ± jitter) ─▶ return
write:  DB transaction commits ─▶ INCR gen key(s)   (after commit, never inside the transaction)
```

This follows the existing architecture decisions:

- [Scalable architecture review](Open_Learn_Scalable_Architecture_Review.md): Redis is conditional; durable SQL stays authoritative.
- [Performance plan A04](Open_Learn_Performance_Implementation_Plan.md): current context and read-your-writes stay on the primary.
- [Usage allowance](UNIFIED_USAGE_ALLOWANCE_IMPLEMENTATION.md): Redis is never the balance store.

**Expectation setting:** this reduces database round trips, connection-pool pressure, and latency for repeated/polled reads. It does **not** address model time-to-first-token. Provider prompt caching (request ordering in `model_provider.py`) is separate work and out of scope here (see §12).

## 2. Hard rules (do not violate)

1. **PostgreSQL is authoritative.** Redis holds only copies that can be rebuilt. Never write data only to Redis.
2. **Fail open.** Any Redis error, timeout, or decode failure is treated as a cache miss (read) or ignored (write/invalidate), then the request continues against the database. A Redis outage must never produce a 5xx.
3. **Never cache:**
   - `/v1/usage/allowance` or anything the usage ledger uses for admission, holds, or settlement.
   - Identity, session, device revocation, or `assert_principal_active` results (`identity.py:95`).
   - Current branch context, conversation state used for generation, workspace/study note bodies, note revisions, transcripts. (Exception: §8 Phase 4, only after its gate passes.)
   - Anything authorization depends on. Ownership/authorization checks run uncached, on every request, before a cache read.
4. **Invalidate after commit only.** Never invalidate or populate inside an open transaction. A rolled-back transaction must not invalidate.
5. **Owner isolation.** Every key for user data contains the (hashed) owner. A cache entry for owner A must be unreachable from owner B's request, even when IDs collide.
6. **Local/desktop unchanged.** SQLite installs, `start-local.ps1`, `install-local.ps1`, the desktop PyInstaller build (`backend/forma-api.spec`), and the test suite must work with no Redis installed or configured. Import `redis` lazily.
7. **No raw content or identifiers in logs/metrics.** Follow the existing content-free conventions in `performance.py`.

## 3. Current state (verified at time of writing)

- FastAPI modular monolith; routes are mostly sync `def` (run in the thread pool). App wiring: `backend/app/main.py`.
- Persistence: `backend/app/storage.py` `Store.transaction()` (line ~40) wraps `engine.begin()` and runs lease and principal checks. Engines: `backend/app/database.py`. Process connection budgets: `backend/app/capacity.py`, `deploy/connection-budget.json`.
- Hosted: Render (Virginia), roles `api`, `generation`, `learning`, `agent`, `class`, `browser`, `notifications`, `cron`, all sharing the `openlearn-production` env group (`deploy/render-paid.yaml`, `deploy/render.yaml`).
- Existing ad-hoc cache: web evidence results stored in Postgres `context_records` with `kind='web_evidence_cache'` (`backend/app/web_evidence/store.py:382-440`, used from `web_evidence/service.py:636-650`, cleaned by `web_evidence/retention.py`).
- Diagnostics: `backend/app/performance.py` (`STAGES`, `TimingRegistry`, `observe`, `span`, structured `openlearn.performance` logger).

## 4. Architecture

### 4.1 New module: `backend/app/cache.py`

Public surface (names may be adjusted to match code style, behavior may not):

```python
class Cache(Protocol):
    enabled: bool
    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes, ttl_seconds: int) -> None: ...
    def delete(self, *keys: str) -> None: ...
    def generation(self, namespace: str, scope: str) -> int | None: ...   # None = unavailable → bypass
    def bump(self, namespace: str, scope: str) -> None: ...                # INCR + EXPIRE on gen key
    def erase_scope(self, scope: str) -> None: ...                         # SCAN/UNLINK, for account erasure

class NullCache:  # default; enabled=False; every method is a no-op / returns None
class RedisCache: # wraps redis.Redis with a bounded ConnectionPool

def get_cache() -> Cache                       # process singleton; NullCache unless configured
def owner_scope(owner_id: str) -> str          # sha256(owner_id)[:24]; never put raw owner IDs in keys

def get_or_load(namespace: str, scope: str, parts: Mapping[str, Any], loader: Callable[[], T], *,
                ttl_seconds: int, encode: Callable[[T], bytes], decode: Callable[[bytes], T]) -> T

def invalidate(namespace: str, scope: str) -> None   # defers to after-commit if a Store.transaction is active
```

**Key format:**

```
data:  ol:c{CACHE_SCHEMA}:{namespace}:{scope}:g{generation}:{sha256(canonical_json(parts))[:32]}
gen:   ol:gen:{namespace}:{scope}
```

- `CACHE_SCHEMA` is an integer constant in `cache.py`. Bump it whenever any cached payload shape changes, so overlapping deploys never decode each other's entries.
- `canonical_json` uses sorted keys and no whitespace. `parts` never contains secrets.
- Generation keys get a long TTL (e.g. 7 days), refreshed on bump, so they don't accumulate forever. A missing generation key reads as `0`.

**`get_or_load` algorithm (order matters for correctness):**

1. If the cache is disabled, the namespace isn't enabled (see §5), or the circuit breaker is open: `return loader()`.
2. `gen = cache.generation(namespace, scope)`. If `None` (Redis error): `return loader()`. **Read the generation before loading from the DB.**
3. `raw = cache.get(key(gen))`. On a hit, `decode(raw)`. If decode raises: delete the key, count `decode_error`, fall through to a miss.
4. On a miss: `value = loader()`, then `cache.set(key(gen), encode(value), jittered(ttl_seconds))`. Errors on set are swallowed and counted.
5. Return `value`.

Why this is race-safe: a reader that captured generation *g* before a writer committed and bumped to *g+1* can only write its (possibly stale) value under the *g* key, which no future reader requests. Do not "optimize" by reading the generation after the load.

**Jitter:** `ttl * uniform(0.9, 1.1)`, minimum 1 second.

**Circuit breaker (per process):** after 5 consecutive Redis errors, bypass Redis for 30 seconds, then allow one probe. This prevents adding a timeout to every request during an outage. Count breaker state changes.

**Client settings:** `redis.Redis(connection_pool=ConnectionPool.from_url(REDIS_URL, max_connections=<role budget>, socket_connect_timeout=0.2, socket_timeout=0.1, health_check_interval=30))`. Do not use `decode_responses=True` (values are bytes). No retries inside the request path.

**Single-flight (only where marked in §8):** before loading, `SET ol:lock:{key} 1 NX PX 5000`. If not acquired, poll `GET key` up to ~3 × 50 ms, then load from the DB anyway. Never block longer than that.

### 4.2 After-commit invalidation in `Store.transaction()`

Add a context-local pending-invalidation list to `backend/app/storage.py`:

- The outermost `Store.transaction()` creates the list (`contextvars.ContextVar`). Nested or reentrant use must append to the outer list rather than flushing early.
- `cache.invalidate(namespace, scope)` appends to the active list if one exists, otherwise bumps immediately (for writes made via `engine.begin()` / autocommit outside `Store.transaction`, call `invalidate` **after** the `with` block exits).
- Flush (bump all, deduplicated) only after `engine.begin()` exits without an exception. Discard the list on exception.
- Flushing must never raise into the caller.
- Some services take an optional `connection` and use `nullcontext(connection)`. Their invalidations land in whichever outer transaction owns the connection. Verify this with a test (§9).

### 4.3 Encoding

- Pydantic models: `TypeAdapter(T).dump_json(value)` / `TypeAdapter(T).validate_json(raw)`, including for `list[Model]`.
- Plain dict/list results: `json.dumps(value, separators=(',', ':'), default=str).encode()`. If a value contains datetimes, prefer converting the route to a Pydantic model or ensure the existing response serialization of the decoded value is identical (test it: §9 "response parity").

### 4.4 Account erasure and privacy

- Find the account deletion / privacy erasure path (`privacy_routes.py`, `identity_revocation.py`, `backup_service.py`; verify). After its transaction commits, call `cache.erase_scope(owner_scope(owner))`. This uses `SCAN MATCH ol:*:*:{scope}:*` + `UNLINK`, plus deletion of that scope's generation keys.
- On material deletion, invalidate that material's namespaces (see §8).

## 5. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `REDIS_URL` | unset | `redis://` or `rediss://` URL. Unset → `NullCache`. |
| `OPENLEARN_CACHE_ENABLED` | `false` | Master switch. Must be `true` and `REDIS_URL` set to use Redis. |
| `OPENLEARN_CACHE_NAMESPACES` | empty | Comma-separated allowlist, e.g. `web_evidence,material_blocks`. Unlisted namespaces bypass reads **but still bump generations on writes** so they're safe to enable later. |
| `OPENLEARN_CACHE_SHADOW` | empty | Comma-separated namespaces in shadow mode (see §10). |
| `OPENLEARN_REDIS_POOL_SIZE` | role default | Per-process max Redis connections. |

Rules:

- **Invalidation must be on wherever writes happen.** Any process that writes data belonging to a cached namespace (workers included, e.g. material processing in the `learning` role) must have `REDIS_URL` set, or caches go stale until TTL. Put `REDIS_URL` in the shared `openlearn-production` env group, not on individual services.
- If `OPENLEARN_CACHE_ENABLED=true` and `REDIS_URL` is unset, log a single warning and use `NullCache`. Don't crash.
- Production validation (`release.py` / `readiness.py` / release preflight, whichever owns config checks; verify) should flag the hosted config as invalid if any role that writes cached data lacks `REDIS_URL` while the API has caching enabled.
- `/live` and `/ready` must **not** fail when Redis is down. Report the cache as `degraded` in readiness diagnostics only.
- Add the variables (commented) to `deploy/hosted.env.example` and `backend/.env.example`.

## 6. Infrastructure

- **Hosted:** Render Key Value (Valkey/Redis-compatible) in `virginia`, same region as the API, internal network only (empty `ipAllowList`), `maxmemoryPolicy: allkeys-lru`. Add it to `deploy/render-paid.yaml` and `deploy/render.yaml` and wire `REDIS_URL` via `fromService` → `connectionString`. **Check the current Render Blueprint spec for the exact `type`/field names before editing; don't guess.** Don't provision paid resources. Leave `autoDeployTrigger`/plan choices for the owner to approve.
- **Connection budget:** add a `redis` section to `deploy/connection-budget.json` (provider connection limit, per-role pool sizes, overlap factor 2). Add role defaults in `capacity.py` next to `ROLE_POOLS`. Extend the existing budget test (in `backend/tests/test_release_gates.py` or wherever `connection-budget.json` is validated) so the total across roles × replicas × overlap stays within the provider limit.
- **Local load testing:** add an optional `redis` service to `deploy/compose-performance.yaml`. Don't touch the local start/install scripts.
- **Dependencies:** add `redis` (redis-py, current 5.x/6.x line; check the latest stable) to `backend/requirements.txt`, and `fakeredis` to the test dependencies. Import both lazily. Confirm the PyInstaller desktop build still succeeds and doesn't require Redis at runtime.

## 7. Observability

In `backend/app/performance.py`:

- Add stages `cache_get` and `cache_load` to `STAGES`, labelled by namespace as the `resource`.
- Add bounded counters per namespace: `hit`, `miss`, `error`, `decode_error`, `bypass`, `set_error`, `invalidate`, `invalidate_error`, `shadow_mismatch`, plus breaker `open`/`close` events.
- Expose them in the existing protected operational snapshot alongside the query and timing registries.
- Content-free: namespace names and counts only; no keys, owner scopes, or payloads.

## 8. Work plan

Do one phase per PR. Each phase must pass the full existing test suite, the new tests in §9, and its own acceptance criteria before the next starts.

### Phase 0: Foundation (no behavior change)

- `backend/app/cache.py` (§4.1), the after-commit hook (§4.2), config (§5), metrics (§7), `erase_scope` wired into account erasure (§4.4).
- Default everywhere is `NullCache`.
- **Acceptance:** full suite passes with no Redis; foundation unit tests (§9) pass against `fakeredis`; desktop build unaffected.

### Phase 1: Low-risk namespaces

**1a. `web_evidence`: move the existing SQL cache to Redis.**

- In `web_evidence/store.py`, when the namespace is enabled, `get_cache`/`put_cache` use Redis with the existing `ttl_seconds`. Keep the payload's `tenantId` + `fingerprint` checks exactly as they are. Scope = hashed tenant/owner.
- When disabled, keep the existing SQL path unchanged (local/desktop).
- Use single-flight (§4.1) for the external search call in `web_evidence/service.py:636-650`; it's expensive and billed.
- Leave `web_evidence/retention.py` working for any SQL rows that remain.
- **Acceptance:** identical results to the SQL path in existing `test_web_evidence*.py`. With Redis enabled, no `context_records` writes for `web_evidence_cache`.

**1b. `material_blocks`: material version blocks.**

- Route `GET /v1/material-versions/{vid}/blocks` → `MaterialService.blocks` (`material_service.py:696`).
- Keep `self.version(owner, vid)` **uncached and first**. It's the ownership/deleted check and must 404 immediately after deletion. Cache only the block rows query result.
- Scope: `vid` (the ownership check already ran). Namespace generation per version.
- Blocks are **not** immutable. They're rewritten on reprocessing/OCR. Bump `material_blocks` for that version after every write to `material_blocks`. Known writers: `material_service.py:968`, `material_service.py:1036`, `material_index.py:320`. Re-grep: `grep -rnE "(INSERT INTO|UPDATE|DELETE FROM) material_blocks" backend/app`.
- Only populate the cache when the version status is `ready` (not `processing`/`partially_ready`).
- TTL: 24 h. Optionally apply the same pattern to `GET /v1/material-versions/{vid}/index-pages` (`material_routes.py:31`) and `GET /v1/source-spans/{span_id}`, but only after enumerating their writers the same way.
- **Acceptance:** reprocessing a version returns new blocks on the next read; deleting the material returns 404 immediately.

### Phase 2: Mutable dashboard reads (ship in shadow mode first, §10)

**2a. `concept_graph`: self-versioning.**

- `StableConceptService.graph` (`stable_concept_service.py:80`). Keep `assert_owner_active` and the `SELECT revision FROM concept_graph_revisions` query uncached. Cache the assembled graph keyed by `(owner_scope, revision)`. Historical revisions are immutable; the current graph changes only when the revision changes.
- **Precondition you must verify:** every write to the tables in `TABLES` (`stable_concept_service.py:21`) bumps `concept_graph_revisions`. Grep for writers of each table across `backend/app`. Any writer that doesn't bump the revision (e.g. projections/legacy mappings written elsewhere) must call `invalidate('concept_graph', owner_scope)` after commit, and you must then also include the generation in the key.
- TTL: 1 h.

**2b. `course`: course list, course detail, roadmap.**

- `CourseService.list_courses` (`course_service.py:264`) and `get_course` (`:160`). Note `list_courses` is N+1: it calls `get_course` per course, and each runs ~6 queries.
- `get_course` summaries depend on `courses`, `course_roadmap_nodes`, `learning_sessions`, `workspace_notes`, `materials`, and `concept_memory_states` (due review count, which is also time-dependent).
- Scope: owner. One generation per owner covers all of that owner's course entries.
- Bump `course` for the owner after commit on:
  - all `CourseService` writes (create/update/delete, roadmap add/update/delete/reorder/generate, set/remove session course, attach/detach material);
  - **insert/delete or `course_id` change** of `learning_sessions`, `workspace_notes`, `materials`.
- Do **not** bump on ordinary session payload updates (every chat turn writes `learning_sessions`; bumping there would destroy the hit rate). Find writers with `grep -rnE "(INSERT INTO|UPDATE|DELETE FROM) (courses|course_roadmap_nodes|learning_sessions|workspace_notes|materials)\b" backend/app` and classify each.
- `due_review_count` staleness from review activity is accepted, bounded by TTL. Document this in the code at the cache site.
- TTL: 60 s.

**2c. `calendar`: calendar list and occurrences.**

- Routes `GET /calendars` and `GET /occurrences` in `backend/app/calendar/routes.py:46,67` (polled by the client). Identify the service functions behind them and every writer (event create/patch/cancel, proposals decisions, preferences, permissions, Google sync, operation undo/reconcile, reminder workers). Bump `calendar` for the owner after each commit.
- Occurrence queries take a time range. Include the normalized range in `parts`.
- TTL: 30 s.

**Phase 2 acceptance:** shadow mode shows zero mismatches across the test suite and a production soak (excluding the documented `due_review_count` lag) before serving from the cache.

### Phase 3: Usage display aggregates

- `GET /v1/usage/summary` and `GET /v1/usage/analytics` (`usage_routes.py:136,145`). Display only.
- Bump `usage_display` for the owner after usage settlement commits (find the ledger settlement path in `backend/app/usage/ledger.py`).
- **Never** `/usage/allowance`, `/usage/estimate`, `/usage/activity`, or any ledger read used for admission.
- TTL: 60 s.

### Phase 4: Conversation history (gated; do not start without the owner's go-ahead)

Start only if diagnostics from Phases 0-3 show that `generation_context` database time is a meaningful share of time to first token.

- History for generation comes from the journey/session payload (`journey["turns"]`) plus the branch parent map (`response_branches`) and the generation's branch (`generation_records`), assembled in `journey_service.py` around lines 383-399 via `conversation_branching.visible_context_turns`.
- Candidate: cache the `response_branches` parent map per `(owner_scope, session_id)`, bumped after any commit that inserts or updates `response_branches` for that session.
- Caching turns themselves requires a per-session generation bumped after **every** commit that changes the session's turns. Read-your-writes is mandatory: a message persisted before generation must appear in that generation's context. Prove this with a test that persists a message then immediately builds context, under concurrent writers.
- Write a short design note in this document's §13 and get approval before implementing.

## 9. Tests

Put tests in `backend/tests/test_cache.py` (foundation) and extend the existing domain tests (`test_web_evidence*.py`, `test_materials.py`, `test_material_index.py`, `test_courses.py`, `test_course_*.py`, calendar and usage tests). Use `fakeredis` via a fixture in `conftest.py` that installs a `RedisCache` backed by `fakeredis.FakeRedis` and enables the namespaces under test. Default fixture state remains `NullCache`.

**Foundation (Phase 0):**

- Hit, miss, TTL expiry, jitter bounds.
- Decode failure → key deleted, loader result returned.
- `CACHE_SCHEMA` change → old entries ignored.
- Redis raising on every call → correct results from the loader, no exception, breaker opens after 5 errors and recovers.
- `NullCache` never calls the loader more or less than once per request.
- Owner isolation: same `parts`, different owners → different keys and values.
- After-commit: invalidation inside a committed `Store.transaction` bumps once (deduplicated); inside a rolled-back transaction it doesn't bump; nested/`nullcontext(connection)` usage flushes only at the outermost commit.
- Stale write-back race: loader captured at generation g, writer commits and bumps, slow loader then sets; the next read returns fresh data.
- `erase_scope` removes all of an owner's keys and no other owner's.

**Per namespace:**

- Read-after-write: every writer listed in §8 for that namespace, followed by a read, returns fresh data. Implement as a parametrized table of (write action, read action) so newly added writers are easy to add.
- Response parity: the cached response body is byte-identical (after JSON normalization) to the uncached response.
- Authorization: a deleted/foreign resource still 404s/403s with a warm cache.

**Integration:** add one job (or step) in `.github/workflows/platform-release-validation.yml` that runs the cache tests against a real Redis service container alongside PostgreSQL. Mark them so the default local run doesn't require Redis.

Run tests from the repository root, as CI does, e.g. `python -m pytest -q backend/tests/test_cache.py`.

## 10. Rollout

1. Deploy Phase 0 with `OPENLEARN_CACHE_ENABLED=false`. Verify no change.
2. Provision Key Value (owner approval), set `REDIS_URL` in the shared env group, enable caching with an empty namespace allowlist. Generations bump; nothing is served. Confirm the error rate is zero and the connection budget holds.
3. Enable `web_evidence,material_blocks`.
4. For each Phase 2/3 namespace, first enable **shadow mode**: compute both cached and fresh values, return the fresh value, and count/log content-free mismatches (namespace + field names only). Promote to serving only after zero unexplained mismatches over an agreed soak.
5. **Rollback** is configuration only: remove the namespace from the allowlist, or set `OPENLEARN_CACHE_ENABLED=false`. No data migration is ever needed.

## 11. Definition of done (per phase)

- Hard rules in §2 hold; reviewer can point to the test that enforces each one touched by the phase.
- Existing suite plus new tests pass locally without Redis and in CI with Redis.
- Metrics visible in the operational snapshot; hit rate measured for each enabled namespace.
- Before/after numbers recorded in `docs/performance/` for the affected endpoints (p50/p95 latency, queries per request, pool checkout wait), following `docs/performance/Benchmark_Protocol.md`.
- `CHANGELOG.md` and this document's §13 updated.

## 12. Out of scope

- Provider prompt caching (reordering stable instructions/history before per-turn reference data in `model_provider.py`, `prompt_cache_key`, measuring `cached_tokens`). Track separately.
- Redis pub/sub or queues. PostgreSQL LISTEN/NOTIFY remains the selected wake-up mechanism (performance plan A01).
- Rate limiting / burst limits in Redis.
- Response caching of model outputs.
- Fixing the `list_courses` N+1 query. Recommended as a separate change; caching shouldn't hide it.

## 13. Decisions and implementation log

Decisions for the project owner (record answers here):

- [ ] Approve provisioning Render Key Value (plan/cost) and the connection budget.
- [ ] Confirm user-uploaded material text (`material_blocks`) may be cached in Redis on Render's private network with 24 h TTL and erasure on delete. If not, drop 1b.
- [ ] Confirm shadow-mode soak duration for Phase 2/3 namespaces.
- [ ] Phase 4 go/no-go after diagnostics.

Implementation log (agent appends: date, phase, PR, deviations from this spec and why):

-
