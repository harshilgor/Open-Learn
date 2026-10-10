"""Persistence adapter shared by the modular-monolith services.

The adapter keeps the original method surface while moving connection and
dialect concerns behind SQLAlchemy. New state services use ``transaction`` to
commit canonical state, evidence, and audit events atomically.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, text

from .database import create_database_engine, run_migrations
from .models import GraphJob, GraphVersion, TopicScope, utc_now
from .policy_models import PolicyValidationResult, TeachingPlan
from .session_models import ActionEvent, LearningSession, LessonArtifact, RunStatus, short_title


class Store:
    def __init__(self, location: str | Path):
        raw = str(location)
        if "://" in raw:
            self.url = raw
        elif raw == ":memory:":
            self.url = "sqlite+pysqlite:///file:ai_tutor_memdb?mode=memory&cache=shared&uri=true"
        else:
            self.url = f"sqlite+pysqlite:///{Path(raw).resolve()}"
        import os
        if os.getenv('OPENLEARN_MIGRATE_ON_START','true')=='false':
            from .database import require_current_schema
            require_current_schema(self.url)
        else:run_migrations(self.url)
        self.engine: Engine = create_database_engine(self.url)

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.begin() as connection:
            from .execution import active_job
            from .workflow_store import WorkflowStore
            job = active_job.get()
            if job is not None:
                WorkflowStore(self).validate_lease(connection, job)
            from .identity import principal_context, assert_principal_active
            principal = principal_context.get()
            if principal:
                assert_principal_active(connection, principal)
            yield connection
            if principal:
                assert_principal_active(connection, principal)
            if job is not None:
                status = connection.execute(text("SELECT status FROM learning_jobs WHERE id=:id"), {"id": job["id"]}).scalar_one_or_none()
                if status == "running":
                    WorkflowStore(self).validate_lease(connection, job)

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _put(connection: Connection, table: str, key_column: str, key: str, values: dict[str, Any]) -> None:
        exists = connection.execute(
            text(f"SELECT 1 FROM {table} WHERE {key_column} = :key"), {"key": key}
        ).first()
        if exists:
            assignments = ", ".join(f"{column} = :{column}" for column in values)
            connection.execute(
                text(f"UPDATE {table} SET {assignments} WHERE {key_column} = :key"),
                {**values, "key": key},
            )
        else:
            insert_values = {key_column: key, **values}
            columns = ", ".join(insert_values)
            parameters = ", ".join(f":{column}" for column in insert_values)
            connection.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({parameters})"), insert_values)

    def save_scope(self, scope: TopicScope) -> None:
        with self.transaction() as connection:
            from .identity import grant_resource
            grant_resource(connection, "topic_scopes", scope.id)
            self._put(connection, "topic_scopes", "id", scope.id, {"payload": scope.model_dump_json()})

    def get_scope(self, scope_id: str) -> TopicScope | None:
        with self.engine.connect() as connection:
            from .identity import authorize_resource
            authorize_resource(connection, "topic_scopes", scope_id)
            row = connection.execute(text("SELECT payload FROM topic_scopes WHERE id = :id"), {"id": scope_id}).mappings().first()
        return TopicScope.model_validate_json(row["payload"]) if row else None

    def save_job(self, job: GraphJob) -> None:
        with self.transaction() as connection:
            from .identity import grant_resource
            grant_resource(connection, "graph_jobs", job.id)
            self._put(connection, "graph_jobs", "id", job.id, {"scope_id": job.scope_id, "payload": job.model_dump_json()})

    def get_job(self, job_id: str) -> GraphJob | None:
        with self.engine.connect() as connection:
            from .identity import authorize_resource
            authorize_resource(connection, "graph_jobs", job_id)
            row = connection.execute(text("SELECT payload FROM graph_jobs WHERE id = :id"), {"id": job_id}).mappings().first()
        return GraphJob.model_validate_json(row["payload"]) if row else None

    def save_graph(self, graph: GraphVersion) -> None:
        with self.transaction() as connection:
            from .identity import grant_resource
            grant_resource(connection, "graph_versions", graph.id)
            self._put(connection, "graph_versions", "id", graph.id, {"scope_id": graph.scope_id, "payload": graph.model_dump_json()})

    def get_graph(self, graph_id: str) -> GraphVersion | None:
        with self.engine.connect() as connection:
            from .identity import authorize_resource
            authorize_resource(connection, "graph_versions", graph_id)
            row = connection.execute(text("SELECT payload FROM graph_versions WHERE id = :id"), {"id": graph_id}).mappings().first()
        return GraphVersion.model_validate_json(row["payload"]) if row else None

    def save_session(self, session: LearningSession) -> None:
        with self.transaction() as connection:
            from .buddy_service import BuddyService
            previous=connection.execute(text('SELECT buddy_id FROM buddy_chats WHERE id=:id AND owner_id=:owner'), {'id':session.id,'owner':session.learner_id}).scalar_one_or_none()
            buddy=previous or BuddyService(self).resolve(connection,session.learner_id,session.course_id,session.buddy_id)
            session=session.model_copy(update={'buddy_id':buddy})
            self._put(connection, "learning_sessions", "id", session.id, {
                "graph_id": session.graph_id,
                "learner_id": session.learner_id,
                "course_id": session.course_id,
                "current_concept_id": session.current_concept_id,
                "current_lesson_id": session.current_lesson_id,
                "state_version": session.state_version,
                "authority_revision": session.authority_revision,
                "current_branch_id": session.current_branch_id,
                "active_generation_id": session.active_generation_id,
                "active_quiz_id": session.active_quiz_id,
                "active_review_id": session.active_review_id,
                "active_job_id": session.active_job_id,
                "updated_at": session.updated_at,
                "payload": session.model_dump_json(),
            })
            connection.execute(text('INSERT INTO buddy_chats(id,owner_id,buddy_id) VALUES(:id,:owner,:buddy) ON CONFLICT(id) DO NOTHING'), {'id':session.id,'owner':session.learner_id,'buddy':buddy})

    def get_session(self, session_id: str) -> LearningSession | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT payload FROM learning_sessions WHERE id = :id"), {"id": session_id}).mappings().first()
        from .identity import principal_context, fail
        principal = principal_context.get()
        if row and principal and LearningSession.model_validate_json(row["payload"]).learner_id != principal.owner_id:
            fail('session_not_found', 'Session not found.', 404)
        return LearningSession.model_validate_json(row["payload"]) if row else None

    def list_sessions(self, owner: str, limit: int = 50, offset: int = 0) -> tuple[list[LearningSession], int]:
        """Newest-first conversation metadata for one learner. Payloads are parsed
        but only session-level fields are returned by the history endpoint."""
        with self.engine.connect() as connection:
            total = connection.execute(
                text("SELECT COUNT(*) FROM learning_sessions WHERE learner_id = :owner"), {"owner": owner}
            ).scalar_one()
            rows = connection.execute(
                text("SELECT payload FROM learning_sessions WHERE learner_id = :owner "
                     "ORDER BY updated_at DESC NULLS LAST LIMIT :limit OFFSET :offset"),
                {"owner": owner, "limit": limit, "offset": offset},
            ).mappings().all()
        return ([LearningSession.model_validate_json(row["payload"]) for row in rows], int(total))

    def journey_turn_count(self, owner: str, session_id: str) -> int:
        return self.journey_history_metadata(owner, session_id)["turn_count"]

    def journey_history_metadata(self, owner: str, session_id: str) -> dict:
        """Bounded learner-message preview; never expose lesson or answer content."""
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM practice_records WHERE id = :id AND owner_id = :owner"),
                {"id": f"journey_{session_id}", "owner": owner},
            ).mappings().first()
        if row is None:
            return {"turn_count": 0, "preview": None}
        try:
            turns = json.loads(row["payload"]).get("turns", [])
            if not isinstance(turns, list):
                return {"turn_count": 0, "preview": None}
            preview = next((turn.get("question") for turn in reversed(turns)
                            if isinstance(turn, dict) and isinstance(turn.get("question"), str)
                            and turn["question"].strip()), None)
            if preview:
                preview = " ".join(preview.split())
                preview = preview[:177] + "…" if len(preview) > 180 else preview
            return {"turn_count": len(turns), "preview": preview}
        except (ValueError, AttributeError):
            return {"turn_count": 0, "preview": None}

    def rename_session(self, session_id: str, owner: str, title: str) -> LearningSession | None:
        session = self.get_session(session_id)
        if session is None or session.learner_id != owner:
            return None
        updated = session.model_copy(update={"title": title, "updated_at": utc_now()})
        self.save_session(updated)
        return updated

    def touch_session_in(self, connection: Connection, session_id: str, owner: str, first_question: str | None = None) -> None:
        """Refresh recency (and backfill a missing title) inside the caller's transaction."""
        row = connection.execute(
            text("SELECT payload FROM learning_sessions WHERE id = :id"), {"id": session_id}
        ).mappings().first()
        if row is None:
            return
        session = LearningSession.model_validate_json(row["payload"])
        if session.learner_id != owner:
            return
        update: dict[str, Any] = {"updated_at": utc_now()}
        if not (session.title or "").strip() and (first_question or "").strip():
            update["title"] = short_title(first_question)
        updated = session.model_copy(update=update)
        connection.execute(
            text("UPDATE learning_sessions SET payload = :payload, updated_at = :updated_at WHERE id = :id"),
            {"id": session_id, "payload": updated.model_dump_json(), "updated_at": updated.updated_at},
        )

    def delete_session(self, session_id: str, owner: str) -> bool:
        """Remove a conversation and everything scoped to it.

        Quizzes are deliberately preserved: they own assessment evidence with an
        independent lifecycle and remain readable without their source session.
        Learning jobs are left to fail safe on their next poll.
        """
        session = self.get_session(session_id)
        if session is None or session.learner_id != owner:
            return False
        journey_id = f"journey_{session_id}"
        with self.transaction() as connection:
            from .in_class_service import invalidate_material_access
            invalidate_material_access(
                connection, session_id=session_id, owner=owner,
                session_course_id=None, update_session_course=True,
            )
            action_ids = connection.execute(
                text("SELECT id FROM learning_actions WHERE session_id = :sid"), {"sid": session_id}
            ).scalars().all()
            for action_id in action_ids:
                connection.execute(text("DELETE FROM action_events WHERE action_id = :id"), {"id": action_id})
                connection.execute(text("DELETE FROM policy_validation_results WHERE action_id = :id"), {"id": action_id})
                connection.execute(text("DELETE FROM teaching_plans WHERE action_id = :id"), {"id": action_id})
            connection.execute(text("DELETE FROM learning_actions WHERE session_id = :sid"), {"sid": session_id})
            connection.execute(text("DELETE FROM lesson_artifacts WHERE session_id = :sid"), {"sid": session_id})
            connection.execute(text("DELETE FROM material_attachments WHERE session_id = :sid"), {"sid": session_id})
            connection.execute(
                text("DELETE FROM context_records WHERE session_id = :sid AND owner_id = :owner"),
                {"sid": session_id, "owner": owner},
            )
            connection.execute(
                text("DELETE FROM generation_records WHERE session_id = :sid AND owner_id = :owner"),
                {"sid": session_id, "owner": owner},
            )
            set_ids = connection.execute(
                text("SELECT id FROM recommendation_sets WHERE session_id = :sid AND owner_id = :owner"),
                {"sid": session_id, "owner": owner},
            ).scalars().all()
            for set_id in set_ids:
                rec_ids = connection.execute(
                    text("SELECT id FROM next_action_recommendations WHERE set_id = :set"), {"set": set_id}
                ).scalars().all()
                for rec_id in rec_ids:
                    connection.execute(
                        text("DELETE FROM recommendation_interactions WHERE recommendation_id = :id"), {"id": rec_id}
                    )
                connection.execute(
                    text("DELETE FROM next_action_recommendations WHERE set_id = :set"), {"set": set_id}
                )
            connection.execute(
                text("DELETE FROM recommendation_sets WHERE session_id = :sid AND owner_id = :owner"),
                {"sid": session_id, "owner": owner},
            )
            connection.execute(
                text("DELETE FROM practice_records WHERE owner_id = :owner AND kind IN ('journey', 'note_draft', 'note_proposal') "
                     "AND (id = :jid OR parent_id = :sid)"),
                {"owner": owner, "jid": journey_id, "sid": session_id},
            )
            connection.execute(text('DELETE FROM buddy_chats WHERE id=:sid AND owner_id=:owner'),{'sid':session_id,'owner':owner})
            connection.execute(text('DELETE FROM buddy_navigation WHERE last_chat_id=:sid AND owner_id=:owner'),{'sid':session_id,'owner':owner})
            connection.execute(text("DELETE FROM learning_sessions WHERE id = :sid"), {"sid": session_id})
        return True

    def save_action(self, action: RunStatus, idempotency_key: str | None = None) -> None:
        with self.transaction() as connection:
            updated = connection.execute(
                text("UPDATE learning_actions SET payload = :payload WHERE id = :id"),
                {"id": action.run_id, "payload": action.model_dump_json()},
            )
            if not updated.rowcount:
                connection.execute(
                    text("INSERT INTO learning_actions(id, session_id, idempotency_key, payload) VALUES(:id, :session_id, :key, :payload)"),
                    {"id": action.run_id, "session_id": action.session_id, "key": idempotency_key, "payload": action.model_dump_json()},
                )

    def get_action(self, action_id: str) -> RunStatus | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT payload FROM learning_actions WHERE id = :id"), {"id": action_id}).mappings().first()
        if row:
            self.get_session(RunStatus.model_validate_json(row["payload"]).session_id)
        return RunStatus.model_validate_json(row["payload"]) if row else None

    def get_action_by_idempotency(self, session_id: str, idempotency_key: str) -> RunStatus | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM learning_actions WHERE session_id = :session_id AND idempotency_key = :key"),
                {"session_id": session_id, "key": idempotency_key},
            ).mappings().first()
        return RunStatus.model_validate_json(row["payload"]) if row else None

    def save_teaching_plan(self, plan: TeachingPlan) -> None:
        with self.transaction() as connection:
            connection.execute(
                text("INSERT INTO teaching_plans(id, action_id, payload) VALUES(:id, :action_id, :payload)"),
                {"id": plan.id, "action_id": plan.action_id, "payload": plan.model_dump_json()},
            )

    def get_teaching_plan(self, plan_id: str) -> TeachingPlan | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM teaching_plans WHERE id = :id"), {"id": plan_id}
            ).mappings().first()
        if row:
            self.get_action(TeachingPlan.model_validate_json(row["payload"]).action_id)
        return TeachingPlan.model_validate_json(row["payload"]) if row else None

    def save_policy_validation(self, result: PolicyValidationResult) -> None:
        with self.transaction() as connection:
            connection.execute(
                text("INSERT INTO policy_validation_results(id, action_id, plan_id, payload) VALUES(:id, :action_id, :plan_id, :payload)"),
                {"id": result.id, "action_id": result.action_id, "plan_id": result.plan_id, "payload": result.model_dump_json()},
            )

    def get_policy_validation(self, action_id: str) -> PolicyValidationResult | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT payload FROM policy_validation_results WHERE action_id = :id"), {"id": action_id}
            ).mappings().first()
        return PolicyValidationResult.model_validate_json(row["payload"]) if row else None

    def count_artifacts_for_action(self, action_id: str) -> int:
        # Payloads are text on both databases; use each dialect's JSON extraction.
        expression = (
            "CAST(payload AS JSONB) ->> 'verification_run_id'"
            if self.engine.dialect.name == "postgresql"
            else "json_extract(payload, '$.verification_run_id')"
        )
        with self.engine.connect() as connection:
            return int(connection.execute(
                text(f"SELECT COUNT(*) FROM lesson_artifacts WHERE {expression} = :id"),
                {"id": action_id},
            ).scalar_one())

    def save_artifact(self, artifact: LessonArtifact) -> None:
        with self.transaction() as connection:
            self._put(connection, "lesson_artifacts", "id", artifact.id, {"session_id": artifact.session_id, "payload": artifact.model_dump_json()})

    def get_artifact(self, artifact_id: str) -> LessonArtifact | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT payload FROM lesson_artifacts WHERE id = :id"), {"id": artifact_id}).mappings().first()
        if row:
            self.get_session(LessonArtifact.model_validate_json(row["payload"]).session_id)
        return LessonArtifact.model_validate_json(row["payload"]) if row else None

    def save_event(self, event: ActionEvent) -> None:
        with self.transaction() as connection:
            self._put(connection, "action_events", "id", event.id, {
                "action_id": event.action_id,
                "sequence": event.sequence,
                "payload": event.model_dump_json(),
            })

    def list_events(self, action_id: str) -> list[ActionEvent]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT payload FROM action_events WHERE action_id = :id ORDER BY sequence ASC"), {"id": action_id}
            ).mappings().all()
        return [ActionEvent.model_validate_json(row["payload"]) for row in rows]
