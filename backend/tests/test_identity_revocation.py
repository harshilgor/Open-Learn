import time
from io import BytesIO

import pytest
from sqlalchemy import text

from backend.app.identity_revocation import (
    InMemoryRevocationJournal,
    RevocationGateError,
    S3RevocationJournal,
    account_deletion_record,
    device_revocation_record,
    reconcile_identity_snapshot,
)


def _tables(*, status="active", data=True):
    tables = {
        "identity_accounts": [{"id": "alice", "status": status, "deleted_at": None, "display_name": "Alice"}],
        "identity_devices": [{"id": "device_one", "owner_id": "alice", "revoked_at": None}],
        "workspace_notes": [],
    }
    if data:
        tables["workspace_notes"].append({"id": "note_one", "owner_id": "alice"})
    return tables


def test_identity_restore_is_disabled_without_explicit_operator_enablement():
    journal = InMemoryRevocationJournal("2020-01-01T00:00:00Z")
    with pytest.raises(RevocationGateError, match="operator enables"):
        reconcile_identity_snapshot(_tables(), archive_created_at="2026-10-01T00:00:00Z", journal=journal, enabled=False)
    with pytest.raises(RevocationGateError, match="independent revocation journal"):
        reconcile_identity_snapshot(_tables(), archive_created_at="2026-10-01T00:00:00Z", journal=None, enabled=True)


def test_restore_requires_complete_journal_coverage_before_snapshot_time():
    journal = InMemoryRevocationJournal("2026-10-02T00:00:00Z")
    with pytest.raises(RevocationGateError, match="predates"):
        reconcile_identity_snapshot(_tables(), archive_created_at="2026-10-01T00:00:00Z", journal=journal, enabled=True)
    journal.fail_reads = True
    with pytest.raises(RevocationGateError, match="read failed"):
        reconcile_identity_snapshot(_tables(), archive_created_at="2026-10-03T00:00:00Z", journal=journal, enabled=True)


def test_account_deleted_after_snapshot_blocks_old_content_restore():
    journal = InMemoryRevocationJournal("2020-01-01T00:00:00Z", (account_deletion_record("alice", 1791504000),))
    with pytest.raises(RevocationGateError, match="predates an account deletion"):
        reconcile_identity_snapshot(_tables(status="active", data=True), archive_created_at="2026-10-01T00:00:00Z", journal=journal, enabled=True)


def test_tombstoned_account_without_owned_content_is_reconcilable():
    record = account_deletion_record("alice", 1791504000)
    journal = InMemoryRevocationJournal("2020-01-01T00:00:00Z", (record,))
    tables = _tables(status="deleted", data=False)
    tables["identity_devices"] = []
    reconcile_identity_snapshot(tables, archive_created_at="2026-10-10T00:00:00Z", journal=journal, enabled=True)
    assert tables["identity_accounts"][0]["status"] == "deleted"


def test_device_revocation_is_applied_to_staged_restore_rows():
    record = device_revocation_record("alice", "device_one", 1791504000)
    journal = InMemoryRevocationJournal("2020-01-01T00:00:00Z", (record,))
    tables = _tables(data=False)
    reconcile_identity_snapshot(tables, archive_created_at="2026-10-03T00:00:00Z", journal=journal, enabled=True)
    assert tables["identity_devices"][0]["revoked_at"] == 1791504000


def test_account_erasure_appends_hashed_tombstone_to_injected_authority(tmp_path):
    from backend.app.identity_data import erase_owner
    from backend.app.storage import Store

    store = Store(tmp_path / "openlearn.db")
    try:
        with store.transaction() as conn:
            conn.execute(text(
                "INSERT INTO identity_accounts(id,subject_hash,display_name,status,created_at) VALUES('alice','subject','Alice','active',:now)"),
                {"now": time.time()})
        journal = InMemoryRevocationJournal("2020-01-01T00:00:00Z")
        erase_owner(store, "alice", revocation_journal=journal)
        snapshot = journal.read_snapshot()
        assert len(snapshot.records) == 1
        record = snapshot.records[0]
        assert record.kind == "account_deleted" and "alice" not in str(record.as_dict())
        with store.engine.connect() as conn:
            row = conn.execute(text("SELECT status FROM identity_accounts WHERE id='alice'")).scalar_one()
        assert row == "deleted"
    finally:
        store.close()


def test_s3_authority_requires_separate_bucket_and_explicit_coverage(monkeypatch):
    for name in ("OPENLEARN_REVOCATION_JOURNAL_BUCKET", "OPENLEARN_REVOCATION_JOURNAL_PREFIX", "OPENLEARN_REVOCATION_JOURNAL_COVERAGE_START"):
        monkeypatch.delenv(name, raising=False)
    assert S3RevocationJournal.from_environment() is None
    monkeypatch.setenv("OPENLEARN_REVOCATION_JOURNAL_BUCKET", "app-bucket")
    monkeypatch.setenv("OPENLEARN_REVOCATION_JOURNAL_PREFIX", "revocations")
    monkeypatch.setenv("OPENLEARN_REVOCATION_JOURNAL_COVERAGE_START", "2026-01-01T00:00:00Z")
    monkeypatch.setenv("OPENLEARN_ASSISTANT_S3_BUCKET", "app-bucket")
    with pytest.raises(RevocationGateError, match="separate from application objects"):
        S3RevocationJournal.from_environment()


def test_s3_adapter_appends_and_reads_immutable_hashed_records():
    class Client:
        def __init__(self):
            self.objects = {}

        def put_object(self, **request):
            key = request["Key"]
            if key in self.objects:
                raise AssertionError("unexpected overwrite attempt")
            self.objects[key] = request["Body"]

        def list_objects_v2(self, **request):
            prefix = request["Prefix"]
            return {"IsTruncated": False, "Contents": [{"Key": key} for key in self.objects if key.startswith(prefix)]}

        def get_object(self, **request):
            return {"Body": BytesIO(self.objects[request["Key"]])}

    client = Client()
    journal = S3RevocationJournal(client, "separate-journal-bucket", "revocations", "2020-01-01T00:00:00Z")
    record = device_revocation_record("alice", "device_one", 1791504000)
    journal.append(record)
    snapshot = journal.read_snapshot()
    assert snapshot.complete and snapshot.records == (record,)
    assert next(iter(client.objects)).startswith("revocations/records/")
    assert b"alice" not in next(iter(client.objects.values()))

    class TruncatedClient(Client):
        def list_objects_v2(self, **request):
            return {"IsTruncated": True, "Contents": []}

    class UnavailableClient(Client):
        def list_objects_v2(self, **request):
            raise OSError("test read failure")

    with pytest.raises(RevocationGateError, match="pagination ended unexpectedly"):
        S3RevocationJournal(TruncatedClient(), "journal", "revocations", "2020-01-01T00:00:00Z").read_snapshot()
    with pytest.raises(RevocationGateError, match="could not be fully read"):
        S3RevocationJournal(UnavailableClient(), "journal", "revocations", "2020-01-01T00:00:00Z").read_snapshot()
