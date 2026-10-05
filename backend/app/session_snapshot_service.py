"""Server-authoritative learning-session snapshot and guarded pointer updates."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text

from .material_service import problem
from .models import utc_now
from .session_models import (
    LearningSession,
    SessionPositionUpdate,
    SessionSnapshot,
    SessionTurnSummary,
)


def _object(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    return json.loads(value) if isinstance(value, str) else value


class SessionSnapshotService:
    def __init__(self, store: Any):
        self.store = store

    @staticmethod
    def advance_authority(
        connection: Connection,
        *,
        session_id: str,
        owner: str,
        concept_id: str | None = None,
        lesson_id: str | None = None,
    ) -> int:
        row = connection.execute(text("""
            SELECT payload,authority_revision,state_version
            FROM learning_sessions
            WHERE id=:session AND learner_id=:owner
        """), {"session": session_id, "owner": owner}).mappings().first()
        if row is None:
            problem("session_not_found", "This learning session is not available.", 404)
        session = LearningSession.model_validate_json(row["payload"])
        revision = int(row["authority_revision"] or session.authority_revision or session.state_version or 1) + 1
        update = {
            "authority_revision": revision,
            "state_version": revision,
            "updated_at": utc_now(),
        }
        if concept_id is not None:
            update["current_concept_id"] = concept_id
        if lesson_id is not None:
            update["current_lesson_id"] = lesson_id
        updated = session.model_copy(update=update)
        connection.execute(text("""
            UPDATE learning_sessions
            SET authority_revision=:revision,state_version=:revision,
                current_concept_id=:concept,current_lesson_id=:lesson,
                updated_at=:updated,payload=:payload
            WHERE id=:session AND learner_id=:owner
        """), {
            "revision": revision,
            "concept": updated.current_concept_id,
            "lesson": updated.current_lesson_id,
            "updated": updated.updated_at,
            "payload": updated.model_dump_json(),
            "session": session_id,
            "owner": owner,
        })
        return revision

    def get(self, owner: str, session_id: str) -> SessionSnapshot:
        session = self.store.get_session(session_id)
        if session is None or session.learner_id != owner:
            problem("session_not_found", "This learning session is not available.", 404)
        with self.store.engine.connect() as connection:
            journey_row = connection.execute(text("""
                SELECT revision,payload FROM practice_records
                WHERE id=:id AND owner_id=:owner AND kind='journey'
            """), {"id": f"journey_{session_id}", "owner": owner}).mappings().first()
            generation = connection.execute(text("""
                SELECT id,status FROM generation_records
                WHERE owner_id=:owner AND session_id=:session
                  AND status NOT IN ('completed','cancelled','failed')
                ORDER BY updated_at DESC LIMIT 1
            """), {"owner": owner, "session": session_id}).mappings().first()
            jobs = connection.execute(text("""
                SELECT id FROM learning_jobs
                WHERE owner_id=:owner AND target_id=:session
                  AND status IN ('queued','running')
                LIMIT 1
            """), {"owner": owner, "session": session_id}).mappings().first()
            branches = connection.execute(text("""
                SELECT id FROM branches
                WHERE learner_id=:owner AND session_id=:session AND lifecycle='open'
                ORDER BY updated_at DESC LIMIT 1
            """), {"owner": owner, "session": session_id}).mappings().first()
            recommendation = connection.execute(text("""
                SELECT id FROM recommendation_sets
                WHERE owner_id=:owner AND session_id=:session AND status='current'
                ORDER BY created_at DESC LIMIT 1
            """), {"owner": owner, "session": session_id}).mappings().first()
            quiz_id = None
            if session.active_quiz_id:
                quiz_id = connection.execute(text("""
                    SELECT id FROM practice_records
                    WHERE id=:id AND owner_id=:owner AND kind='quiz'
                      AND history_session_id=:session
                      AND (history_status IS NULL OR history_status NOT IN ('completed','cancelled'))
                """), {"id": session.active_quiz_id, "owner": owner, "session": session_id}).scalar_one_or_none()
            if not quiz_id:
                quiz_id = connection.execute(text("""
                    SELECT id FROM practice_records
                    WHERE owner_id=:owner AND kind='quiz' AND history_session_id=:session
                      AND (history_status IS NULL OR history_status NOT IN ('completed','cancelled'))
                    ORDER BY history_created_at DESC,id DESC LIMIT 1
                """), {"owner": owner, "session": session_id}).scalar_one_or_none()
            review_id = None
            if session.active_review_id:
                review_id = connection.execute(text("""
                    SELECT id FROM practice_records
                    WHERE id=:id AND owner_id=:owner AND kind='review_session'
                      AND history_session_id=:session AND history_status IN ('ready','in_progress')
                """), {"id": session.active_review_id, "owner": owner, "session": session_id}).scalar_one_or_none()
            if not review_id:
                review_id = connection.execute(text("""
                    SELECT id FROM practice_records
                    WHERE owner_id=:owner AND kind='review_session' AND history_session_id=:session
                      AND history_status IN ('ready','in_progress')
                    ORDER BY history_created_at DESC,id DESC LIMIT 1
                """), {"owner": owner, "session": session_id}).scalar_one_or_none()

        journey = _object(journey_row["payload"]) if journey_row else {
            "mode": "ask",
            "status": "new",
            "position": 0,
            "steps": [],
            "turns": [],
        }
        steps = journey.get("steps") or []
        position = min(int(journey.get("position") or 0), max(0, len(steps) - 1))
        step = steps[position] if steps else {}
        turns = journey.get("turns") or []
        last = next((turn for turn in reversed(turns) if turn.get("lesson")), None)
        lesson = (last or {}).get("lesson") or {}
        last_turn = None
        if last:
            last_turn = SessionTurnSummary(
                index=turns.index(last),
                lesson_id=lesson.get("id"),
                concept_id=lesson.get("conceptId"),
                mode=last.get("mode"),
            )
        return SessionSnapshot(
            session=session,
            revision=session.authority_revision,
            mode=journey.get("mode") or "ask",
            journey_status=journey.get("status") or "new",
            journey_revision=int(journey_row["revision"]) if journey_row else 1,
            journey_position=position,
            current_concept_id=step.get("conceptId") or lesson.get("conceptId") or session.current_concept_id,
            current_lesson_id=lesson.get("id") or session.current_lesson_id,
            current_branch_id=session.current_branch_id or (branches["id"] if branches else None),
            active_generation_id=session.active_generation_id or (generation["id"] if generation else None),
            active_generation_status=generation["status"] if generation else None,
            active_quiz_id=quiz_id,
            active_review_id=review_id,
            active_job_id=session.active_job_id or (jobs["id"] if jobs else None),
            current_recommendation_set_id=recommendation["id"] if recommendation else None,
            last_committed_turn=last_turn,
        )

    def update(self, owner: str, session_id: str, command: SessionPositionUpdate) -> SessionSnapshot:
        supplied = command.model_dump(exclude={"expected_revision"}, exclude_unset=True)
        with self.store.transaction() as connection:
            row = connection.execute(text("""
                SELECT payload,authority_revision FROM learning_sessions
                WHERE id=:session AND learner_id=:owner
            """), {"session": session_id, "owner": owner}).mappings().first()
            if row is None:
                problem("session_not_found", "This learning session is not available.", 404)
            session = LearningSession.model_validate_json(row["payload"])
            current_revision = int(row["authority_revision"] or session.authority_revision or 1)
            if current_revision != command.expected_revision:
                problem("stale_session", "The session changed; reload it before continuing.", 409)
            if supplied.get("current_concept_id") is not None:
                graph = self.store.get_graph(session.graph_id)
                if graph is None or supplied["current_concept_id"] not in {concept.id for concept in graph.concepts}:
                    problem("concept_not_in_session", "The concept is not part of this session.", 409)
            revision = current_revision + 1
            updated = session.model_copy(update={
                **supplied,
                "authority_revision": revision,
                "state_version": revision,
                "updated_at": utc_now(),
            })
            connection.execute(text("""
                UPDATE learning_sessions SET
                    current_concept_id=:concept,current_lesson_id=:lesson,
                    current_branch_id=:branch,active_generation_id=:generation,
                    active_quiz_id=:quiz,active_review_id=:review,active_job_id=:job,
                    authority_revision=:revision,state_version=:revision,
                    updated_at=:updated,payload=:payload
                WHERE id=:session AND learner_id=:owner AND authority_revision=:expected
            """), {
                "concept": updated.current_concept_id,
                "lesson": updated.current_lesson_id,
                "branch": updated.current_branch_id,
                "generation": updated.active_generation_id,
                "quiz": updated.active_quiz_id,
                "review": updated.active_review_id,
                "job": updated.active_job_id,
                "revision": revision,
                "updated": updated.updated_at,
                "payload": updated.model_dump_json(),
                "session": session_id,
                "owner": owner,
                "expected": current_revision,
            })
        return self.get(owner, session_id)
