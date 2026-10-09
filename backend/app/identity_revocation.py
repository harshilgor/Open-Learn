"""Independent revocation journal and fail-closed restore reconciliation.

The journal is intentionally external to the application database. Restore of
identity-bearing snapshots is disabled unless an operator explicitly enables
it and supplies a complete, readable journal with a declared coverage start.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Literal, Protocol


class RevocationGateError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _utc(value: str | datetime) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RevocationGateError("invalid_revocation_coverage", "The revocation journal coverage timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise RevocationGateError("invalid_revocation_coverage", "The revocation journal coverage timestamp must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _hash(kind: str, value: str) -> str:
    return hashlib.sha256(("openlearn-revocation-v1\0" + kind + "\0" + value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RevocationRecord:
    record_id: str
    kind: Literal["account_deleted", "device_revoked"]
    owner_hash: str
    occurred_at: str
    device_hash: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"recordId": self.record_id, "kind": self.kind, "ownerHash": self.owner_hash,
                "deviceHash": self.device_hash, "occurredAt": self.occurred_at}

    @classmethod
    def parse(cls, value: Any) -> "RevocationRecord":
        if not isinstance(value, dict):
            raise RevocationGateError("invalid_revocation_record", "The revocation journal contains an invalid record.")
        kind, owner_hash, device_hash = value.get("kind"), value.get("ownerHash"), value.get("deviceHash")
        if kind not in {"account_deleted", "device_revoked"}:
            raise RevocationGateError("invalid_revocation_record", "The revocation journal contains an unknown record kind.")
        if not isinstance(owner_hash, str) or len(owner_hash) != 64 or any(c not in "0123456789abcdef" for c in owner_hash):
            raise RevocationGateError("invalid_revocation_record", "The revocation journal owner digest is malformed.")
        if kind == "device_revoked" and (not isinstance(device_hash, str) or len(device_hash) != 64 or any(c not in "0123456789abcdef" for c in device_hash)):
            raise RevocationGateError("invalid_revocation_record", "The revocation journal device digest is malformed.")
        if kind == "account_deleted" and device_hash is not None:
            raise RevocationGateError("invalid_revocation_record", "Account revocations cannot name a device digest.")
        occurred_at = _utc(value.get("occurredAt")).isoformat()
        record_id = value.get("recordId")
        if not isinstance(record_id, str) or len(record_id) != 64:
            raise RevocationGateError("invalid_revocation_record", "The revocation journal record id is malformed.")
        canonical = {"kind": kind, "ownerHash": owner_hash, "deviceHash": device_hash,
                     "occurredAt": occurred_at}
        expected_id = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if record_id != expected_id:
            raise RevocationGateError("invalid_revocation_record", "The revocation journal record checksum does not match its content.")
        return cls(record_id, kind, owner_hash, occurred_at, device_hash)


@dataclass(frozen=True)
class RevocationSnapshot:
    coverage_start: datetime
    records: tuple[RevocationRecord, ...]
    complete: bool


class RevocationJournal(Protocol):
    def append(self, record: RevocationRecord) -> None: ...
    def read_snapshot(self) -> RevocationSnapshot: ...


def account_deletion_record(owner_id: str, occurred_at: float | None = None) -> RevocationRecord:
    timestamp = datetime.fromtimestamp(occurred_at, timezone.utc) if occurred_at is not None else datetime.now(timezone.utc)
    owner_hash = _hash("owner", owner_id)
    payload = {"kind": "account_deleted", "ownerHash": owner_hash, "deviceHash": None, "occurredAt": timestamp.isoformat()}
    record_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return RevocationRecord(record_id, "account_deleted", owner_hash, timestamp.isoformat())


def device_revocation_record(owner_id: str, device_id: str, occurred_at: float | None = None) -> RevocationRecord:
    timestamp = datetime.fromtimestamp(occurred_at, timezone.utc) if occurred_at is not None else datetime.now(timezone.utc)
    owner_hash, device_hash = _hash("owner", owner_id), _hash("device", device_id)
    payload = {"kind": "device_revoked", "ownerHash": owner_hash, "deviceHash": device_hash, "occurredAt": timestamp.isoformat()}
    record_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return RevocationRecord(record_id, "device_revoked", owner_hash, timestamp.isoformat(), device_hash)


class S3RevocationJournal:
    """Append-only object journal in its own bucket; requires an operator-set coverage boundary."""
    def __init__(self, client: Any, bucket: str, prefix: str, coverage_start: str | datetime):
        self.client, self.bucket = client, bucket
        self.prefix = prefix.strip("/")
        if not self.prefix:
            raise RevocationGateError("invalid_revocation_journal_config", "The revocation journal needs a dedicated object prefix.")
        self.coverage_start = _utc(coverage_start)

    @classmethod
    def from_environment(cls) -> "S3RevocationJournal | None":
        bucket = os.getenv("OPENLEARN_REVOCATION_JOURNAL_BUCKET", "").strip()
        prefix = os.getenv("OPENLEARN_REVOCATION_JOURNAL_PREFIX", "").strip("/")
        coverage = os.getenv("OPENLEARN_REVOCATION_JOURNAL_COVERAGE_START", "").strip()
        if not bucket and not prefix and not coverage:
            return None
        if not bucket or not prefix or not coverage:
            raise RevocationGateError("invalid_revocation_journal_config", "Set the journal bucket, prefix, and coverage start together.")
        application_buckets = {os.getenv(name, "").strip() for name in ("OPENLEARN_OBJECT_BUCKET", "OPENLEARN_ASSISTANT_S3_BUCKET")}
        if bucket in application_buckets - {""}:
            raise RevocationGateError("invalid_revocation_journal_config", "The revocation journal must use a bucket separate from application objects.")
        try:
            import boto3
            client = boto3.client("s3", region_name=os.getenv("OPENLEARN_REVOCATION_JOURNAL_REGION") or None)
        except Exception as exc:
            raise RevocationGateError("revocation_journal_unavailable", "The external revocation journal client could not be initialized.") from exc
        return cls(client, bucket, prefix, coverage)

    def append(self, record: RevocationRecord) -> None:
        body = json.dumps(record.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        key = f"{self.prefix}/records/{record.record_id}.json"
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/json", IfNoneMatch="*")
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = str(response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
            if code == "412":
                existing = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
                if existing == body:
                    return
            raise RevocationGateError("revocation_journal_write_failed", "The external revocation journal did not confirm the record.") from exc

    def read_snapshot(self) -> RevocationSnapshot:
        records: list[RevocationRecord] = []
        token = None
        try:
            while True:
                request = {"Bucket": self.bucket, "Prefix": f"{self.prefix}/records/"}
                if token:
                    request["ContinuationToken"] = token
                page = self.client.list_objects_v2(**request)
                for item in page.get("Contents", []):
                    response = self.client.get_object(Bucket=self.bucket, Key=item["Key"])
                    raw = response["Body"].read()
                    value = json.loads(raw.decode("utf-8"))
                    record = RevocationRecord.parse(value)
                    if item["Key"] != f"{self.prefix}/records/{record.record_id}.json":
                        raise RevocationGateError("invalid_revocation_record", "A journal record does not match its immutable object key.")
                    records.append(record)
                    if len(records) > 100_000:
                        raise RevocationGateError("revocation_journal_too_large", "The revocation journal exceeds the bounded restore scan limit.")
                if not page.get("IsTruncated"):
                    break
                token = page.get("NextContinuationToken")
                if not token:
                    raise RevocationGateError("revocation_journal_incomplete", "The revocation journal pagination ended unexpectedly.")
        except RevocationGateError:
            raise
        except Exception as exc:
            raise RevocationGateError("revocation_journal_unavailable", "The external revocation journal could not be fully read.") from exc
        return RevocationSnapshot(self.coverage_start, tuple(records), True)


def configured_revocation_journal() -> RevocationJournal | None:
    return S3RevocationJournal.from_environment()


def reconcile_identity_snapshot(tables: dict[str, list[dict[str, Any]]], *, archive_created_at: str,
                                journal: RevocationJournal | None, enabled: bool) -> None:
    """Validate journal authority and apply device revocations to staged restore rows.

    An account-deletion record against a snapshot that still contains active
    account data blocks restore; callers must use safe content-only import or
    an operator-reviewed cleanup. The helper never revives deleted content.
    """
    if not enabled:
        raise RevocationGateError("identity_restore_disabled", "Identity-bearing restore is disabled until an operator enables the external revocation gate.")
    if journal is None:
        raise RevocationGateError("revocation_journal_required", "Identity-bearing restore needs the independent revocation journal.")
    snapshot = journal.read_snapshot()
    if not snapshot.complete:
        raise RevocationGateError("revocation_journal_incomplete", "The external revocation journal did not confirm a complete read.")
    archive_time = _utc(archive_created_at)
    if archive_time < _utc(snapshot.coverage_start):
        raise RevocationGateError("revocation_coverage_gap", "This backup predates the external journal's declared complete-coverage window.")
    account_rows = tables.get("identity_accounts", [])
    device_rows = tables.get("identity_devices", [])
    accounts = {_hash("owner", str(row.get("id"))): row for row in account_rows if row.get("id")}
    devices = {_hash("device", str(row.get("id"))): row for row in device_rows if row.get("id")}
    tombstone_tables = {"identity_accounts", "identity_object_cleanup", "browser_provider_cleanup", "agent_sandbox_cleanup"}
    for record in snapshot.records:
        if record.kind == "account_deleted":
            account = accounts.get(record.owner_hash)
            if account is None:
                continue
            if account.get("status") != "deleted":
                raise RevocationGateError("restore_contains_deleted_account", "The backup predates an account deletion and still contains that account; restore is blocked.")
            for table_name, rows in tables.items():
                if table_name in tombstone_tables:
                    continue
                for row in rows:
                    owner_id = row.get("owner_id", row.get("learner_id", row.get("owner_learner_id")))
                    if owner_id and _hash("owner", str(owner_id)) == record.owner_hash:
                        raise RevocationGateError("restore_contains_deleted_account_data", "The backup still contains data for a deleted account; restore is blocked.")
        elif record.kind == "device_revoked":
            device = devices.get(record.device_hash or "")
            if device is None:
                continue
            if _hash("owner", str(device.get("owner_id", ""))) != record.owner_hash:
                raise RevocationGateError("revocation_owner_mismatch", "A device revocation does not match the restored device owner.")
            device["revoked_at"] = min(float(device.get("revoked_at") or float("inf")), _utc(record.occurred_at).timestamp())


class InMemoryRevocationJournal:
    """Deterministic test adapter. Never selected by production configuration."""
    def __init__(self, coverage_start: str | datetime, records: tuple[RevocationRecord, ...] = ()):
        self.coverage_start = _utc(coverage_start)
        self.records = {record.record_id: record for record in records}
        self.fail_reads = False
        self.fail_writes = False

    def append(self, record: RevocationRecord) -> None:
        if self.fail_writes:
            raise RevocationGateError("revocation_journal_write_failed", "The test journal write failed.")
        previous = self.records.get(record.record_id)
        if previous and previous != record:
            raise RevocationGateError("revocation_journal_conflict", "The journal record id has conflicting content.")
        self.records[record.record_id] = record

    def read_snapshot(self) -> RevocationSnapshot:
        if self.fail_reads:
            raise RevocationGateError("revocation_journal_unavailable", "The test journal read failed.")
        return RevocationSnapshot(self.coverage_start, tuple(self.records.values()), True)
