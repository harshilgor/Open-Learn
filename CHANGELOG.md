# Changelog

All notable changes are recorded here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses semantic version tags for published releases.

## [Unreleased]

### Added

- Learner memory Phase E (flagged, default off): `OPENLEARN_MEMORY_CONSOLIDATION` runs a daily `memory_consolidate` job for each owner with memory activity in the last 3 days.
  - Forgetting: stale tentative inferences are deleted after 30 days; tentative statements by the learner are archived, never deleted. Reinforced tentative facts are promoted. Facts whose strength falls below 0.05 and deadlines past their 7-day grace are archived, as are episodes older than a year.
  - Near-duplicates in the same kind and scope merge into the older fact (lexical until embeddings are approved). Same-rank conflicts within 24 hours are flagged `needs_review`.
  - Episodes: idle sessions (2 hours) get an extractive `memory_episode` (questions, answer headings, lesson titles, concept IDs; no model call). Questions that read as instructions or touch a sensitive category are left out. Deleting a conversation deletes its episodes.
  - Core profile: a deterministic, byte-stable list of the learner's most durable facts, stored in `context_records`, rewritten only when its bytes change, and cached in the new Redis `learner_profile` namespace. It replaces the Phase D profile section; forgotten facts leave it immediately.
  - New `GET /v1/memory/profile` and `GET /v1/memory/changes` (content-free counts, e.g. "3 memories archived, 1 updated").
  - Evaluation adds 15 forgetting cases (all must pass; no learner-stated fact may be deleted). Consolidation of 2,000 facts takes 0.76 s on SQLite; warm retrieval p95 with the core profile is 14.9 ms.
