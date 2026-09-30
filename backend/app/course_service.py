"""Course domain service: creation, roadmap orchestration, and context aggregation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Connection, text

from .course_models import (
    CourseCreate,
    CoursePublic,
    CourseReminderPreferences,
    CourseRoadmapNode,
    CourseSummary,
    CourseTeachingPreferences,
    CourseUpdate,
    RoadmapNodeCreate,
    RoadmapNodeUpdate,
    RoadmapProgressionResult,
)
from .models import utc_now
from .session_models import LearningSession
from .storage import Store
from .workspace_note_models import WorkspaceNoteSummary


def _generate_default_roadmap(course_id: str, goal: str) -> list[dict[str, Any]]:
    """Deterministic, structured initial roadmap based on user's goal."""
    now = utc_now()
    phases_and_topics = [
        ("Foundations", [f"Core concepts of {goal[:40]}", "Fundamental terminology", "Historical context & motivation"]),
        ("Core Architecture", [f"Key mechanisms and design principles", "Standard patterns and implementations"]),
        ("Advanced Analysis", [f"Performance trade-offs & edge cases", "Modern industry practices"]),
        ("Synthesis & Application", [f"Practical applications & future directions", "Comprehensive review"]),
    ]
    nodes: list[dict[str, Any]] = []
    order_idx = 0
    for phase, topics in phases_and_topics:
        for title in topics:
            nodes.append({
                "id": f"node_{uuid4().hex}",
                "course_id": course_id,
                "phase": phase,
                "concept_id": f"concept_{course_id[7:15]}_{uuid4().hex[:6]}",
                "title": title,
                "status": "planned" if order_idx > 0 else "in_progress",
                "order_index": order_idx,
                "created_at": now,
            })
            order_idx += 1
    return nodes


def _generate_tailored_curriculum(
    course_id: str,
    name: str,
    goal: str,
    prefs: CourseTeachingPreferences,
    prompt: str | None = None,
) -> list[dict[str, Any]]:
    """Generate a domain-tailored curriculum matching course goals, preferences, and custom prompts."""
    now = utc_now()
    prompt_lower = (prompt or "").lower()

    is_project_focused = any(k in prompt_lower for k in ["project", "build", "hands-on", "practical", "app", "code"]) or prefs.code_examples
    is_rigorous = prefs.math_level == "rigorous" or any(k in prompt_lower for k in ["math", "formal", "proof", "rigorous", "theory"])
    is_intro = prefs.depth == "introductory" or any(k in prompt_lower for k in ["beginner", "intro", "basics", "simple"])

    short_goal = goal[:45].strip()

    if is_project_focused:
        phases = [
            ("Environment & Setup", [f"Development tooling for {name}", f"First working prototype of {short_goal}"]),
            ("Core Implementation", [f"Core modules and state management", f"Implementing key logic for {name}", "Testing and debugging workflows"]),
            ("Optimization & Hardening", ["Error handling, performance, and edge cases", "Security and architectural best practices"]),
            ("Project Capstone", [f"Full end-to-end deployment of {name}", "Code review, documentation & next steps"]),
        ]
    elif is_rigorous:
        phases = [
            ("Mathematical Foundations", [f"Formal definitions & notation for {name}", "Underlying theorems and first principles"]),
            ("Theoretical Mechanics", [f"Core analytical structures in {name}", "Proof sketches and invariant guarantees"]),
            ("Advanced Analysis", ["Complexity bounds and performance trade-offs", "Limiting behavior and asymptotic properties"]),
            ("Research Synthesis", [f"Modern open questions in {short_goal}", "Comprehensive technical defense"]),
        ]
    elif is_intro:
        phases = [
            ("Orientation & Big Picture", [f"What is {name} and why it matters", "Essential terminology in plain language"]),
            ("Foundational Concepts", [f"The 3 key building blocks of {short_goal}", "Real-world intuitive analogies"]),
            ("Guided Practice", [f"Working through a standard {name} walkthrough", "Common pitfalls to avoid"]),
            ("Moving Forward", [f"Connecting {name} to broader subjects", "Personal project and exploration ideas"]),
        ]
    else:
        phases = [
            ("Foundations & Intuition", [f"Core concepts of {name}", "Fundamental mental models", "Historical context & motivation"]),
            ("Mechanisms & Patterns", [f"Key architecture of {short_goal}", "Standard design patterns", "Step-by-step walkthrough"]),
            ("Deep Dive & Edge Cases", ["Performance trade-offs and subtleties", "Debugging tricky failure modes"]),
            ("Synthesis & Mastery", [f"Real-world application of {name}", "Comprehensive synthesis & self-assessment"]),
        ]

    # If the user prompt specifically specifies an emphasis, add it as a specialized node
    if prompt and len(prompt.strip()) > 3:
        clean_prompt_topic = " ".join(prompt.split())[:60]
        phases[-1][1].insert(0, f"Focus Milestone: {clean_prompt_topic}")

    nodes: list[dict[str, Any]] = []
    order_idx = 0
    for phase, topics in phases:
        for title in topics:
            nodes.append({
                "id": f"node_{uuid4().hex}",
                "course_id": course_id,
                "phase": phase,
                "concept_id": f"concept_{course_id[7:15]}_{uuid4().hex[:6]}",
                "title": title,
                "status": "planned" if order_idx > 0 else "in_progress",
                "order_index": order_idx,
                "created_at": now,
            })
            order_idx += 1
    return nodes


