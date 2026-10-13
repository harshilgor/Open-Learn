from uuid import uuid4

from fastapi.testclient import TestClient

try:
    from backend.app.main import app
except ModuleNotFoundError:
    from app.main import app


client = TestClient(app)


def _headers(learner_id: str) -> dict[str, str]:
    return {"X-Dev-Learner-Id": learner_id}


def _document(learner_id: str, title: str = "Feedback loops.md") -> dict:
    response = client.post(
        f"/v1/learners/{learner_id}/documents",
        headers=_headers(learner_id),
        json={
            "title": title,
            "mimeType": "text/markdown",
            "content": (
                "# Feedback loops\n\nA feedback loop returns part of a system's output as a future input. "
                "Reinforcing loops amplify a change, while balancing loops counteract change. "
                "Delays can make the visible effect arrive after the original action."
            ),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_document_task_creates_a_versioned_document_anchored_note_and_audit_events():
    learner_id = f"agent-{uuid4().hex}"
    document = _document(learner_id)
    task_response = client.post(
        f"/v1/learners/{learner_id}/agent-tasks",
        headers={**_headers(learner_id), "Idempotency-Key": "summarize-feedback-loops"},
        json={
            "goal": "Create study notes from this reading",
            "documentIds": [document["id"]],
            "noteStyle": "study",
        },
    )
    assert task_response.status_code == 202, task_response.text
    accepted = task_response.json()
    assert accepted["status"] == "queued"
    task = client.get(
        f"/v1/learners/{learner_id}/agent-tasks/{accepted['id']}", headers=_headers(learner_id)
    ).json()
    assert task["status"] == "completed"
    assert task["result"]["noteId"]
    assert task["steps"][-1]["tool"] == "create_learner_note"

    notes = client.get(f"/v1/learners/{learner_id}/notes", headers=_headers(learner_id)).json()
    assert len(notes) == 1
    assert notes[0]["id"] == task["result"]["noteId"]
    assert notes[0]["documentId"] == document["id"]
    assert "## Extractive summary" in notes[0]["body"]
    assert "## Study prompts" in notes[0]["body"]
    assert notes[0]["provenance"]["taskId"] == task["id"]

    events = client.get(
        f"/v1/learners/{learner_id}/agent-tasks/{task['id']}/events", headers=_headers(learner_id)
    ).json()
    assert [event["sequence"] for event in events] == list(range(6))
    assert events[-1]["type"] == "task.completed"

    # Writing a note is learner activity, not evidence of understanding.
    state = client.get(f"/v1/learners/{learner_id}/state", headers=_headers(learner_id)).json()
    assert state["states"] == []


def test_agent_task_idempotency_does_not_duplicate_the_note():
    learner_id = f"agent-retry-{uuid4().hex}"
    document = _document(learner_id)
    body = {"goal": "Summarize this", "documentIds": [document["id"]]}
    first = client.post(
        f"/v1/learners/{learner_id}/agent-tasks", headers={**_headers(learner_id), "Idempotency-Key": "stable-task"}, json=body
    )
    second = client.post(
        f"/v1/learners/{learner_id}/agent-tasks", headers={**_headers(learner_id), "Idempotency-Key": "stable-task"}, json=body
    )
    assert first.status_code == second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    notes = client.get(f"/v1/learners/{learner_id}/notes", headers=_headers(learner_id)).json()
    assert len(notes) == 1


def test_agent_documents_and_tasks_are_learner_scoped():
    owner = f"agent-owner-{uuid4().hex}"
    other = f"agent-other-{uuid4().hex}"
    document = _document(owner)
    forbidden = client.post(
        f"/v1/learners/{other}/agent-tasks",
        headers=_headers(other),
        json={"goal": "Try another learner's document", "documentIds": [document["id"]]},
    )
    assert forbidden.status_code == 404
    mismatch = client.get(f"/v1/learners/{owner}/documents", headers=_headers(other))
    assert mismatch.status_code == 403