- Generated visuals are runtime-verified before learners see them: a headless sandbox mounts each candidate exactly like the chat card at desktop and mobile widths, checks for errors, blank or empty renders, invalid readouts, clipped layouts and dead controls, and feeds specific findings back to the model for bounded repair.
- Conversational visual editing: follow-ups such as "add air resistance to this" revise the existing visual from its exact source, carry over saved control values, and record lineage ("Version 2") while leaving the earlier version untouched.
- Visual progress shows sandbox testing and repair attempts; generated visuals can be opened full screen.
- `backend/scripts/visual_benchmark.py`: a live generative-visual benchmark with task-specific scientific and interaction checks.
- Science checks for priority topics (pendulum, Ohm's law, projectile motion, gradient descent, neuron activation, transmission-line reflection) test displayed values against the governing formula before a visual is shown.
- Optional screenshot judge (`OPENLEARN_VISUAL_JUDGE_MODEL`): a reviewed multimodal model's critique of a working first attempt feeds one improvement pass; it never blocks a visual.
- Paid Claude visual models are supported through `OPENLEARN_VISUAL_REQUIRE_PROVIDER_PARAMETERS` and `OPENLEARN_VISUAL_TOOL_CHOICE`.
- Learner memory Phase D (flagged, default off): `OPENLEARN_MEMORY_RETRIEVAL_V2` replaces the Phase A block with ranked retrieval for chat and Learn mode.
  - Ranking parses time phrases in the learner's message (today, last week, next Friday, "in November", dates, "when is my…"). It then scores facts and past-session episodes by lexical BM25, concept overlap and time fit, weighted by a strength that decays with disuse (§9.2) plus origin and course bonuses.
  - Selection applies diversity limits and token budgets. The block renders as byte-stable text with a Profile section (preferences and constraints).
  - Assessment context gets only preferences and constraints.
  - Use is recorded at turn commit (stability grows at most once a day). The context inspector shows a content-free `memoryTrace`.
  - Static ranking rows are cached per process and revalidated by a per-owner version counter (migration `0087_memory_fact_versions`; release head moved). Warm retrieval p95 is 19 ms at 2,000 facts on SQLite.
  - The evaluation suite adds 50 retrieval cases with recall@5 gates. Benchmark script: `backend/scripts/memory_retrieval_benchmark.py`.
- Learner memory Phase C (flagged, default off): `OPENLEARN_MEMORY_EXTRACTION=off|shadow|on` with `OPENLEARN_MEMORY_EXTRACTION_MODEL` queues a `memory_extract` job in each chat turn's commit transaction. The job proposes facts with a strict-schema model call billed to the learner's allowance, and a deterministic validator keeps only facts backed by a verbatim quote from the learner's own typed words (not code, block quotes, pasted text, or other people). The validator also enforces an injection denylist, sensitive-category rules (stored only on explicit request, flagged `sensitive`), deadline dates, course matching, and per-turn/per-day caps. Changed facts supersede older ones in the same scope, and Undo restores them. The web client marks pasted text, sends its timezone, shows "Saved to memory · View · Undo" under the turn, and shows a one-time notice. New `GET /v1/memory/facts?generation_id=` and `DELETE /v1/memory/facts/{id}?undo=true`. A deterministic evaluation suite (`evaluation_runner --memory`, 50 cases) gates promotion from shadow. The usage ledger accepts Claude Haiku 5.5 when it is the configured memory model.
- Learner memory Phase B: migration `0086_learner_memory` adds `memory_facts` (add-only, with a timeline and a one-active-fact-per-subject index), `memory_episodes`, `memory_embeddings`, and `memory_settings`, and backfills existing saved preferences as facts. Saving a preference (Settings or "remember that…") also writes a fact in the same transaction; dismissing it or removing its source deletes the fact, and revising the source archives it. New owner-scoped, `no-store` APIs: `GET /v1/memory/facts`, `GET /v1/memory/facts/{id}/history`, `GET`/`DELETE /v1/memory/episodes`, and `GET`/`PUT /v1/memory/settings`. The chat memory block now reads preferences from `memory_facts`. The release contract schema head is now `0086_learner_memory`.
- Learner memory Phase A (flagged, default off): `OPENLEARN_MEMORY_CHAT_CONTEXT` adds a bounded `learnerMemory` context block to default chat with explicit saved preferences, course dates in the next 30 days, and a five-item learner-state snapshot; `OPENLEARN_MEMORY_SKIP_UNUSED_COMPILE` skips the shared context compile that streamed chat turns discarded.
- Optional Redis cache-aside layer (`backend/app/cache.py`) for polled and repeated reads: web evidence results, material blocks, concept graph, courses, calendar, and usage display aggregates. Off by default (`OPENLEARN_CACHE_ENABLED`, `REDIS_URL`); fail-open with a circuit breaker; per-namespace enable and shadow modes; generation-based invalidation flushed after commit; erasure on account deletion; Render Key Value in the Blueprints and Redis connection budget. See `docs/REDIS_CACHE_ASIDE_IMPLEMENTATION.md`.
- Persistent chat history in the sidebar with time grouping, search, rename, delete, and per-learner isolation.
- Living study notes: each Learn chat owns a linked note; the tutor proposes concise sections (turns, side explorations, quiz checklists) with accept/edit/reject and tutor/user/shared ownership plus revision protection.
- Fullscreen Settings with General, API keys, Notifications, Data & privacy, and About; browser clients can save provider keys to the local service configuration.
- On-device usage analytics (tokens, generations, cost) with trend and top-session views.

- Learn workflow with Ask/Learn mode, teaching gears, resumable learner journeys, inline assessment, and a direct path into Quiz.
- Quiz workspace with generated question sets, answer evaluation, repair guidance, and evidence admission through the canonical learner-state service.
- Local privacy controls to export learner records as JSON or permanently remove locally stored learner data and imported materials.
- Desktop provider setup backed by the operating system credential store, a first-run setup screen, native workspace settings menu, and optional due-review notifications.
- Electron desktop packaging for a bundled web interface and FastAPI sidecar, per-user application-data directories, dynamic loopback ports, loopback-token protection, sidecar recovery, and GitHub Actions packaging workflows.
- Signed-beta release automation for Windows x64 and macOS Intel/Apple Silicon, with signing/notarization gates, release checksums, beta release notes, and an upgrade-validation runbook.

### Changed

- Visual generation limits are configurable (`OPENLEARN_VISUAL_MAX_OUTPUT_TOKENS`, default 16000; `OPENLEARN_VISUAL_DEADLINE_SECONDS`, default 600; `OPENLEARN_VISUAL_MAX_ATTEMPTS`, default 3; `OPENLEARN_VISUAL_MAX_INPUT_BYTES`, default 160000).
- Turns where no visual is useful end without a visual-model call.
- The shared context compiler estimates tokens as UTF-8 bytes / 3 (matching the generation context engine) instead of one token per byte, so compiled packets admit about three times more content within the same budget. Remembered items are ranked course-scoped, explicit, newest first and capped at 12.
- Updated the repository README and installation guide around the local desktop beta and GitHub Releases distribution.

### Fixed

- Visual model calls were often charged at their full conservative reservation because the usage receipt arrived after the agent stopped reading; finished generations are now drained for their receipt, and provider-rejected requests settle at zero.
- Visual code validation crashed on Windows for any visual containing non-ASCII text (Greek letters, arrows, emoji).
- Valid visuals that create elements in JavaScript were rejected as missing DOM targets.
- `(await import('three')).default`, `d3` defaults and the `three/examples/jsm` OrbitControls path now resolve in visual frames.
- Claude visual models: repair and polish attempts failed with HTTP 400 (orphaned tool calls in the continuation). Feedback now continues the thread as a user message, and tool calls are paired before each model call.
- Claude visual models: visuals often never started because a malformed trailing `jsExpressions` argument was dropped. It is now recovered and verified like any other code, and a declared `editOf` is recovered from the same arguments.
- Edits that keep the original visual's structure are recognized even when the model omits `editOf`.

### Known limitations

- `v0.1.0-beta` is publishable only after the repository signing and notarization secrets are configured; no public installer exists until that release workflow passes.
- Silent Squirrel uninstall needs final verification through a normal interactive Windows installation; learner data is intentionally preserved across uninstall/reinstall.
- Hosted accounts, synchronization, automatic updates, calibrated mastery, and retrieval-backed source verification are not included.
