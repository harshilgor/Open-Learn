"""Owned semantic updates for persisted visual specifications."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import text

from .material_service import MaterialService, problem
from .session_models import ApiModel, LessonArtifact
from .visualization_models import VisualizationSpec, VisualAnnotation
from .workflow_store import WorkflowStore


class VisualChange(ApiModel):
    operation: Literal["change_parameter", "annotate", "set_domain"]
    expected_revision: int = Field(ge=1)
    parameter_id: str | None = Field(default=None, max_length=64)
    value: float | None = Field(default=None, ge=-10000, le=10000, allow_inf_nan=False)
    annotation: VisualAnnotation | None = None
    x_domain: tuple[float, float] | None = None

    @model_validator(mode="after")
    def complete_change(self):
        if self.operation == "change_parameter" and (self.parameter_id is None or self.value is None):
            raise ValueError("parameter id and value are required")
        if self.operation == "annotate" and self.annotation is None:
            raise ValueError("annotation is required")
        if self.operation == "set_domain" and self.x_domain is None:
            raise ValueError("x domain is required")
        return self


def changed_spec(spec: VisualizationSpec, change: VisualChange) -> VisualizationSpec:
    if spec.revision != change.expected_revision:
        problem("revision_conflict", "The visual changed. Reload it before editing.", 409)
    payload = spec.model_dump(mode="json", by_alias=True)
    payload["revision"] = spec.revision + 1
    if change.operation == "change_parameter":
        if spec.type != "simulation":
            problem("unsupported_visual_operation", "Only simulations have parameters.", 422)
        matched = False
        for parameter in payload["parameters"]:
            if parameter["id"] == change.parameter_id:
                if not parameter["minimum"] <= change.value <= parameter["maximum"]:
                    problem("parameter_out_of_range", "That value is outside the visual's range.", 422)
                parameter["initial"] = change.value
                matched = True
        if not matched:
            problem("parameter_not_found", "That simulation parameter is unavailable.", 404)
    elif change.operation == "annotate":
        if len(payload["annotations"]) >= 12:
            problem("annotation_limit", "This visual already has the maximum number of annotations.", 422)
        payload["annotations"] = [*payload["annotations"], change.annotation.model_dump(mode="json", by_alias=True)]
    else:
        if spec.type not in {"function", "line", "scatter", "distribution"}:
            problem("unsupported_visual_operation", "This visual has no numeric x axis.", 422)
        payload["xDomain"] = change.x_domain
    return VisualizationSpec.model_validate(payload)


def replace_in_journey(journey: dict, lesson_id: str, updated: VisualizationSpec) -> bool:
    changed = False
    for turn in journey.get("turns", []):
        lesson = turn.get("lesson") or {}
        if lesson.get("id") != lesson_id:
            continue
        for block in lesson.get("blocks", []):
            for index, value in enumerate(block.get("visualizations", [])):
                if value.get("id") == updated.id:
                    block["visualizations"][index] = updated.model_dump(mode="json", by_alias=True)
                    changed = True
    return changed


class VisualizationService:
    def __init__(self, store):
        self.store = store

    def replace_in_artifact(self, conn, owner: str, lesson_id: str, updated: VisualizationSpec) -> None:
        row = conn.execute(text("SELECT session_id,payload FROM lesson_artifacts WHERE id=:id"), {"id": lesson_id}).mappings().first()
        if row is None:
            problem("not_found", "This lesson is unavailable.", 404)
        MaterialService(self.store).session(owner, row["session_id"])
        artifact = LessonArtifact.model_validate_json(row["payload"])
        found = False
        for block in artifact.blocks:
            for index, value in enumerate(block.visualizations):
                if value.get("id") == updated.id:
                    if value.get("revision", 1) != updated.revision - 1:
                        problem("revision_conflict", "The visual changed. Reload it before editing.", 409)
                    block.visualizations[index] = updated.model_dump(mode="json", by_alias=True)
                    found = True
        if not found:
            problem("not_found", "This visualization is unavailable.", 404)
        conn.execute(text("UPDATE lesson_artifacts SET payload=:payload WHERE id=:id"),
                     {"id": lesson_id, "payload": artifact.model_dump_json()})

    def change(self, owner: str, lesson_id: str, visualization_id: str, change: VisualChange) -> VisualizationSpec:
        artifact = self.store.get_artifact(lesson_id)
        if artifact is None:
            problem("not_found", "This lesson is unavailable.", 404)
        MaterialService(self.store).session(owner, artifact.session_id)
        raw = next((value for block in artifact.blocks for value in block.visualizations if value.get('id') == visualization_id), None)
        if raw is None:
            problem("not_found", "This visualization is unavailable.", 404)
        if raw.get('type') == 'generated_ui_ref':
            from .visual_runs import VisualRuns
            return VisualRuns(self.store).change(owner, lesson_id, visualization_id, change)
        current = VisualizationSpec.model_validate(raw)
        updated = changed_spec(current, change)
        with self.store.transaction() as conn:
            self.replace_in_artifact(conn, owner, lesson_id, updated)
            records = WorkflowStore(self.store)
            row = conn.execute(text("SELECT 1 FROM practice_records WHERE id=:id AND owner_id=:owner"),
                               {"id": f"journey_{artifact.session_id}", "owner": owner}).first()
            if row:
                journey = records.read(owner, f"journey_{artifact.session_id}", "journey", conn)
                if replace_in_journey(journey, lesson_id, updated):
                    records.put(conn, owner, "journey", journey, artifact.session_id, expected=journey["revision"])
        return updated
