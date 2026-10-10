import json

from sqlalchemy import create_engine, text

from backend.app.storage import Store
from backend.app.session_models import SessionSummary
from backend.app.models import utc_now


def test_history_preview_is_bounded_owner_scoped_and_excludes_private_answers():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    store = Store.__new__(Store)
    store.engine = engine
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE practice_records (id TEXT, owner_id TEXT, payload TEXT)"))
        connection.execute(text("INSERT INTO practice_records VALUES (:id, :owner, :payload)"), {
            "id": "journey_chat", "owner": "alice", "payload": json.dumps({"turns": [
                {"question": "First question", "lesson": {"answer": "PRIVATE SOLUTION"}},
                {"question": "  Last\n question " + "x" * 300, "answer": "PRIVATE ANSWER"},
            ]})})
    metadata = store.journey_history_metadata("alice", "chat")
    assert metadata["turn_count"] == 2
    assert metadata["preview"].startswith("Last question ")
    assert len(metadata["preview"]) <= 180
    assert metadata["preview"].endswith("…")
    assert "PRIVATE" not in metadata["preview"]
    summary = SessionSummary(id="chat", title="Physics", updated_at=utc_now(), **metadata).to_summary_dict()
    assert summary["preview"] == metadata["preview"]
    assert summary["turnCount"] == 2
    assert "preview" not in SessionSummary(id="empty", title="New chat", updated_at=utc_now()).to_summary_dict()
    assert store.journey_history_metadata("bob", "chat") == {"turn_count": 0, "preview": None}
    engine.dispose()
