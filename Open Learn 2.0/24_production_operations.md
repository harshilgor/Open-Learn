# Performance resource use and production operations

Operate the integrated system within measured latency, cost, privacy, recovery, and resource limits.

Status: partial operations and recovery runbook added. Runtime service limits, deployed metrics, restoration drills, PostgreSQL concurrency, and live provider thresholds remain unverified. Source: section 24 of OpenLearn Complete Implementation Brief, prepared 30 September 2026.

Implementation: see [operations and cutover runbook](../docs/OPENLEARN_2_OPERATIONS_AND_CUTOVER.md). It records current deployment profiles, worker operation, backup/restore precautions, recovery actions, and release gates. Numeric performance targets remain unset until measured on supported environments.

The implementation sequence below translates the brief into repository work. Proposed names and policies must be reconciled with existing contracts before implementation. The detailed requirements retain the source brief’s wording.

## Dependencies

- [Application foundation and durable execution](01_application_foundation.md)
- [Shared data contracts and architecture decisions](02_shared_data_contracts.md)
- [Identity authorization and device synchronization](03_identity_and_device_sync.md)

Dependencies here are implementation prerequisites. Later consumers integrate through typed contracts; their existence is not required to begin this component. See [build order](BUILD_ORDER.md).

## Existing implementation to inspect

- [backend/app/workflow_store.py](../backend/app/workflow_store.py)
- [backend/app/generation_service.py](../backend/app/generation_service.py)
- [backend/app/usage_service.py](../backend/app/usage_service.py)
- [backend/app/backup_service.py](../backend/app/backup_service.py)
- [backend/app/privacy_routes.py](../backend/app/privacy_routes.py)
- [start-local.ps1](../start-local.ps1)
- [docs/STREAMING_DEPLOYMENT.md](../docs/STREAMING_DEPLOYMENT.md)

## Implementation sequence

1. Separate interactive and batch job capacity; bound provider calls, upload queues, decoding spools, source processing, and retries.
2. Instrument p50/p95 latency and costs by stage; establish numeric targets after baseline measurement and before production cutover.
3. Implement revision-keyed cache invalidation, event-watermark checks, safe diagnostics, and alerts for stuck or inconsistent work.
4. Provide audited replay/reindex/retry tools, tested database-object restoration, deletion-aware restores, and reversible deployment procedures.

## Detailed feature requirements

### Keep model calls purposeful

Structured state reduction, scheduling, ownership checks, graph traversal, and task ranking run in deterministic code. Models are used for content interpretation, question authoring and checking, open-ended grading, and teaching. Reuse an accepted evaluation and source extraction across retries. Avoid re-embedding unchanged sources or generating every possible task's content before the learner selects one.

Maintain configurable limits for context tokens, authoring retries, transcript windows, extraction sections, concurrent uploads, jobs per account, and provider calls. Differentiate interactive queues from batch ingestion so a large recording does not delay an answer or a quiz submission. Apply backpressure before memory or storage grows without bound.

### Measurement targets

Instrument time to first teaching token, time to validated question, answer-evaluation latency, projection commit time, transcription lag behind capture, upload acknowledgment latency, and Canvas synchronization completeness. Record p50 and p95 by environment and provider. Also track tokens, external cost, worker CPU, peak memory, disk queue size, and retry rate.

The team will set numeric latency and concurrency targets after measuring the existing product and testing the supported deployment profiles. Relative acceptance requires no unexplained material regression in ordinary interactions, and absolute targets must be recorded before production cutover. Model and network latency should be separated from application overhead so optimizations address the actual bottleneck.

### Cache and projection safety

Use revision-keyed caches and bounded retention. Frequently read learner projections are small relational records. Expensive state rebuilds are scoped to affected concepts rather than every learner. Large transcript retrieval returns bounded spans. Jobs can be resumed from checkpoints instead of restarting a lecture or course import.

A cache miss affects performance, not correctness. If an asynchronous projection is temporarily stale, a decision either recomputes the small required state synchronously, waits for the known event watermark, or clearly reports pending analysis. It must not confidently recommend practice based on evidence it knows has been superseded.

### Observability and privacy

Propagate a request ID through generation, grading, evidence, and planning. Keep structured reason codes, input revisions, job progress, and safe error metadata. Restrict full prompt and transcript diagnostics to authorized operators with explicit retention and audit. Never log authentication headers, Canvas credentials, signed download links, or raw audio by default.

Alerts cover stuck jobs, expired leases, repeated provider errors, missing recording units, unusual challenge rates, growing transcription lag, failed projection updates, and synchronization errors. Admin repair tools can retry a job, reindex a source, or replay a projection with an audit trail; they cannot silently fabricate learner evidence.

### Backups recovery and deployment

Back up the relational database and object metadata with a documented recovery plan. Validate restoration of a recording manifest plus its objects and restoration of evidence plus projections. Rebuildable indexes and projections should have verified rebuild commands. Pin and document runtime dependencies and supported platform configurations.

Database migrations run in dependency order and are tested on representative existing data. Expand schema before switching readers. A failed rollout can switch application readers back while preserving newly written durable observations. Keep compatibility until the rollback window ends. Do not rely on an irreversible destructive migration to make the new schema work.

## Completion and integration

Deliver the service and data changes, the user-facing behavior described above, recovery paths, migration compatibility, and evidence for the relevant [acceptance criteria](ACCEPTANCE_AND_USER_JOURNEYS.md). Passing an isolated unit test or adding an endpoint does not establish integrated completion.

Platform reference numbers in the source requirements resolve through [technical references](TECHNICAL_REFERENCES.md).
