# AI Tutor Harness backend

This backend is the functional modular-monolith slice for the learning harness. It
accepts any topic, creates a bounded `TopicScope`, runs a persisted graph job,
and returns a versioned graph with stable IDs, typed edges, and an explicit
trust label.

The default provider is `deterministic_baseline`. It requires no AI API key and
does not invent domain facts: it creates a generic instructional scaffold whose
concepts and relationships are marked `limited_unverified`. This makes the
frontend integration and state contracts testable immediately. The next
provider can implement the same `GraphGenerator.generate(scope)` boundary with
retrieval and a structured model call, followed by the same validation and
publication checks.

## Run locally

Install dependencies and run from the project root. SQLite remains the zero-
service local/test fallback:

```bash
python -m pip install -r backend/requirements.txt
export DATABASE_URL="sqlite+pysqlite:///backend/data/forma.db"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

For PostgreSQL, create a database and replace the URL:

```bash
createdb ai_tutor
export DATABASE_URL="postgresql+psycopg://localhost/ai_tutor"
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Startup upgrades the schema automatically. The explicit Alembic command is
useful for release checks. Deployed environments must set
`AI_TUTOR_ENV=production` and a PostgreSQL URL; SQLite is refused in that mode.
Legacy `FORMA_DB_PATH` remains a local-only fallback so existing databases can
be upgraded in place.

The API is available at `http://127.0.0.1:8000` and its OpenAPI document at
`/docs`.

## Class recordings to study notes

Class audio is uploaded from the browser to the owner-scoped local API, stored
beside the database, and linked to the existing Markdown note. Processing
transcribes with the selected provider's audio transcription API and creates a Markdown study
guide with the selected text provider. Processing state survives restarts;
queued or interrupted recordings resume on startup. Failed jobs keep the audio
and can be retried from the note.

Recordings are limited to 24 MB per file. Transcription follows `AI_TUTOR_PROVIDER`
by default: OpenRouter users can use their existing `OPENROUTER_API_KEY`, and
OpenAI users can use `OPENAI_API_KEY`. `AI_TUTOR_TRANSCRIPTION_PROVIDER` can
select either provider independently. The OpenRouter audio model defaults to
`openai/whisper-large-v3` (`AI_TUTOR_OPENROUTER_TRANSCRIPTION_MODEL` overrides it);
the direct OpenAI model defaults to `gpt-4o-mini-transcribe`
(`AI_TUTOR_TRANSCRIPTION_MODEL` overrides it). Audio and note files can be placed in custom
locations with `AI_TUTOR_RECORDINGS_DIR` and `AI_TUTOR_NOTE_VAULT_DIR`.

## First graph flow

```text
POST /v1/topic-scopes
  {"topic":"probability","depth":"introductory"}
        ↓
POST /v1/topic-scopes/{scope_id}/graph-jobs
        ↓
GET  /v1/graph-jobs/{job_id}
GET  /v1/graphs/{graph_id}
```

The synchronous completion is intentional for this local slice. The job is
still persisted with stages and status so it can move to a worker without
changing the HTTP contract. `Idempotency-Key` is accepted at the boundary and
will become the deduplication key when retries and authenticated sessions are
added.

## Production Learning Kernel

The first ChatGPT-style action path is now functional with the same
provider-neutral boundary:

```text
POST /v1/sessions
  {"graphId":"graph_...","goal":"Understand the foundations"}
        ↓
POST /v1/sessions/{sessionId}/actions
  {"intent":"teach","conceptId":"concept_...","gear":"Guided",
   "message":"Teach me this from first principles"}
        ↓
GET  /v1/runs/{runId}
GET  /v1/actions/{runId}/events   (text/event-stream)
GET  /v1/lessons/{lessonId}
```

The action assembles a typed `ActionContext` from the selected graph, target
objective, current session position, Teaching Gear, learner projection, and
request intent. It traverses only incoming `requires` edges, with explicit
cycle, missing-node, unsupported-edge, depth, and node-budget outcomes. The
resulting `TeachingPlan` is persisted before generation and includes its
prerequisite classification, strategy, representation sequence, concepts to
avoid, intended next action, and policy/version metadata.

The response adds `actionContext`, `teachingPlan`, and `policyValidation` while
preserving the existing run and lesson fields. A plan can also be inspected at
`GET /v1/teaching-plans/{planId}`. Actions emit replayable events
(`action.started`, `intent.classified`, `context.ready`, `plan.created`,
`plan.validated`, `artifact.created`, `verification.completed`, and
`lesson.completed`). JSON remains camelCase for the web client.

