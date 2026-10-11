# P05–P07 capacity and cutover

## Capacity envelope

One API process (five connections) and five serial worker processes (two each)
plus the backup cron's one connection use at most 16 pooled connections.
Two complete service generations conservatively use 32;
two migration connections and 20 reserved for auth/platform/operations yield
54 of the observed 60-connection database limit. Six remain unallocated.
This is a planning envelope, not a load qualification. No replicas may be
added without rerunning `check_connection_budget` with their actual count.
HTTP concurrency is bounded at 128, including long-lived streams. Provider
work does not hold a database connection for its entire duration. Existing
worker lease and serial tick behavior remain unchanged. Pool overflow is zero.

Long-lived SQLAlchemy services should use the IPv4 session pooler or direct
Postgres when IPv6 is supported. Keep migration advisory locks on a direct
or session connection; transaction pooling is not approved for migration or
future LISTEN consumers. The live URL was verified through a redacted dashboard
read: Supabase session pooler, port 5432. No listener exists in this stage.
URL passwords must never appear in reports. The free embedded API keeps a
ten-second pool wait after the three-second candidate caused admission failures
in the real workload. Its live override is OPENLEARN_DB_POOL_TIMEOUT_SECONDS=10.

## Probe contract

`/live` and `/health` report process liveness without database/provider work.
`/ready` coalesces dependency checks for three seconds and uses the existing
shared pool. Pool acquisition and connection creation have three-second limits;
the readiness SQL statement has a one-second server timeout. Network failures
after socket establishment can take longer than these individual limits.
Schema compatibility fails startup in Store; `/release` rechecks schema for
explicit deployment gates. `/health/web-evidence` remains the deep diagnostic.
Render should use `/live` to avoid restarting healthy processes during a
database outage; release promotion must still gate on `/ready` and `/release`.

## Replacement services

The paid blueprint uses Virginia, an API Standard instance (1 CPU / 2 GB), and
five Starter workers (0.5 CPU / 512 MB each). Preliminary listed compute cost:
$25 + five × $7 = $60/month, excluding provider use, cron, bandwidth, tax and
database upgrades. These sizes need memory/CPU measurement before qualification.
Supabase quota remediation and backup/restore coverage are required before
cutover; do not delete user data to fit the free tier. The user chose to keep
hosting free on October 10. No paid services or upgrades have been provisioned.

## Ordered cutover and rollback

1. Activate observability on the current endpoint; record successful chat,
   context follow-up, note save/revision conflict, queue and pool measurements.
2. Obtain approval for recurring compute and database costs. Create a Virginia
   replacement with the same reviewed commit. Copy existing service variables
   through the hosting platform, preserving all feature flags and tariffs.
3. Provision the shared production environment group before applying the
   blueprint. Do not provision duplicate cron/notification consumers.
4. Hold replacement consumers stopped. Drain active API-owned generations and
   old embedded jobs; stop old embedded consumers before starting replacements.
   Confirm lease ownership and terminal job counts. Generation execution remains
   inside the API until P14; do not claim this release externalizes it.
5. Deploy external workers at the reviewed commit, then the replacement API
   with external worker mode. Verify readiness, schema and required capabilities.
6. Rebuild frontend with both public and proxy API origins pointing to the
   replacement; stage, pair-gate SHA/origin fingerprint, then promote.
7. Repeat the same measured workload. Verify no lost notes, duplicate side
   effects, expired leases or ownership failures before retiring the old service.
8. Exercise rollback: drain replacements, stop replacement consumers, restore
   old consumers with compatible schema, then restore the matching frontend
   release/origin. Never run two unfenced embedded consumer fleets. Never
   downgrade schema during rollback. Keep the old endpoint until this succeeds.

Provisioning, hosted workload qualification and rollback remain pending until
the live evidence is recorded. The blueprint alone does not complete P07.
