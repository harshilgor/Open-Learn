"""Typed contracts owned by the deterministic teaching-policy layer."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import utc_now


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class PrerequisiteOutcome(StrEnum):
    complete = "complete"
    missing = "missing"
    cyclic = "cyclic"
    unsupported = "unsupported"
    excessive = "excessive"


class GapClassification(StrEnum):
    none = "none"
    uncertain_foundation = "uncertain_foundation"
    missing_foundation = "missing_foundation"
    multiple_foundation_gaps = "multiple_foundation_gaps"
    graph_constraint = "graph_constraint"


class TeachingStrategy(StrEnum):
    direct_explanation = "direct_explanation"
    inline_definition = "inline_definition"
    targeted_diagnostic = "targeted_diagnostic"
    focused_bridge = "focused_bridge"
    proposed_learning_path = "proposed_learning_path"


class ConceptEvidence(ApiModel):
    concept_id: str
    state: Literal[
        "unavailable",
        "unexplored",
        "explored",
        "developing",
        "demonstrated",
        "review_due",
        "misconception_detected",
    ]
    evidence_count: int = Field(default=0, ge=0)
    demonstrated: bool = False
    evidence_ids: list[str] = Field(default_factory=list)


class LearnerEvidenceProjection(ApiModel):
    learner_id: str
    state_version: int = Field(ge=0)
    concepts: list[ConceptEvidence] = Field(default_factory=list)
    interpretation: Literal["uncalibrated_projection"] = "uncalibrated_projection"


class PolicyEdge(ApiModel):
    edge_id: str
    source_concept_id: str
    target_concept_id: str
    support_status: str


class SessionPosition(ApiModel):
    current_concept_id: str | None = None
    current_lesson_id: str | None = None
    state_version: int = Field(ge=1)


class ResolvedTeachingProfile(ApiModel):
    gear: Literal["Quick", "Guided", "Deep"]
    depth: Literal["essential", "scaffolded", "mechanistic"]
    abstraction: Literal["accessible", "balanced", "technical"]
    step_size: Literal["large", "manageable", "fine"]
    derivation: Literal["none", "when_needed", "include"]
    example_mode: Literal["optional", "worked", "worked_with_boundaries"]
    response_mode: Literal["brief_opportunity", "guided_opportunity", "independent_opportunity"]
    local_override: Literal["simplify", "why", "example", "visualize", "check_understanding", "resume", "deepen"] | None = None
    include_intuition: bool = False
    include_assumptions: bool = False
    include_connections: bool = False
    max_examples: int = Field(ge=0, le=2)
    response_opportunity_kind: Literal["brief", "guided", "independent"] = "brief"
    anchor_scope: Literal["lesson", "block", "selection", "branch"] = "lesson"
    visual_spec_kind: Literal["relationship_diagram", "comparison_table", "number_line", "worked_structure", "validated_plot"] | None = None
    # Kept for existing API consumers while visual_spec_kind becomes the typed contract.
    visualize_format: Literal["none", "relationship_diagram_with_text"] = "none"
    profile_version: str = "teaching_profile_v2"


class ActionContext(ApiModel):
    schema_version: Literal["1"] = "1"
    policy_version: str
    action_id: str
    learner_id: str
    session_id: str
    graph_id: str
    graph_revision: int = Field(ge=1)
    graph_publication_state: str
    target_concept_id: str
    target_title: str
    target_objective: str
    target_support_status: str
    session_position: SessionPosition
    teaching_profile: ResolvedTeachingProfile
    learner_evidence: LearnerEvidenceProjection
    request_intent: str
    requires_edges: list[PolicyEdge] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    source_support_statuses: dict[str, str] = Field(default_factory=dict)
    source_policy: Literal["available_graph_sources_only"] = "available_graph_sources_only"
    provider: Literal["deterministic_baseline"] = "deterministic_baseline"


class PrerequisiteIssue(ApiModel):
    outcome: PrerequisiteOutcome
    concept_id: str | None = None
    edge_id: str | None = None
    detail: str


class PrerequisiteResolution(ApiModel):
    outcomes: list[PrerequisiteOutcome]
    prerequisite_ids: list[str] = Field(default_factory=list)
    direct_prerequisite_ids: list[str] = Field(default_factory=list)
    known_prerequisite_ids: list[str] = Field(default_factory=list)
    uncertain_prerequisite_ids: list[str] = Field(default_factory=list)
    gap_prerequisite_ids: list[str] = Field(default_factory=list)
    issues: list[PrerequisiteIssue] = Field(default_factory=list)
    traversed_nodes: int = Field(ge=0)
    max_depth: int = Field(ge=1)
    max_nodes: int = Field(ge=1)


class TeachingPlan(ApiModel):
    id: str
    action_id: str
    session_id: str
    policy_version: str
    plan_version: str = "teaching_plan_v2"
    context_schema_version: str
    target_concept_id: str
    target_objective: str
    known_prerequisite_ids: list[str] = Field(default_factory=list)
    uncertain_prerequisite_ids: list[str] = Field(default_factory=list)
    gap_prerequisite_ids: list[str] = Field(default_factory=list)
    prerequisite_resolution: PrerequisiteResolution
    gap_classification: GapClassification
    strategy: TeachingStrategy
    teaching_profile: ResolvedTeachingProfile
    representation_sequence: list[str] = Field(default_factory=list)
    concepts_to_avoid: list[str] = Field(default_factory=list)
    intended_next_action: Literal[
        "continue_target",
        "await_diagnostic_response",
        "complete_bridge_then_return",
        "offer_path_choice",
        "await_understanding_response",
    ]
    limited: bool = True
    limitation_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class PolicyValidationResult(ApiModel):
    id: str
    action_id: str
    plan_id: str
    policy_version: str
    accepted: bool
    outcome: Literal["accepted", "accepted_limited", "rejected"]
    checks: dict[str, bool] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    source_backed_correctness: Literal[False] = False
    model_verified: Literal[False] = False
    calibrated_mastery: Literal[False] = False
    method: Literal["deterministic_policy_validation"] = "deterministic_policy_validation"
    created_at: datetime = Field(default_factory=utc_now)
