# Agent live acceptance

Acceptance work started 4 October 2026, before milestone 4 implementation.
Authoritative plan: `Open Learn 2.0/26_agent_execution_platform.md`.

## Verified

- Live Daytona adapter acceptance passed in 9.81 seconds with SDK 0.220.0 and snapshot `openlearn-csv-v1-20261004`. Real create/stage/execute/download/delete produced independently validated PNG, XLSX, CSV and JSON (6,874 bytes total). Immutable LocalObjectStore copies were re-read and hash-checked after compute deletion. A bounded listing retry confirmed provider absence. Receipt and outputs: `work/daytona-live-acceptance-20261004-run4/`. Reproduce with `backend/.venv/Scripts/python.exe -m backend.scripts.agent_daytona_acceptance --snapshot openlearn-csv-v1-20261004 --output work/<new-directory>`.
- Created the named snapshot from `daytonaio/sandbox:0.9.0` with 1 CPU, 1 GiB memory and 3 GiB disk, preparing `/workspace` ownership for the non-root `daytona` user. Reproducible image definition: `backend/scripts/daytona-csv.Dockerfile`. Updated server `.env` snapshot and enabled flag without displaying or changing the key. The snapshot remains available; temporary sandbox compute was deleted. Snapshot immutability/publisher digest, measured billing and hosted task/API acceptance remain unverified.
- Earlier base-image runs failed because the non-root user could not create `/workspace`; subsequent listing confirmed those sandboxes absent. The first derived-image attempt failed uploading through the restricted execution environment's refused loopback proxy and verified cleanup. The final run succeeded outside that restriction after permission review. No sandbox network policy was relaxed.
- Live Exa search contract: 1 passed in 4.48 seconds using the configured server credential. Command from repository root: `$env:RUN_LIVE_EXA_TESTS='true'; & backend/.venv/Scripts/python.exe -m pytest backend/tests/test_live_exa.py -q --tb=short -p no:cacheprovider -p no:tmpdir`.
- Strengthened and reran the live contract: 1 passed in 2.57 seconds. It now requires nonempty search results, checks per-source excerpt/result limits, and opens a returned source through the live Exa contents API. Provider client cleanup runs in `finally`. This still does not prove the full research task/citation/retention journey; full live research acceptance remains open.

## Pending configuration and evidence

- Daytona hosted integration: adapter acceptance is verified above; the full deployed task/API, ownership and S3-backed artifact journey remains pending hosted configuration.
- Hosted PostgreSQL: no PostgreSQL `DATABASE_URL` configured; psycopg absent from the current backend environment. Need a disposable hosted test database before migration, concurrent reservation/lease, and recovery checks. Do not run destructive acceptance against user data.
- S3: object backend remains local, with no configured bucket. Need a dedicated test bucket and server-side access before immutable write/read/hash/delete and lifecycle verification. Ambient authentication availability has not been tested.
- Hosted authentication/reconnect: no hosted deployment was verified in this run.

Configuration inventory printed presence indicators only, with no credential values. Daytona snapshot/temporary resources are described above; no PostgreSQL/S3 infrastructure was created. Existing working-tree changes were preserved. The user confirmed the authoritative plan and chose to configure the services first. Milestone 4 implementation therefore remains held until the preceding live acceptance checks can be completed.