Quick, Guided, and Deep compile to different policy dimensions and
representation sequences, not token targets. Simplify, Why, Example, Visualize,
Resume, and Check Understanding are typed local overrides. Deep + Simplify, for
example, keeps mechanistic depth and derivation while lowering abstraction and
step size. Visualize is bounded to a labeled relationship representation with a
text equivalent; it is not an arbitrary simulation renderer.

The current local provider is deliberately called
`deterministic_baseline`. Its lesson is a qualified instructional scaffold
with `insufficient` trust and a source-review note. It does not claim to have
answered arbitrary domain questions or update mastery. Policy validation
explicitly records that it did **not** establish source-backed correctness,
model verification, or calibrated mastery. Opening or generating a lesson
creates no learner evidence and does not mutate the learner projection. Failed
actions do not advance session position. An idempotency-key retry returns the
already committed run, plan, lesson, and events rather than duplicating them.

A model and retrieval provider can later replace lesson rendering behind the
same policy and action contracts. This slice intentionally adds no retrieval
provider, broad assessment engine, flashcards, or complete learner-state
estimator.

No API key is required for the current slice. A provider key becomes necessary
when the deterministic baseline is replaced with source retrieval and model
generated concepts. Keep that key server-side using `.env.example` as the
template; never place it in the browser or repository.

## Learner-owned knowledge graph

Topic graphs are bounded source material. The learner graph is a separate,
cross-topic projection that persists what a learner has encountered and the
evidence-backed overlay state that the learner-state service supplies. A topic
graph can be imported into the learner graph without changing the source graph;
repeating the same import does not duplicate its concepts or edges.

```text
POST /v1/learners/{learner_id}/knowledge-graph/import
  {"graph_id":"graph_..."}
GET  /v1/learners/{learner_id}/knowledge-graph
POST /v1/learners/{learner_id}/knowledge-graph/events
GET  /v1/learners/{learner_id}/knowledge-graph/events
```

The compatibility event projection supports concept exploration, lesson completion,
assessment evidence, demonstrated concepts, review due, and detected
misconceptions. It records events separately from the graph snapshot and keeps
canonical learner-state estimation owned by `LearnerStateService`; these states
are a visual/UX projection rather than a source of canonical mastery.

Session creation now accepts an optional `learner_id` (default `local`) and
imports the session's topic graph into that learner's global projection. This
keeps the graph continuous across sessions and topics. Action evidence is not
implicitly inferred from session creation or generated lesson output. Those
actions append activity events only.

## Persistent learner state

The state API persists curriculum compatibility, canonical concept state,
events, evidence and supersession, misconception hypotheses, review schedules
and history, nested branches, and anchored notes with revisions. Requests are
scoped by learner ID and use camelCase JSON. Evidence admission is idempotent
and is the only path that can update canonical concept state.

See [STATE_CONTRACT.md](STATE_CONTRACT.md) for exact routes, the development
identity safety boundary, conservative reducer behavior, and deferred ownership
for assessments, knowledge tracing, and authentication.

Run validation with:

```bash
python -m pytest backend/tests -q
python -m compileall -q backend/app backend/migrations
```

`python -m app.evaluation_runner` emits deterministic, machine-readable policy
fixtures without provider calls or credentials. `/v1/local-backup` creates a
checksummed archive of local SQLite records, vault Markdown, and owned material
objects only; it never reads credential storage, desktop tokens, environment
variables, or logs. Restore requires preflight and explicit replacement when
local data already exists.
# Lecture recording pipeline

New class recordings use `POST /v1/learners/{learner_id}/lecture-recordings` to create a durable session and note, followed by eight-second browser audio slices sent to `PUT .../{recording_id}/chunks/{sequence}`. Each upload includes `X-Chunk-Start-Ms`, `X-Chunk-End-Ms`, and `X-Chunk-Sha256`; the server acknowledges an exact duplicate. Stop calls `POST .../{recording_id}/finalize` with the expected chunk count. `GET .../{recording_id}` reports missing slices and the progress of transcription, semantic analysis, verification, and note generation. The legacy `class-recording` API remains available for existing recordings.

The browser persists slices in IndexedDB before upload, resumes on reconnect or reload, and asks the learner to finish an interrupted capture. The backend saves retained files under `AI_TUTOR_RECORDINGS_DIR/lectures`, uses the existing leased job table for processing, and resumes jobs on startup. Audio transcription follows the selected OpenRouter or OpenAI provider, while the selected text provider handles section analysis and claim verification. Saved failures can be retried after changing provider settings. Generated note blocks live in lecture tables and appear beside the learner's editable note body; regeneration does not change authored text.

For a local development check, run `python -m pytest backend/tests/test_lecture_pipeline.py -q`. The test suite includes a simulated hour with 450 slices. Deployments with multiple backend processes require shared object storage and a dedicated durable worker before handling real classrooms.
