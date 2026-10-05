"""Small lexical note candidate retriever for optional Ask/Learn context."""
from __future__ import annotations

import re
import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .workspace_note_service import WorkspaceNoteService, WorkspaceNoteError
from .semantic_retrieval import configured_model, note_similarity_scores

STOP = {"about", "after", "again", "could", "does", "from", "have", "into", "just", "know", "more", "please", "that", "their", "them", "there", "these", "this", "what", "when", "where", "which", "with", "would", "your"}


def retrieve_relevant_notes(store, owner: str, query: str, course_id: str | None,
                            explicit_ids: set[str], limit: int = 2,
                            recently_referenced_ids: set[str] | None = None) -> list[dict]:
    terms = [term for term in dict.fromkeys(re.findall(r"[a-zA-Z0-9]{4,}", query.lower())) if term not in STOP][:8]
    service = WorkspaceNoteService(store)
    candidates = {}
    recent_ids = (recently_referenced_ids or set()) - explicit_ids
    for term in terms:
        for summary in service.search(owner, term, limit=10):
            if summary.id in explicit_ids:
                continue
            note_course = summary.frontmatter.get("course_id") or summary.frontmatter.get("courseId")
            if note_course != course_id:
                continue
            score = candidates.setdefault(summary.id, {"summary": summary, "score": 0})
            score["score"] += 2 if term in summary.title.lower() else 1
    if recent_ids:
        for summary in service.list(owner):
            note_course = summary.frontmatter.get("course_id") or summary.frontmatter.get("courseId")
            if summary.id in recent_ids and note_course == course_id:
                candidates.setdefault(summary.id, {"summary": summary, "score": 0})["score"] += 1
    semantic_scores = {}
    model = configured_model()
    if model:
        try:
            eligible = [summary for summary in service.list(owner)
                        if summary.id not in explicit_ids and
                        (summary.frontmatter.get("course_id") or summary.frontmatter.get("courseId")) == course_id]
            if len(eligible) <= 32:
                records = [service.get(owner, summary.id) for summary in eligible]
                semantic_scores = note_similarity_scores(store, query, records, model)
                for summary in eligible:
                    candidates.setdefault(summary.id, {"summary": summary, "score": 0})
        except (httpx.HTTPError, SQLAlchemyError, WorkspaceNoteError, ValueError, KeyError, TypeError, OSError):
            semantic_scores = {}
    lexical_max = max((item["score"] for item in candidates.values()), default=0)
    def relevance(item: dict) -> float:
        return (0.55 * item["score"] / lexical_max if lexical_max else 0) + \
            0.45 * max(0, semantic_scores.get(item["summary"].id, 0))

    selected = sorted(candidates.values(), key=lambda item: (-relevance(item), item["summary"].id))
    selected = [item for item in selected if item["score"] or semantic_scores.get(item["summary"].id, 0) > 0.15][:limit]
    results = []
    for item in selected:
        note = service.get(owner, item["summary"].id)
        if not note.body.strip():
            continue
        lower = note.body.lower()
        matches = [lower.find(term) for term in terms if lower.find(term) >= 0]
        start = max(0, min(matches) - 250) if matches else 0
        results.append({"noteId": note.id, "title": note.title, "revision": note.revision,
                        "text": note.body[start:start + 1400],
                        "relevanceScore": round(relevance(item), 3),
                        "retrieval": "hybrid_embedding" if semantic_scores else "lexical"})
    if terms and len(results) < limit and getattr(store, "engine", None) is not None:
        with store.engine.connect() as connection:
            blocks = connection.execute(text("""SELECT b.title,b.content,b.evidence_json,r.note_id,r.title AS recording_title,r.course_id,n.revision
                FROM lecture_note_blocks b JOIN lecture_recordings r ON r.id=b.recording_id
                JOIN workspace_notes n ON n.id=r.note_id AND n.learner_id=r.learner_id
                WHERE r.learner_id=:owner AND r.status='completed' AND r.generation_version=b.generation_version
                  AND ((CAST(:course AS VARCHAR) IS NULL AND r.course_id IS NULL) OR r.course_id=:course)
                ORDER BY r.updated_at DESC,b.ordinal LIMIT 500"""), {"owner": owner, "course": course_id}).mappings().all()
        ranked = sorted(((sum(term in (row["title"] + " " + row["content"]).lower() for term in terms), row) for row in blocks), key=lambda item: item[0], reverse=True)
        used = {item["noteId"] for item in results} | explicit_ids
        for score, row in ranked:
            if score <= 0 or row["note_id"] in used:
                continue
            used.add(row["note_id"])
            results.append({"noteId": row["note_id"], "title": row["recording_title"], "revision": row["revision"],
                            "text": f"Lecture note: {row['title']}\n{row['content']}\nTranscript evidence: {row['evidence_json']}"[:1400],
                            "relevanceScore": round(score / len(terms), 3), "retrieval": "lecture_evidence"})
            if len(results) >= limit:
                break
    return results
