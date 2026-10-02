# Foundation decisions and operating boundaries

## Execution ownership

Extend `learning_jobs` and `WorkflowStore`; do not replace quiz IDs, attempts,
generation records or existing note revision ownership. Interactive HTTP and
streaming stay in the API. Durable workers share the same application modules.

`OPENLEARN_WORKER_MODE=local` (default) runs one interactive and one batch polling
thread. `external` disables those pollers; run the worker commands below. Existing
legacy whole-recording startup recovery still uses its own executor and is an
outstanding migration boundary. Invalid worker mode configuration fails startup.

```
python -m backend.app.execution_worker --queue interactive
python -m backend.app.execution_worker --queue batch
python -m backend.app.execution_worker --queue interactive --once
```

Each claim is a conditional UPDATE, which acquires the supported SQLite writer
boundary and atomically admits one worker. PostgreSQL also executes that UPDATE
atomically; this implementation does not claim a tested high-throughput
SKIP LOCKED learning-job dispatcher. The outbox dispatcher uses SKIP LOCKED on
PostgreSQL and BEGIN IMMEDIATE on SQLite for its short transaction.

Completion requires matching owner, running state, non-cancelled flag, live
lease, lease token and input revision. A failing completion inside the owning
command transaction rolls back its attempt/activity writes. Input revision
captures job inputs; domain services must still compare their current entity
revision, as existing quiz/note services do. This field alone does not prove
that a source is current.

Heartbeats never revive an expired lease. Claims increment attempts. Expired
final attempts become terminal failures. Explicit transient failure schedules
bounded exponential backoff with jitter. Authentication, permissions and invalid
files are not automatically retried. Existing domain executors still determine
their own errors; migrate their classification explicitly rather than treating
every ModelProviderError as transient.

## Transactional follow-up and watermarks

`WorkflowStore.enqueue(..., connection=conn)` permits canonical data and a
follow-up job to commit together. Lecture chunk metadata and its transcription
job now use it. Durable binary storage finishes before acknowledgment; failed
database insertion cleans up its newly written object. A process crash between
object write and database insertion can leave an orphan object, requiring future
audited cleanup; it cannot acknowledge missing manifest metadata.

`ExecutionOutbox.append` joins the owning command transaction. Delivery handlers
may only mutate durable state or enqueue a job within the supplied connection;
they must not perform external provider calls. A handler failure rolls back its
effects and acknowledgment. Other delivery topics require explicitly registered
consumers; unsupported topics remain pending. `execution.enqueue` is supported.
These are at-least-once contracts, not exactly-once external execution.

Watermarks compare both event sequence and reducer revision. A stale or missing
watermark produces `analysis_pending`, never a conclusion of unknown knowledge.
Downstream projections must adopt these checks before claiming shared-state
consistency.

## Immutable binary storage

The `ImmutableObjects` protocol separates authorized domain services from binary
storage. Local writes fsync bytes and atomically create a hard link; an existing
key must have identical content. POSIX directories are also fsynced. Existing
lecture locations remain unchanged through the shared local adapter.

`S3ImmutableObjects` takes an injected maintained SDK client and private bucket;
runtime IAM supplies credentials. Conditional `IfNoneMatch="*"` prevents
overwrite, and SHA-256 metadata/checks validate duplicates and reads. A 412 is
accepted only after matching existing bytes. Other errors propagate for the
durable caller to classify. This follows the [S3 conditional-write contract](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).

S3 is adapter-tested with a simulator, not exercised against a real bucket.
The existing lecture download path and remaining binary services are local-only
compatibility consumers. No environment toggle silently redirects existing
recordings to an empty bucket. Storage-location metadata, migration, recovery,
authorized downloads and real SDK integration remain required before switching.
No public URLs, signed credentials or raw content are emitted in worker logs.

## Evidence and decisions

Capabilities distinguish recognition, recall, explanation, procedure and
transfer. Observation categories distinguish assessment, assistance, exposure,
coverage, self-report, skip and correction. Assistance with revealed answers,
hints, worked solutions or disclosed help cannot be recorded as observed
independence. Missing historical assistance remains unknown.

Quality, strength, hypothesis support and academic confidence are distinct enums.
No numeric threshold or probability of mastery is added. New contracts do not
change the existing reducer or promote legacy evidence; that migration is
unfinished and needs labeled-history comparison.

Decision records freeze the policy, context manifest, graph, learner and academic
snapshot revisions and source/evaluation dependencies. They are immutable through
the service. Corrections append owner-scoped invalidations against specific
dependency revisions. A newer source does not rewrite an older decision. Domain
producers are responsible for verifying all dependencies before saving; a
decision store is not a substitute for source authorization.

## Identity and privacy boundary

Development profile headers are not verified identity. Hosted API calls fail
closed because several legacy routes still lack an owner boundary and there is
no configured verified-principal implementation. This gate is deliberately not
an authentication provider. Local user-facing services remain available.

Legacy local export/delete were device-wide despite a learner-scoped URL.
They now validate a single profile under the same SQLite writer lock and reject
mixed-profile databases before reading or deleting data. Foreign keys remain
enabled; deletion runs in dependency order. Account-scoped packages, complete
authored-file privacy handling, deletion tombstones, in-flight stage fencing and
deletion-aware backup restores still require the identity/privacy work package.

## Platform and release decisions still required

The baseline supports local Python/React operation and Electron packaging. This
branch's acceptance execution is Linux/SQLite with synthetic providers. Native
iOS/Android background recording and the complete browser matrix are pending
deliverables, not excluded requirements. Hosted PostgreSQL, OIDC, storage and
Canvas configuration and all production latency/quality targets remain explicit
release gates. No unmeasured target or educational threshold is invented here.