class CourseService:
    def __init__(self, store: Store, provider: Any = None):
        self.store = store
        self.provider = provider

    def create_course(self, owner_id: str, input_data: CourseCreate) -> CoursePublic:
        course_id = f"course_{uuid4().hex}"
        now = utc_now()
        teaching_prefs = input_data.teaching_preferences or CourseTeachingPreferences()
        reminder_prefs = input_data.reminder_preferences or CourseReminderPreferences()

        with self.store.transaction() as conn:
            conn.execute(
                text(
                    "INSERT INTO courses(id, owner_id, name, goal, teaching_preferences, reminder_preferences, created_at, updated_at) "
                    "VALUES(:id, :owner_id, :name, :goal, :teaching_preferences, :reminder_preferences, :created_at, :updated_at)"
                ),
                {
                    "id": course_id,
                    "owner_id": owner_id,
                    "name": input_data.name,
                    "goal": input_data.goal,
                    "teaching_preferences": teaching_prefs.model_dump_json(),
                    "reminder_preferences": reminder_prefs.model_dump_json(),
                    "created_at": now,
                    "updated_at": now,
                },
            )

        result = self.get_course(owner_id, course_id)
        if not result:
            raise RuntimeError(f"Course {course_id} could not be loaded after creation.")
        return result

    def get_course(self, owner_id: str, course_id: str) -> CoursePublic | None:
        with self.store.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM courses WHERE id = :id AND owner_id = :owner"),
                {"id": course_id, "owner": owner_id},
            ).mappings().first()
            if not row:
                return None

            roadmap_rows = conn.execute(
                text("SELECT * FROM course_roadmap_nodes WHERE course_id = :id ORDER BY order_index ASC"),
                {"id": course_id},
            ).mappings().all()

            session_count = conn.execute(
                text("SELECT COUNT(*) FROM learning_sessions WHERE course_id = :id AND learner_id = :owner"),
                {"id": course_id, "owner": owner_id},
            ).scalar_one()

            note_count = conn.execute(
                text("SELECT COUNT(*) FROM workspace_notes WHERE course_id = :id AND learner_id = :owner"),
                {"id": course_id, "owner": owner_id},
            ).scalar_one()

            material_count = conn.execute(
                text("SELECT COUNT(*) FROM materials WHERE course_id = :id AND owner_id = :owner AND deleted = false"),
                {"id": course_id, "owner": owner_id},
            ).scalar_one()

            # Dynamically compute review items due for this course
            due_review_count = conn.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT cms.concept_id)
                    FROM concept_memory_states cms
                    WHERE cms.learner_id = :owner
                      AND cms.next_review_at <= :now
                      AND (
                        cms.source_session_id IN (
                          SELECT id FROM learning_sessions WHERE course_id = :id AND learner_id = :owner
                        )
                        OR cms.concept_id IN (
                          SELECT concept_id FROM course_roadmap_nodes WHERE course_id = :id AND concept_id IS NOT NULL
                        )
                      )
                    """
                ),
                {"id": course_id, "owner": owner_id, "now": utc_now()},
            ).scalar_one()

        roadmap = [
            CourseRoadmapNode(
                id=r["id"],
                course_id=r["course_id"],
                phase=r["phase"],
                concept_id=r["concept_id"],
                title=r["title"],
                status=r["status"],
                order_index=r["order_index"],
                created_at=r["created_at"],
            )
            for r in roadmap_rows
        ]

        completed_count = sum(1 for n in roadmap if n.status == "completed")
        roadmap_progress = int((completed_count / len(roadmap) * 100)) if roadmap else 0

        teaching_prefs = (
            CourseTeachingPreferences.model_validate_json(row["teaching_preferences"])
            if row["teaching_preferences"]
            else CourseTeachingPreferences()
        )
        reminder_prefs = (
            CourseReminderPreferences.model_validate_json(row["reminder_preferences"])
            if row["reminder_preferences"]
            else CourseReminderPreferences()
        )

        summary = CourseSummary(
            id=row["id"],
            name=row["name"],
            goal=row["goal"],
            session_count=int(session_count),
            note_count=int(note_count),
            material_count=int(material_count),
            due_review_count=int(due_review_count),
            roadmap_progress=roadmap_progress,
            updated_at=row["updated_at"],
            archived_at=row["archived_at"],
        )

        return CoursePublic(
            id=row["id"],
            name=row["name"],
            goal=row["goal"],
            teaching_preferences=teaching_prefs,
            reminder_preferences=reminder_prefs,
            roadmap=roadmap,
            summary=summary,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            archived_at=row["archived_at"],
        )

    def list_courses(self, owner_id: str, include_archived: bool = False) -> list[CourseSummary]:
        with self.store.engine.connect() as conn:
            query = "SELECT id FROM courses WHERE owner_id = :owner"
            if not include_archived:
                query += " AND archived_at IS NULL"
            query += " ORDER BY updated_at DESC"
            rows = conn.execute(text(query), {"owner": owner_id}).scalars().all()

        summaries: list[CourseSummary] = []
        for course_id in rows:
            course = self.get_course(owner_id, course_id)
            if course:
                summaries.append(course.summary)
        return summaries

    def update_course(self, owner_id: str, course_id: str, input_data: CourseUpdate) -> CoursePublic | None:
        course = self.get_course(owner_id, course_id)
        if not course:
            return None

        updates: dict[str, Any] = {"updated_at": utc_now()}
        if input_data.name is not None:
            updates["name"] = input_data.name
        if input_data.goal is not None:
            updates["goal"] = input_data.goal
        if input_data.teaching_preferences is not None:
            updates["teaching_preferences"] = input_data.teaching_preferences.model_dump_json()
        if input_data.reminder_preferences is not None:
            updates["reminder_preferences"] = input_data.reminder_preferences.model_dump_json()
        if input_data.archived is not None:
            updates["archived_at"] = utc_now() if input_data.archived else None

        assignments = ", ".join(f"{col} = :{col}" for col in updates)
        with self.store.transaction() as conn:
            conn.execute(
                text(f"UPDATE courses SET {assignments} WHERE id = :id AND owner_id = :owner"),
                {**updates, "id": course_id, "owner": owner_id},
            )

        return self.get_course(owner_id, course_id)

    def delete_course(self, owner_id: str, course_id: str) -> bool:
        course = self.get_course(owner_id, course_id)
        if not course:
            return False

        with self.store.transaction() as conn:
            # Unlink associated sessions, notes, and materials rather than deleting them
            session_rows = conn.execute(
                text("SELECT id, payload FROM learning_sessions WHERE course_id = :id AND learner_id = :owner"),
                {"id": course_id, "owner": owner_id},
            ).mappings().all()
            for s_row in session_rows:
                sess_data = json.loads(s_row["payload"])
                sess_data["courseId"] = None
                sess_data["course_id"] = None
                conn.execute(
                    text("UPDATE learning_sessions SET course_id = NULL, payload = :payload WHERE id = :sid"),
                    {"sid": s_row["id"], "payload": json.dumps(sess_data)},
                )
            conn.execute(
                text("UPDATE workspace_notes SET course_id = NULL WHERE course_id = :id AND learner_id = :owner"),
                {"id": course_id, "owner": owner_id},
            )
            conn.execute(
                text("UPDATE materials SET course_id = NULL WHERE course_id = :id AND owner_id = :owner"),
                {"id": course_id, "owner": owner_id},
            )
            conn.execute(
                text("DELETE FROM course_roadmap_nodes WHERE course_id = :id"),
                {"id": course_id},
            )
            conn.execute(
                text("DELETE FROM courses WHERE id = :id AND owner_id = :owner"),
                {"id": course_id, "owner": owner_id},
            )
        return True

    def list_course_sessions(self, owner_id: str, course_id: str, limit: int = 50, offset: int = 0) -> tuple[list[LearningSession], int]:
        with self.store.engine.connect() as conn:
            total = conn.execute(
                text("SELECT COUNT(*) FROM learning_sessions WHERE course_id = :cid AND learner_id = :owner"),
                {"cid": course_id, "owner": owner_id},
            ).scalar_one()
            rows = conn.execute(
                text(
                    "SELECT payload FROM learning_sessions WHERE course_id = :cid AND learner_id = :owner "
                    "ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
                ),
                {"cid": course_id, "owner": owner_id, "limit": limit, "offset": offset},
            ).mappings().all()
        return ([LearningSession.model_validate_json(row["payload"]) for row in rows], int(total))

    def set_session_course(self, owner_id: str, course_id: str, session_id: str, *, remove: bool = False) -> bool:
        if not self.get_course(owner_id, course_id):
            return False
        with self.store.transaction() as conn:
            row = conn.execute(
                text("SELECT payload, course_id FROM learning_sessions WHERE id = :sid AND learner_id = :owner"),
                {"sid": session_id, "owner": owner_id},
            ).mappings().first()
            if not row or (remove and row["course_id"] != course_id):
                return False
            next_course_id = None if remove else course_id
            payload = json.loads(row["payload"])
            now = utc_now()
            payload["courseId"] = next_course_id
            payload["course_id"] = next_course_id
            payload["updatedAt"] = now.isoformat()
            conn.execute(
                text("UPDATE learning_sessions SET course_id = :cid, payload = :payload, updated_at = :now "
                     "WHERE id = :sid AND learner_id = :owner"),
                {"cid": next_course_id, "payload": json.dumps(payload), "now": now,
                 "sid": session_id, "owner": owner_id},
            )
        return True

    def list_course_notes(self, owner_id: str, course_id: str) -> list[WorkspaceNoteSummary]:
        from .workspace_note_service import WorkspaceNoteService
        notes_service = WorkspaceNoteService(self.store)
        all_notes = notes_service.list(owner_id)
        # Filter notes by course_id in database or frontmatter
        course_notes = []
        for note in all_notes:
            if (note.frontmatter or {}).get("course_id") == course_id:
                course_notes.append(note)
            else:
                # Also check database column if present
                with self.store.engine.connect() as conn:
                    cid = conn.execute(
                        text("SELECT course_id FROM workspace_notes WHERE id = :id AND learner_id = :owner"),
                        {"id": note.id, "owner": owner_id},
                    ).scalar_one_or_none()
                    if cid == course_id:
                        course_notes.append(note)
        return course_notes

    def list_course_materials(self, owner_id: str, course_id: str) -> list[dict[str, Any]]:
        from .material_service import MaterialService
        svc = MaterialService(self.store)
        return svc.list(owner_id, course_id=course_id)

    def attach_material_to_course(self, owner_id: str, course_id: str, material_id: str) -> bool:
        course = self.get_course(owner_id, course_id)
        if not course:
            return False
        with self.store.transaction() as conn:
            result = conn.execute(
                text("UPDATE materials SET course_id = :cid WHERE id = :mid AND owner_id = :owner AND deleted = false"),
                {"cid": course_id, "mid": material_id, "owner": owner_id},
            )
            if result.rowcount > 0:
                conn.execute(
                    text("UPDATE courses SET updated_at = :now WHERE id = :cid"),
                    {"now": utc_now(), "cid": course_id},
                )
                return True
        return False

    def detach_material_from_course(self, owner_id: str, course_id: str, material_id: str) -> bool:
        course = self.get_course(owner_id, course_id)
        if not course:
            return False
        with self.store.transaction() as conn:
            result = conn.execute(
                text("UPDATE materials SET course_id = NULL WHERE id = :mid AND course_id = :cid AND owner_id = :owner"),
                {"mid": material_id, "cid": course_id, "owner": owner_id},
            )
            if result.rowcount > 0:
                conn.execute(
                    text("UPDATE courses SET updated_at = :now WHERE id = :cid"),
                    {"now": utc_now(), "cid": course_id},
                )
                return True
        return False

    def generate_tailored_roadmap(
        self,
        owner_id: str,
        course_id: str,
        prompt: str | None = None,
        replace_existing: bool = True,
    ) -> list[CourseRoadmapNode]:
        course = self.get_course(owner_id, course_id)
        if not course:
            raise ValueError(f"Course {course_id} not found.")

        now = utc_now()
        nodes_data = _generate_tailored_curriculum(
            course_id=course_id,
            name=course.name,
            goal=course.goal,
            prefs=course.teaching_preferences,
            prompt=prompt,
        )

        with self.store.transaction() as conn:
            if replace_existing:
                conn.execute(
                    text("DELETE FROM course_roadmap_nodes WHERE course_id = :id"),
                    {"id": course_id},
                )
                start_order = 0
            else:
                max_order = conn.execute(
                    text("SELECT COALESCE(MAX(order_index), -1) FROM course_roadmap_nodes WHERE course_id = :id"),
                    {"id": course_id},
                ).scalar_one()
                start_order = int(max_order) + 1

            for idx, node in enumerate(nodes_data):
                node_to_insert = {**node, "order_index": start_order + idx}
                conn.execute(
                    text(
                        "INSERT INTO course_roadmap_nodes(id, course_id, phase, concept_id, title, status, order_index, created_at) "
                        "VALUES(:id, :course_id, :phase, :concept_id, :title, :status, :order_index, :created_at)"
                    ),
                    node_to_insert,
                )
            conn.execute(
                text("UPDATE courses SET updated_at = :now WHERE id = :id"),
                {"now": now, "id": course_id},
            )

        updated_course = self.get_course(owner_id, course_id)
        return updated_course.roadmap if updated_course else []

    def add_roadmap_node(self, owner_id: str, course_id: str, input_data: RoadmapNodeCreate) -> CourseRoadmapNode:
        course = self.get_course(owner_id, course_id)
        if not course:
            raise ValueError(f"Course {course_id} not found.")

        now = utc_now()
        node_id = f"node_{uuid4().hex}"
        concept_id = input_data.concept_id or f"concept_{course_id[7:15]}_{uuid4().hex[:6]}"

        with self.store.engine.connect() as conn:
            max_order = conn.execute(
                text("SELECT COALESCE(MAX(order_index), -1) FROM course_roadmap_nodes WHERE course_id = :cid"),
                {"cid": course_id},
            ).scalar_one()

        order_index = int(max_order) + 1

        with self.store.transaction() as conn:
            conn.execute(
                text(
                    "INSERT INTO course_roadmap_nodes(id, course_id, phase, concept_id, title, status, order_index, created_at) "
                    "VALUES(:id, :course_id, :phase, :concept_id, :title, :status, :order_index, :created_at)"
                ),
                {
                    "id": node_id,
                    "course_id": course_id,
                    "phase": input_data.phase,
                    "concept_id": concept_id,
                    "title": input_data.title,
                    "status": "planned",
                    "order_index": order_index,
                    "created_at": now,
                },
            )
            conn.execute(
                text("UPDATE courses SET updated_at = :now WHERE id = :id"),
                {"now": now, "id": course_id},
            )

        return CourseRoadmapNode(
            id=node_id,
            course_id=course_id,
            phase=input_data.phase,
            concept_id=concept_id,
            title=input_data.title,
            status="planned",
            order_index=order_index,
            created_at=now,
        )

    def update_roadmap_node(
        self,
        owner_id: str,
        course_id: str,
        node_id: str,
        input_data: RoadmapNodeUpdate | str,
    ) -> CourseRoadmapNode | None:
        course = self.get_course(owner_id, course_id)
        if not course:
            return None

        if isinstance(input_data, str):
            input_data = RoadmapNodeUpdate(status=input_data)  # type: ignore[arg-type]

        updates: dict[str, Any] = {}
        if input_data.title is not None:
            updates["title"] = input_data.title
        if input_data.phase is not None:
            updates["phase"] = input_data.phase
        if input_data.concept_id is not None:
            updates["concept_id"] = input_data.concept_id
        if input_data.status is not None:
            updates["status"] = input_data.status
        if input_data.order_index is not None:
            updates["order_index"] = input_data.order_index

        if not updates:
            for node in course.roadmap:
                if node.id == node_id:
                    return node
            return None

        assignments = ", ".join(f"{col} = :{col}" for col in updates)
        with self.store.transaction() as conn:
            conn.execute(
                text(f"UPDATE course_roadmap_nodes SET {assignments} WHERE id = :id AND course_id = :cid"),
                {**updates, "id": node_id, "cid": course_id},
            )
            conn.execute(
                text("UPDATE courses SET updated_at = :now WHERE id = :id"),
                {"now": utc_now(), "id": course_id},
            )

        updated_course = self.get_course(owner_id, course_id)
        if not updated_course:
            return None
        for node in updated_course.roadmap:
            if node.id == node_id:
                return node
        return None

    def delete_roadmap_node(self, owner_id: str, course_id: str, node_id: str) -> bool:
        course = self.get_course(owner_id, course_id)
        if not course:
            return False

        with self.store.transaction() as conn:
            result = conn.execute(
                text("DELETE FROM course_roadmap_nodes WHERE id = :id AND course_id = :cid"),
                {"id": node_id, "cid": course_id},
            )
            if result.rowcount > 0:
                conn.execute(
                    text("UPDATE courses SET updated_at = :now WHERE id = :id"),
                    {"now": utc_now(), "id": course_id},
                )
                return True
        return False

    def reorder_roadmap_nodes(self, owner_id: str, course_id: str, node_ids: list[str]) -> list[CourseRoadmapNode]:
        course = self.get_course(owner_id, course_id)
        if not course:
            raise ValueError(f"Course {course_id} not found.")

        now = utc_now()
        with self.store.transaction() as conn:
            for idx, nid in enumerate(node_ids):
                conn.execute(
                    text("UPDATE course_roadmap_nodes SET order_index = :idx WHERE id = :id AND course_id = :cid"),
                    {"idx": idx, "id": nid, "cid": course_id},
                )
            conn.execute(
                text("UPDATE courses SET updated_at = :now WHERE id = :id"),
                {"now": now, "id": course_id},
            )

        updated_course = self.get_course(owner_id, course_id)
        return updated_course.roadmap if updated_course else []

    def evaluate_roadmap_progression(self, owner_id: str, course_id: str) -> RoadmapProgressionResult:
        course = self.get_course(owner_id, course_id)
        if not course:
            raise ValueError(f"Course {course_id} not found.")

        with self.store.engine.connect() as conn:
            # 1. Fetch learner_concept_states
            lcs_rows = conn.execute(
                text("SELECT concept_id, status FROM learner_concept_states WHERE learner_id = :owner"),
                {"owner": owner_id},
            ).mappings().all()
            concept_states = {row["concept_id"]: row["status"] for row in lcs_rows}

            # 2. Fetch concept_memory_states
            cms_rows = conn.execute(
                text(
                    "SELECT concept_id, mastery_estimate, needs_remediation, review_count, last_outcome "
                    "FROM concept_memory_states WHERE learner_id = :owner"
                ),
                {"owner": owner_id},
            ).mappings().all()
            memory_states = {
                row["concept_id"]: {
                    "mastery_estimate": row["mastery_estimate"],
                    "needs_remediation": bool(row["needs_remediation"]),
                    "review_count": row["review_count"] or 0,
                    "last_outcome": row["last_outcome"],
                }
                for row in cms_rows
            }

            # 3. Fetch course sessions
            session_rows = conn.execute(
                text("SELECT id, payload FROM learning_sessions WHERE course_id = :cid AND learner_id = :owner"),
                {"cid": course_id, "owner": owner_id},
            ).mappings().all()
            course_sessions = [LearningSession.model_validate_json(r["payload"]) for r in session_rows]

        nodes_updated = 0
        updated_nodes: list[CourseRoadmapNode] = []

        for node in course.roadmap:
            current_status = node.status
            target_status = current_status

            cid = node.concept_id
            if cid and cid in memory_states and memory_states[cid]["needs_remediation"]:
                target_status = "needs_review"
            elif cid and (
                concept_states.get(cid) == "demonstrated"
                or (cid in memory_states and memory_states[cid]["mastery_estimate"] in ("strong", "mastered", "retained", "fluent"))
            ):
                target_status = "completed"
            elif cid and (
                concept_states.get(cid) in ("developing", "explored")
                or (cid in memory_states and memory_states[cid]["review_count"] > 0)
            ):
                if current_status != "completed":
                    target_status = "in_progress"
            else:
                # Also check title matching against explored topics in sessions
                norm_title = node.title.lower()
                matching_sessions = [
                    s for s in course_sessions
                    if norm_title in (s.title or "").lower()
                    or (s.title and s.title.lower() in norm_title)
                    or norm_title in (s.goal or "").lower()
                ]
                if matching_sessions:
                    if current_status == "planned":
                        target_status = "in_progress"

            if target_status != current_status:
                with self.store.transaction() as conn:
                    conn.execute(
                        text("UPDATE course_roadmap_nodes SET status = :status WHERE id = :id AND course_id = :cid"),
                        {"status": target_status, "id": node.id, "cid": course_id},
                    )
                nodes_updated += 1
                node = node.model_copy(update={"status": target_status})

            updated_nodes.append(node)

        # Re-fetch course to compute summary properly
        refreshed_course = self.get_course(owner_id, course_id)
        completed_count = sum(1 for n in updated_nodes if n.status == "completed")
        due_reviews = refreshed_course.summary.due_review_count if refreshed_course else 0

        return RoadmapProgressionResult(
            course_id=course_id,
            nodes_updated=nodes_updated,
            completed_count=completed_count,
            total_count=len(updated_nodes),
            due_review_count=due_reviews,
            roadmap=updated_nodes,
        )
