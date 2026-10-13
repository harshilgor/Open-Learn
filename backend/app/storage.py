"""Persistence adapter shared by the modular-monolith services.

The adapter keeps the original method surface while moving connection and
dialect concerns behind SQLAlchemy. New state services use ``transaction`` to
commit canonical state, evidence, and audit events atomically.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, text

from .database import create_database_engine, run_migrations
from .models import GraphJob, GraphVersion, TopicScope
from .policy_models import PolicyValidationResult, TeachingPlan
from .session_models import ActionEvent, LearningSession, LessonArtifact, RunStatus
from .agent_models import AgentDocument, AgentTask, AgentTaskEvent


class Store:
    def __init__(self, location: str | Path):
        raw = str(location)
        if "://" in raw:
            self.url = raw
        elif raw == ":memory:":
            self.url = "sqlite+pysqlite:///file:ai_tutor_memdb?mode=memory&cache=shared&uri=true"
        else:
            self.url = f"sqlite+pysqlite:///{Path(raw).resolve()}"
        run_migrations(self.url)
        self.engine: Engine = create_database_engine(self.url)

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.begin() as connection:
            yield connection

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
            self._put(connection, "topic_scopes", "id", scope.id, {"payload": scope.model_dump_json()})

    def get_scope(self, scope_id: str) -> TopicScope | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT payload FROM topic_scopes WHERE id = :id"), {"id": scope_id}).mappings().first()
        return TopicScope.model_validate_json(row["payload"]) if row else None

    def save_job(self, job: GraphJob) -> None:
        with self.transaction() as connection:
            self._put(connection, "graph_jobs", "id", job.id, {"scope_id": job.scope_id, "payload": job.model_dump_json()})

    def get_job(self, job_id: str) -> GraphJob | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT payload FROM graph_jobs WHERE id = :id"), {"id": job_id}).mappings().first()
        return GraphJob.model_validate_json(row["payload"]) if row else None

    def save_graph(self, graph: GraphVersion) -> None:
        with self.transaction() as connection:
            self._put(connection, "graph_versions", "id", graph.id, {"scope_id": graph.scope_id, "payload": graph.model_dump_json()})

    def get_graph(self, graph_id: str) -> GraphVersion | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT payload FROM graph_versions WHERE id = :id"), {"id": graph_id}).mappings().first()
        return GraphVersion.model_validate_json(row["payload"]) if row else None

    def save_session(self, session: LearningSession) -> None:
        with self.transaction() as connection:
            self._put(connection, "learning_sessions", "id", session.id, {
                "graph_id": session.graph_id,
                "learner_id": session.learner_id,
                "current_concept_id": session.current_concept_id,
                "current_lesson_id": session.current_lesson_id,
                "state_version": session.state_version,
                "updated_at": session.updated_at,
                "payload": session.model_dump_json(),
            })

    def get_session(self, session_id: str) -> LearningSession | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT payload FROM learning_sessions WHERE id = :id"), {"id": session_id}).mappings().first()
        return LearningSession.model_validate_json(row["payload"]) if row else None

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

    def save_agent_document(self, document: AgentDocument, content: str) -> None:
        with self.transaction() as connection:
            self._put(connection, "agent_documents", "id", document.id, {
                "learner_id": document.learner_id,
                "title": document.title,
                "mime_type": document.mime_type,
                "content": content,
                "content_sha256": document.content_sha256,
                "created_at": document.created_at,
            })

    def get_agent_document(self, document_id: str, learner_id: str) -> tuple[AgentDocument, str] | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT id, learner_id, title, mime_type, content, content_sha256, created_at
                FROM agent_documents WHERE id=:id AND learner_id=:learner_id
            """), {"id": document_id, "learner_id": learner_id}).mappings().first()
        if row is None:
            return None
        document = AgentDocument(
            id=row["id"], learner_id=row["learner_id"], title=row["title"], mime_type=row["mime_type"],
            character_count=len(row["content"]), content_sha256=row["content_sha256"], created_at=row["created_at"],
        )
        return document, row["content"]

    def list_agent_documents(self, learner_id: str) -> list[AgentDocument]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT id, learner_id, title, mime_type, content, content_sha256, created_at
                FROM agent_documents WHERE learner_id=:learner_id ORDER BY created_at DESC
            """), {"learner_id": learner_id}).mappings().all()
        return [AgentDocument(
            id=row["id"], learner_id=row["learner_id"], title=row["title"], mime_type=row["mime_type"],
            character_count=len(row["content"]), content_sha256=row["content_sha256"], created_at=row["created_at"],
        ) for row in rows]

    def save_agent_task(self, task: AgentTask, idempotency_key: str | None = None) -> None:
        values: dict[str, Any] = {
            "learner_id": task.learner_id,
            "status": task.status.value,
            "payload": task.model_dump_json(),
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }
        # A status update must never erase the idempotency key established by
        # the create command.  Omitting it also works for inserts because the
        # database column is nullable.
        if idempotency_key is not None:
            values["idempotency_key"] = idempotency_key
        with self.transaction() as connection:
            self._put(connection, "agent_tasks", "id", task.id, values)

    def get_agent_task(self, task_id: str, learner_id: str) -> AgentTask | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT payload FROM agent_tasks WHERE id=:id AND learner_id=:learner_id"), {
                "id": task_id, "learner_id": learner_id,
            }).mappings().first()
        return AgentTask.model_validate_json(row["payload"]) if row else None

    def get_agent_task_by_idempotency(self, learner_id: str, idempotency_key: str) -> AgentTask | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT payload FROM agent_tasks WHERE learner_id=:learner_id AND idempotency_key=:key
            """), {"learner_id": learner_id, "key": idempotency_key}).mappings().first()
        return AgentTask.model_validate_json(row["payload"]) if row else None

    def list_agent_tasks(self, learner_id: str, limit: int = 50) -> list[AgentTask]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT payload FROM agent_tasks WHERE learner_id=:learner_id ORDER BY updated_at DESC LIMIT :limit
            """), {"learner_id": learner_id, "limit": limit}).mappings().all()
        return [AgentTask.model_validate_json(row["payload"]) for row in rows]

    def save_agent_task_event(self, event: AgentTaskEvent) -> None:
        with self.transaction() as connection:
            self._put(connection, "agent_task_events", "id", event.id, {
                "task_id": event.task_id,
                "sequence": event.sequence,
                "payload": event.model_dump_json(),
            })

    def list_agent_task_events(self, task_id: str) -> list[AgentTaskEvent]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT payload FROM agent_task_events WHERE task_id=:task_id ORDER BY sequence ASC
            """), {"task_id": task_id}).mappings().all()
        return [AgentTaskEvent.model_validate_json(row["payload"]) for row in rows]
