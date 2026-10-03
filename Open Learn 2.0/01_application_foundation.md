# Application foundation and durable execution

Establish shared service ownership, durable workers, object storage boundaries, and reliable follow-up delivery within the modular monolith.

Status: planned. Source: section 3 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

Implementation update: execution foundation added in migration `0028`, with worker startup, lease fencing, transactional delivery and immutable storage adapters. See [implementation and operations notes](../docs/APPLICATION_FOUNDATION.md) for delivered boundaries, configuration and outstanding runtime verification. Existing material and whole-recording binary paths remain compatibility adapters to migrate with their owning features; the new lecture object path uses the shared storage interface.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

Start with the current repository inventory and the shared architecture decisions.

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/main.py](../backend/app/main.py)
- [backend/app/database.py](../backend/app/database.py)
- [backend/app/workflow_store.py](../backend/app/workflow_store.py)
- [backend/app/generation_store.py](../backend/app/generation_store.py)
- [backend/migrations](../backend/migrations)

## Implementation sequence

1. Inventory existing job and generation contracts; document module ownership and the supported local and hosted execution profiles.
2. Extend durable jobs with input revisions, attempts, retry scheduling, cancellation, and lease validation. Keep provider calls outside database transactions and preserve the SQLite claim path.
3. Add a transactional outbox and idempotent consumers. Commit authoritative attempts, evidence, affected capability state, and activity position together; send expensive derived work through the outbox.
4. Give asynchronous projections an event watermark. Consumers must catch up, recompute the small required state, or report pending analysis before using a stale result.
5. Introduce a shared immutable object interface with local filesystem and hosted storage adapters; exercise crash recovery, expired leases, and duplicate delivery.

## Detailed feature requirements

### Module ownership

Keep one backend application with modules for identity, evidence, concepts, learner state, memory, context, pedagogy, assessment, recordings, academic data, browser integration, planning, and evaluation. Each module owns its tables and mutations. Other modules call its service interface or consume its durable events. Avoid direct writes into another module's projection tables.

Reuse the existing package layout where possible. These are boundaries of responsibility, not a requirement to move every existing file into a newly named directory. A small refactor that establishes one shared context service is preferable to relocating the entire application without changing behavior.

Run interactive HTTP and streaming work in the API process. Run transcription, document extraction, embedding, state rebuilds, and evaluation in worker processes from the same application codebase. Use the existing durable job machinery if it supports claims, leases, retries, cancellation, and deduplication; extend it where needed. A worker process is an execution boundary, not a new microservice.

### Durable jobs and transactions

A job stores owner, type, target entity, input revision, idempotency key, status, attempt count, next retry time, lease expiry, progress, cancellation state, and safe error code. PostgreSQL workers can claim queued work using short transactions and row locking with SKIP LOCKED [6]. SQLite uses a supported single-writer claim path rather than copying PostgreSQL concurrency assumptions.

Never hold a database transaction open while waiting for a model, browser operation, or transcription request. Commit the job claim, execute external work, and then commit validated output if the input revision and lease still match. Expired workers cannot overwrite newer results. Transient failures retry with bounded exponential backoff and jitter. Authentication failures, unsupported files, and invalid permissions require a user or configuration change rather than endless retries.

The learning command transaction saves the attempt, evidence event, affected learner projections, quiz position, and durable follow-up work together. Expensive consequences such as embedding and schedule recomputation run after commit. A transactional outbox records those consequences so a crash cannot lose them. Delivery is at least once; unique keys and idempotent handlers make repeated delivery harmless. We do not claim exactly-once execution of external providers.

### Storage and identifiers

PostgreSQL holds structured state, histories, source metadata, and jobs. Object storage holds immutable audio, PDFs, images, and large transcript exports. Local filesystem storage implements the same object interface for desktop use. Text retrieval uses relational filters plus full-text search; vector retrieval may use pgvector in hosted PostgreSQL. A deterministic local text-search fallback keeps SQLite installations functional.

Use opaque globally unique IDs. Every owned row carries the verified account or learner owner. Course membership scopes course data, while concept identity remains separate from course names and graph revisions. Timestamps use UTC instants with an IANA timezone where a human scheduling interpretation matters. A date-only deadline remains a date until an explicit time is provided.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
