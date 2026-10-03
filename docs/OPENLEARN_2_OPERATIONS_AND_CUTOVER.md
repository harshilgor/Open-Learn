# Open Learn 2.0 operations and migration runbook

This runbook describes the implementation in this branch as of checkpoint `8d16a05` plus ongoing feature work. Recheck the live branch, migration head, provider configuration, and deployment matrix before executing any production procedure. A passing local SQLite check does not establish hosted PostgreSQL or object-store recovery.

## Deployment profiles

| Profile | Database | Worker | Binary storage | Identity |
| --- | --- | --- | --- | --- |
| Desktop/local | SQLite | Embedded worker by default; set `OPENLEARN_WORKER_MODE=external` only when supervising a separate worker | Local immutable object adapter or existing compatible paths | Local principal; linking to an account requires configured OIDC |
| Hosted | PostgreSQL (`DATABASE_URL`) | Separate supervised `python -m backend.app.worker` process | S3-compatible adapter configured with least-privilege bucket access | Verified OIDC issuer/audience/JWKS; development headers are not accepted |

Hosted API replicas must not each run independent embedded workers. The worker and API must use the same database and object store. Do not enable a workflow based only on the presence of a route; verify its required services, ownership checks, and recovery behavior first.

## Before an upgrade

1. Freeze writes or schedule a maintenance window for production cutover.
2. Record the deployed application commit and supported rollback commit.
3. Create a database backup and an object-store inventory using the provider's supported tools. Verify restore into an isolated environment.
4. Run the content-free application inventory on the source database and file roots:

   ```powershell
   python -m backend.app.migration_inventory --output openlearn-before.json
   ```

5. Confirm the migration graph has one head and review the SQL for the full chain:

   ```powershell
   python -m alembic -c backend/alembic.ini heads
   python -m alembic -c backend/alembic.ini history --verbose
   ```

6. Run the migrations against a disposable copy of representative existing data. Confirm foreign-key relationships, row counts, checksums, and existing activity IDs before and after.
7. Never combine migration files from independently authored branches solely because revision numbers match. Resolve ancestry and schema differences first.

## Apply and verify migrations

For a disposable local database, point `FORMA_DB_PATH` at a new test path before starting the application. The application `Store` upgrades to the current head when constructed, so do not point a verification command at a valuable database unless the verified pre-upgrade backup is available.

```powershell
$env:AI_TUTOR_ENV = 'test'
$env:FORMA_DB_PATH = 'backend/data/openlearn-migration-check.db'
$env:DATABASE_URL = 'sqlite+pysqlite:///./backend/data/openlearn-migration-check.db'
python -m alembic -c backend/alembic.ini upgrade head
python -m alembic -c backend/alembic.ini current
python -m backend.app.migration_inventory --output openlearn-after.json
```

Compare the two inventory reports by table counts, total rows, per-table owner counts, file counts/bytes, and content-set hashes. The report includes no owner labels or account identifiers. Do not treat matching aggregates as sufficient proof: inspect representative IDs and relationships in the disposable database through the migration validation suite. Keep a signed or otherwise access-controlled copy of the reports because cross-table counts can reveal usage patterns.

The migration inventory command is read-only and does not instantiate `Store`; it never applies migrations. It does not verify row-level semantic mappings, media decodability, or provider operation.

## Worker operations

Run a single polling pass when diagnosing a disposable environment:

```powershell
python -m backend.app.worker --once
```

Run under a process supervisor in hosted environments. Monitor job age, expired leases, retries, cancellation, outbox delivery, projection watermarks, provider errors, recording gaps, and owner deletion state. Worker exceptions should be visible as safe reason codes; do not log tokens, raw prompts, notes, transcripts, signed URLs, or audio.

Before retrying a failed job, check that its owner remains active, its input revision is current, and the failure is retryable. Replaying a job must use its idempotency key. Do not repair the database by inserting learning observations manually.

## Backup, restore, and deletion

- Use the account-scoped export workflow for hosted account data and local backup for a local installation. These archives have different ownership and restore rules.
- Restore first into an isolated database and object prefix. Verify checksums, row counts, ownership, note revisions, recordings, and pending-job fences before exposing the restored environment.
- A restore must not revive deleted accounts, grants, or jobs. Reapply deletion tombstones/fences and verify object cleanup before opening traffic.
- Account deletion must fence new writes and workers, delete owned database records and objects, and leave other accounts unchanged. Verify with two-account fixtures.
- Keep provider credentials in the operating system or deployment secret manager. They are not application backup contents.

Do not use irreversible object-store lifecycle deletion until the account/object inventory and recovery window have been reviewed. A logical deletion that leaves stale content eligible for retrieval is also incomplete.

## Incident recovery

### Database migration failure

Stop API and worker processes, retain logs with secrets removed, restore the verified pre-migration backup into a new database, and point the rollback build at that restored database. Do not attempt an unreviewed downgrade on production. Preserve the failed database for diagnosis.

### Provider outage or stuck job

Keep interactive requests separate from batch ingestion. Allow bounded retries only for transient transport failures; authorization/configuration failures require operator or user action. After provider recovery, resume from durable checkpoints and verify the resulting revision before advancing projections.

### Recording object missing or checksum mismatch

Retain the manifest and gap report, stop transcript finalization for affected intervals, and recover from the source device or backup. Do not fill a missing interval with guessed transcript text. Verify the same object hash and sequence before acknowledging a retry.

## Release gates

Before hosted cutover, record actual p50/p95 latency, provider cost, resource limits, queue capacity, and recovery objectives for each supported deployment profile. Require one migration head, PostgreSQL concurrency tests, object restore tests, OIDC and device revocation checks, complete user journeys, accessible recovery states, and reviewed educational quality results. Demonstration thresholds remain shadowed until labeled histories support admission. Missing delayed outcomes are reported as missing, not failure or success.

The local inventory and deterministic synthetic evaluation are engineering aids. They do not substitute for deployed restore drills, institution-specific Canvas validation, native mobile capture testing, or expert educational review.
