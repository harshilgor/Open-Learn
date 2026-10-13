"""Bounded executor for learner-owned document tasks.

The current executor is intentionally deterministic and extractive.  It is a
real task/tool boundary, not a hidden model call: every read and write is
recorded, and the only write tool delegates to ``LearnerStateService``.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Iterable
from uuid import uuid4

from .agent_models import (
    AgentDocument,
    AgentDocumentCreate,
    AgentTask,
    AgentTaskCreate,
    AgentTaskEvent,
    AgentTaskResult,
    AgentTaskStatus,
    AgentTaskStep,
)
from .models import utc_now
from .state_models import NoteCreate, StateEventCreate
from .state_service import LearnerStateService
from .storage import Store


class AgentTaskError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")
_STOP_WORDS = frozenset({
    "about", "after", "again", "also", "because", "being", "between", "could", "document", "during",
    "each", "from", "have", "into", "more", "most", "other", "should", "that", "their", "there",
    "these", "this", "those", "through", "under", "using", "what", "when", "where", "which", "with",
    "would", "your", "than", "then", "them", "they", "will", "were", "been", "does", "such",
})


def _compact_text(content: str) -> str:
    return re.sub(r"[ \t]+", " ", content.replace("\r\n", "\n")).strip()


def _sentences(content: str) -> list[str]:
    compact = _compact_text(content)
    chunks = _SENTENCE_BOUNDARY.split(compact)
    return [chunk.strip(" \n-•") for chunk in chunks if len(chunk.strip(" \n-•")) >= 24]


def _key_terms(texts: Iterable[str]) -> list[str]:
    counts = Counter(
        word.lower() for text in texts for word in _WORD.findall(text)
        if word.lower() not in _STOP_WORDS
    )
    return [word for word, _ in counts.most_common(6)]


def _build_note(document_title: str, content: str, goal: str, style: str) -> tuple[str, str]:
    candidates = _sentences(content)
    if not candidates:
        compact = _compact_text(content)
        candidates = [compact[:900]] if compact else ["The document did not contain extractable text."]
    key_points = candidates[: min(6, len(candidates))]
    summary = " ".join(candidates[: min(3, len(candidates))])[:1400]
    terms = _key_terms(candidates)
    lines = [f"# {document_title}", "", "## Task", goal, "", "## Extractive summary", summary, "", "## Key points"]
    lines.extend(f"- {point}" for point in key_points)
    if style == "study":
        lines.extend(["", "## Study prompts"])
        if terms:
            lines.extend(f"- Explain the role of **{term}** in your own words." for term in terms[:4])
        else:
            lines.append("- Restate the main idea without looking at the source.")
    lines.extend([
        "", "## Source boundary",
        "- This note is an extractive, deterministic draft from the attached text. It does not add source verification or mastery evidence.",
    ])
    body = "\n".join(lines)
    return body[:20_000], summary


class AgentTaskService:
    """Creates durable tasks and runs the allowed local tool sequence."""

    def __init__(self, store: Store):
        self.store = store

    def create_document(self, learner_id: str, request: AgentDocumentCreate) -> AgentDocument:
        now = utc_now()
        content = request.content.replace("\r\n", "\n").strip()
        if not content:
            raise AgentTaskError("document_empty", "Document text cannot be blank.", 422)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        document = AgentDocument(
            id=f"doc_{uuid4().hex}", learner_id=learner_id, title=request.title, mime_type=request.mime_type,
            character_count=len(content), content_sha256=digest, created_at=now,
        )
        # LearnerStateService owns learner registration so all learner-owned
        # records share one identity lifecycle.
        with self.store.transaction() as connection:
            LearnerStateService(self.store)._ensure_learner(connection, learner_id)
        self.store.save_agent_document(document, content)
        return document

    def get_document(self, learner_id: str, document_id: str) -> AgentDocument:
        document = self.store.get_agent_document(document_id, learner_id)
        if document is None:
            raise AgentTaskError("document_not_found", "Document does not exist for this learner.", 404)
        return document[0]

    def list_documents(self, learner_id: str) -> list[AgentDocument]:
        return self.store.list_agent_documents(learner_id)

    def create_task(self, learner_id: str, request: AgentTaskCreate, idempotency_key: str | None = None) -> AgentTask:
        if idempotency_key:
            existing = self.store.get_agent_task_by_idempotency(learner_id, idempotency_key)
            if existing is not None:
                return existing
        for document_id in request.document_ids:
            if self.store.get_agent_document(document_id, learner_id) is None:
                raise AgentTaskError("document_not_found", "Every task document must belong to this learner.", 404)
        now = utc_now()
        task = AgentTask(
            id=f"task_{uuid4().hex}", learner_id=learner_id, kind=request.kind, goal=request.goal,
            document_ids=request.document_ids, note_style=request.note_style, note_scope=request.note_scope,
            status=AgentTaskStatus.queued, created_at=now, updated_at=now,
        )
        self.store.save_agent_task(task, idempotency_key)
        self._event(task.id, 0, "task.queued", {"kind": task.kind.value, "documentIds": task.document_ids})
        return task

    def run_task(self, learner_id: str, task_id: str) -> AgentTask:
        task = self.get_task(learner_id, task_id)
        if task.status in {AgentTaskStatus.completed, AgentTaskStatus.failed, AgentTaskStatus.cancelled}:
            return task
        try:
            task = self._update(task, status=AgentTaskStatus.planning)
            self._event(task.id, 1, "task.planned", {"tools": ["read_owned_document", "extract_key_points", "create_learner_note"]})
            documents = []
            for document_id in task.document_ids:
                document = self.store.get_agent_document(document_id, learner_id)
                if document is None:
                    raise AgentTaskError("document_not_found", "A task document is no longer available to this learner.", 409)
                documents.append(document)
            task = self._update(
                task,
                status=AgentTaskStatus.running,
                steps=[AgentTaskStep(tool="read_owned_document", status="completed", detail=f"Read {len(documents)} owned document(s).")],
            )
            self._event(task.id, 2, "tool.completed", {
                "tool": "read_owned_document",
                "documents": [{"id": document.id, "title": document.title} for document, _ in documents],
            })
            # A note uses the first document as its canonical database anchor;
            # every selected source is combined for extraction and retained in
            # provenance, so a multi-document task does not silently ignore
            # the later attachments.
            document, _ = documents[0]
            combined_title = document.title if len(documents) == 1 else f"Study notes: {document.title} + {len(documents) - 1} more"
            combined_content = "\n\n".join(content for _, content in documents)
            body, summary = _build_note(combined_title, combined_content, task.goal, task.note_style)
            task = self._update(task, steps=[
                *task.steps,
                AgentTaskStep(tool="extract_key_points", status="completed", detail="Produced an extractive summary and source-derived study prompts."),
            ])
            self._event(task.id, 3, "tool.completed", {
                "tool": "extract_key_points", "documentId": document.id, "title": combined_title,
            })
            note = LearnerStateService(self.store).create_note(learner_id, NoteCreate(
                scope=task.note_scope,
                body=body,
                document_id=document.id,
                provenance={
                    "source": "agent_task", "taskId": task.id, "documentId": document.id,
                    "contentSha256": document.content_sha256,
                    "sourceDocuments": [{"id": item.id, "contentSha256": item.content_sha256} for item, _ in documents],
                    "method": "extractive_deterministic_v1",
                },
            ))
            task = self._update(task, steps=[
                *task.steps,
                AgentTaskStep(tool="create_learner_note", status="completed", detail="Created a learner-owned note with a document anchor."),
            ])
            self._event(task.id, 4, "tool.completed", {"tool": "create_learner_note", "noteId": note.id})
            result = AgentTaskResult(
                note_id=note.id, document_ids=task.document_ids, summary=summary,
                limitations=[
                    "Extractive deterministic draft; no external retrieval or source verification was performed.",
                    "The task did not update learner evidence or mastery.",
                    "The note is database-anchored to the first selected document; all selected documents are retained in provenance.",
                ] if len(documents) > 1 else [
                    "Extractive deterministic draft; no external retrieval or source verification was performed.",
                    "The task did not update learner evidence or mastery.",
                ],
            )
            task = self._update(task, status=AgentTaskStatus.completed, result=result)
            self._event(task.id, 5, "task.completed", {"noteId": note.id, "documentIds": task.document_ids})
            LearnerStateService(self.store).append_event(learner_id, StateEventCreate(
                kind="agent_task.completed", action_id=task.id,
                idempotency_key=f"agent-task-completed:{task.id}",
                payload={"taskId": task.id, "noteId": note.id, "documentIds": task.document_ids},
                provenance={"source": "agent_task_service", "method": "extractive_deterministic_v1"},
            ))
            return task
        except AgentTaskError:
            raise
        except Exception as exc:
            failed = self._update(task, status=AgentTaskStatus.failed, error_code="agent_task_failed")
            self._event(failed.id, 99, "task.failed", {"code": "agent_task_failed", "detail": str(exc)})
            raise AgentTaskError("agent_task_failed", "Agent task failed; retry is safe.", 500) from exc

    def get_task(self, learner_id: str, task_id: str) -> AgentTask:
        task = self.store.get_agent_task(task_id, learner_id)
        if task is None:
            raise AgentTaskError("task_not_found", "Agent task does not exist for this learner.", 404)
        return task

    def list_tasks(self, learner_id: str, limit: int = 50) -> list[AgentTask]:
        return self.store.list_agent_tasks(learner_id, limit)

    def list_events(self, learner_id: str, task_id: str) -> list[AgentTaskEvent]:
        self.get_task(learner_id, task_id)
        return self.store.list_agent_task_events(task_id)

    def cancel_task(self, learner_id: str, task_id: str) -> AgentTask:
        task = self.get_task(learner_id, task_id)
        if task.status in {AgentTaskStatus.completed, AgentTaskStatus.failed, AgentTaskStatus.cancelled}:
            return task
        cancelled = self._update(task, status=AgentTaskStatus.cancelled)
        self._event(task.id, 98, "task.cancelled", {"reason": "learner_cancelled"})
        return cancelled

    def _update(self, task: AgentTask, **changes: object) -> AgentTask:
        updated = task.model_copy(update={**changes, "updated_at": utc_now()})
        self.store.save_agent_task(updated)
        return updated

    def _event(self, task_id: str, sequence: int, event_type: str, data: dict[str, object]) -> None:
        self.store.save_agent_task_event(AgentTaskEvent(
            id=f"agent_event_{uuid4().hex}", task_id=task_id, sequence=sequence,
            type=event_type, data=data, created_at=utc_now(),
        ))
