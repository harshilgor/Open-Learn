"""Learner-memory API shapes. Owner IDs are never accepted from clients."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MemorySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    learning_enabled: bool = Field(alias="learningEnabled")
    expected_revision: int = Field(alias="expectedRevision", ge=0)


def public_fact(fact: dict) -> dict:
    return {
        "id": fact["id"], "kind": fact["kind"], "statement": fact["statement"],
        "courseId": fact["course_id"], "conceptIds": fact["concept_ids"], "eventDate": fact["event_date"],
        "origin": fact["origin"], "status": fact["status"], "sensitive": fact["sensitive"],
        "learnedAt": fact["learned_at"], "validFrom": fact["valid_from"], "invalidAt": fact["invalid_at"],
        "supersededBy": fact["superseded_by"], "confirmedAt": fact["confirmed_at"], "lastUsedAt": fact["last_used_at"],
        "useCount": fact["use_count"], "needsReview": fact["needs_review"], "revision": fact["revision"],
        # The learner's own words and where they said them; no other content.
        "basis": [{key: ref.get(key) for key in ("type", "sessionId", "turnIndex", "quote", "sourceId", "revision") if ref.get(key) is not None}
                  for ref in fact["basis"]],
    }


def public_episode(episode: dict) -> dict:
    return {
        "id": episode["id"], "sessionId": episode["session_id"], "courseId": episode["course_id"],
        "periodStart": episode["period_start"], "periodEnd": episode["period_end"], "turnRange": episode["turn_range"],
        "summary": episode["summary"], "topics": episode["topics"], "method": episode["method"],
        "createdAt": episode["created_at"], "revision": episode["revision"],
    }


def public_settings(settings: dict) -> dict:
    return {"learningEnabled": settings["learning_enabled"], "revision": settings["revision"], "updatedAt": settings["updated_at"]}
