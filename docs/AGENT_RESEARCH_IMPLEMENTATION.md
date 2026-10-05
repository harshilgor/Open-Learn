# Agent execution slice 2: research and durable outputs

Implemented on 4 October 2026, following `Open Learn 2.0/26_agent_execution_platform.md`, section 12. This slice builds on the shared foundation worker, owner-scoped task API, events and artifact store. It does not complete slices 3–7.

## Learner flow

Select Research in the shared assistant panel in either existing chat surface, enter a question, and submit. Admission records the explicit capability and a validated research specification. Ordinary tutoring messages continue through the existing tutor. The panel reconnects to persisted task state and shows progress, completion checks, downloadable Markdown and JSON files, and sources. Inspecting a source fetches its retained excerpt on demand through the authenticated API; source text renders as plain text. A follow-up creates a linked task with the new question. Foundation pause, resume, cancel and reply controls apply to research too.

## Backend connections

`agent_execution/research.py` wraps the existing WebEvidenceService and Exa adapter, retaining existing egress, quotas, assessment and emergency-stop policies. Session identity and owner come from authenticated state. The specification chooses attached materials, external evidence, or attached-first retrieval; searches and source opening are bounded. Attached-first work can produce a partial material report when external search is unavailable. External-only work reports missing setup explicitly.

Migration `0043_agent_research` adds revision-scoped research journals and immutable source snapshots after foundation migration `0042`. The journal records completed retrieval steps and validated synthesis, allowing worker recovery without repeating successful provider calls. Source snapshots retain excerpts independently of the short-lived response cache. Each snapshot records input revision, content hash, retrieval time and provenance. Material snapshots recheck the attached version and block hash before access.

The worker prepares report metadata, stores immutable objects using the existing ObjectStore, then publishes a fenced final event. Recovery after storage reuses the prepared objects. Revision changes and cancellation prevent stale publication. Foundation artifact downloads check owner access, object integrity and retained source access. Expired or deleted sources invalidate dependent reports; worker cleanup removes the report objects. Material deletion also erases the new durable snapshots in the same database transaction. This does not claim immediate deletion of independent upstream provider caches.

Source APIs are `GET /v1/assistant/tasks/{taskId}/sources`, `GET /v1/assistant/sources/{sourceId}` and `DELETE /v1/assistant/sources/{sourceId}`. Cross-owner identifiers return unavailable; unavailable retained content cannot be downloaded through a dependent report.

A caller can submit this body to `POST /v1/assistant/messages` with the normal authenticated session and a stable `Idempotency-Key`. Substitute a session owned by that user and reuse the client message ID only when retrying the same request:

```json
{
  "clientMessageId": "research-request-1",
  "sessionId": "owned-session-id",
  "text": "Does retrieval practice improve recall?",
  "capability": "research",
  "researchSpec": {
    "query": "Does retrieval practice improve recall?",
    "sourcePolicy": "attached_preferred",
    "maxSources": 5,
    "openSources": 2
  }
}
```

Use the task reference returned by admission with the foundation task/activity APIs. Download each final artifact through `GET /v1/assistant/artifacts/{artifactId}/download`. Empty questions, unknown fields and out-of-range source limits are rejected rather than interpreted as agent instructions. A deleted or expired source cannot be revived by retrying its old journal; start a linked new task to retrieve fresh evidence.

## Completion meaning

Without a JSON-capable model, the output is an explicitly labeled excerpt digest. With a model, the question and bounded evidence are supplied together as untrusted data. Structured validation rejects unknown citations, unsupported claimed quotes and generated URLs. Source text is escaped in Markdown output. Citation existence and exact quotes are checked; model synthesis is marked semantically unverified and the task completes partially. No independent semantic verifier or comprehensive coverage guarantee is claimed. Research never writes learner mastery or assessment evidence.

## Configuration and deployment

Enable admission with `OPENLEARN_AGENT_ADMISSION_ENABLED=true`. Production uses `OPENLEARN_WORKER_MODE=external` and a separately supervised `python -m backend.app.agent_execution.worker` process. External research requires the existing `AI_TUTOR_WEB_EVIDENCE=true`, `AI_TUTOR_WEB_PROVIDER=exa` and server-only `EXA_API_KEY`. Existing WebEvidenceService host, budget, timeout and kill settings continue to apply. Never put provider keys in frontend configuration.

`OPENLEARN_RESEARCH_CONTENT_RETENTION_SECONDS` controls snapshot retention, bounded from 60 seconds to 30 days, default 30 days. Choose the deployment's retention policy before enabling production use. Apply migrations using the repository's normal deployment process; do not downgrade a populated production database merely to test migration rollback.

## Verification and remaining release gates

The deterministic research suite covers HTTP admission through worker completion and authenticated downloads, source inspection/deletion, Exa search and contents using mocked HTTP transport, provider-cache expiry, worker crash after storage, restart deduplication, source retention expiry, material detach/deletion, owner isolation, cancellation/revision fences, assessment and emergency-stop gates, strict citations, and honest partial completion. It also invalidates a source after storage but before publication: both deletion and expiry must prevent a successful final event. No paid Exa requests are needed for these tests.

Recorded validation: 19 research cases, the existing evidence regressions, 14 affected frontend tests, and the production frontend build. Foundation additionally verified 50 backend cases covering migrations, identity, execution, lecture and object storage (one environment-dependent skip). The research cases include deletion during model synthesis, which must not persist deleted source content back into the journal, and an upload finishing after cleanup, which must requeue the orphan object for deletion. See the foundation implementation record for its full evidence and environment constraints.

Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_agent_research.py backend/tests/test_web_evidence.py -q -p no:cacheprovider` and `npm run test:agent` from `web` for the research-source, execution-panel and browser-compatibility components. The foundation validation also covers migration upgrade/rollback and production frontend compilation. Windows temporary-directory ACL failures in unrelated storage fixtures require the permitted test environment; they are setup failures, not passing checks.

Real in-app browser verification opened the existing session chat, selected Research, submitted a question, observed completion, and inspected the retained plain-text source excerpt. Reload restored both task histories and their file/source controls. This used the isolated deterministic preview fixture, labeled Offline fixture, with no production route injection or paid provider calls. The shared lab flow also completed after answering its persisted units question. The browser download click reached an HTTP 200, but the in-app download/path bridge timed out; no claim is made that a browser-saved file path was verified. Authenticated HTTP download and content checks passed separately.

Live provider credentials/egress, deployed worker supervision, PostgreSQL concurrency, and real multi-device reconnect still require deployment evidence. Native lecture recording and Daytona execution belong to later slices. Keep the feature flag disabled in production until those applicable environment checks are completed. The real-browser result covers the local deterministic flow and does not substitute for these environment checks.
