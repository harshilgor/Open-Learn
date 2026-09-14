"""Deterministic, unit-testable planning policy for teaching actions."""

from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

from .learner_graph import LearnerGraph
from .models import GraphVersion
from .policy_models import (
    ActionContext,
    ConceptEvidence,
    GapClassification,
    LearnerEvidenceProjection,
    PolicyEdge,
    PolicyValidationResult,
    PrerequisiteIssue,
    PrerequisiteOutcome,
    PrerequisiteResolution,
    ResolvedTeachingProfile,
    SessionPosition,
    TeachingPlan,
    TeachingStrategy,
)
from .session_models import LearningSession, TeachingGear, TeachingIntent


POLICY_VERSION = "teaching_policy_v2"
DEFAULT_MAX_PREREQUISITE_DEPTH = 4
DEFAULT_MAX_PREREQUISITE_NODES = 12


def resolve_teaching_profile(
    gear: TeachingGear,
    intent: TeachingIntent,
    *,
    has_block_anchor: bool = False,
    has_selection_anchor: bool = False,
    is_branch: bool = False,
) -> ResolvedTeachingProfile:
    """Compile the persistent gear and one local action into explicit dimensions."""

    defaults = {
        TeachingGear.quick: dict(
            depth="essential",
            abstraction="balanced",
            step_size="large",
            derivation="none",
            example_mode="optional",
            response_mode="brief_opportunity", include_intuition=False, include_assumptions=False,
            include_connections=False, max_examples=1, response_opportunity_kind="brief",
        ),
        TeachingGear.guided: dict(
            depth="scaffolded",
            abstraction="balanced",
            step_size="manageable",
            derivation="when_needed",
            example_mode="worked",
            response_mode="guided_opportunity", include_intuition=True, include_assumptions=False,
            include_connections=True, max_examples=1, response_opportunity_kind="guided",
        ),
        TeachingGear.deep: dict(
            depth="mechanistic",
            abstraction="technical",
            step_size="fine",
            derivation="include",
            example_mode="worked_with_boundaries",
            response_mode="independent_opportunity", include_intuition=True, include_assumptions=True,
            include_connections=True, max_examples=2, response_opportunity_kind="independent",
        ),
    }
    values = defaults[gear].copy()
    local_override = None if intent == TeachingIntent.teach else intent.value
    visual_spec_kind = None
    visualize_format = "none"
    if intent == TeachingIntent.simplify:
        # Depth and derivation remain owned by the gear. This makes Deep +
        # Simplify thorough but accessible instead of silently becoming Quick.
        values.update(abstraction="accessible", step_size="fine")
    elif intent == TeachingIntent.example:
        values["example_mode"] = "worked_with_boundaries"
    elif intent == TeachingIntent.visualize:
        visual_spec_kind = "relationship_diagram"
        visualize_format = "relationship_diagram_with_text"
    elif intent == TeachingIntent.check_understanding:
        values["response_mode"] = "independent_opportunity"
        values["response_opportunity_kind"] = "independent"
    elif intent in {TeachingIntent.why, TeachingIntent.deepen}:
        values.update(include_assumptions=True, include_connections=True)
    anchor_scope = "branch" if is_branch else "selection" if has_selection_anchor else "block" if has_block_anchor else "lesson"
    return ResolvedTeachingProfile(
        gear=gear.value,
        local_override=local_override,
        visual_spec_kind=visual_spec_kind,
        visualize_format=visualize_format,
        anchor_scope=anchor_scope,
        **values,
    )


def _evidence_projection(graph: GraphVersion, learner_graph: LearnerGraph) -> LearnerEvidenceProjection:
    projected_by_source: dict[str, ConceptEvidence] = {}
    for item in learner_graph.concepts:
        for source_id in item.source_concept_ids:
            if graph.id not in item.source_graph_ids:
                continue
            projected_by_source[source_id] = ConceptEvidence(
                concept_id=source_id,
                state=item.state,
                evidence_count=item.evidence_count,
                demonstrated=item.state == "demonstrated",
            )
    concepts = [
        projected_by_source.get(concept.id, ConceptEvidence(concept_id=concept.id, state="unavailable"))
        for concept in graph.concepts
    ]
    return LearnerEvidenceProjection(
        learner_id=learner_graph.learner_id,
        state_version=learner_graph.state_version,
        concepts=concepts,
    )


def assemble_action_context(
    *,
    action_id: str,
    graph: GraphVersion,
    session: LearningSession,
    target_concept_id: str,
    intent: TeachingIntent,
    gear: TeachingGear,
    learner_graph: LearnerGraph,
    has_block_anchor: bool = False,
    has_selection_anchor: bool = False,
    is_branch: bool = False,
) -> ActionContext:
    target = next(concept for concept in graph.concepts if concept.id == target_concept_id)
    return ActionContext(
        policy_version=POLICY_VERSION,
        action_id=action_id,
        learner_id=session.learner_id,
        session_id=session.id,
        graph_id=graph.id,
        graph_revision=session.graph_revision,
        graph_publication_state=graph.publication_state,
        target_concept_id=target.id,
        target_title=target.title,
        target_objective=target.objective or session.goal or graph.description,
        target_support_status=target.support_status,
        session_position=SessionPosition(
            current_concept_id=session.current_concept_id,
            current_lesson_id=session.current_lesson_id,
            state_version=session.state_version,
        ),
        teaching_profile=resolve_teaching_profile(gear, intent, has_block_anchor=has_block_anchor, has_selection_anchor=has_selection_anchor, is_branch=is_branch),
        learner_evidence=_evidence_projection(graph, learner_graph),
        request_intent=intent.value,
        requires_edges=[
            PolicyEdge(
                edge_id=edge.id,
                source_concept_id=edge.source,
                target_concept_id=edge.target,
                support_status=edge.support_status,
            )
            for edge in graph.edges
            if edge.type == "requires"
        ],
        source_ids=list(target.source_ids),
        source_support_statuses={
            source_id: next(
                (source.support_status for source in graph.sources if source.id == source_id),
                "missing",
            )
            for source_id in target.source_ids
        },
    )


def resolve_prerequisites(
    graph: GraphVersion,
    context: ActionContext,
    *,
    max_depth: int = DEFAULT_MAX_PREREQUISITE_DEPTH,
    max_nodes: int = DEFAULT_MAX_PREREQUISITE_NODES,
) -> PrerequisiteResolution:
    """Traverse only incoming ``requires`` edges with hard cycle/budget stops."""

    concepts = {concept.id: concept for concept in graph.concepts}
    incoming = defaultdict(list)
    for edge in graph.edges:
        if edge.type == "requires":
            incoming[edge.target].append(edge)
    for edges in incoming.values():
        edges.sort(key=lambda edge: (edge.source, edge.id))

    prerequisites: list[str] = []
    direct: list[str] = []
    issues: list[PrerequisiteIssue] = []
    visited: set[str] = set()

    def add_issue(outcome: PrerequisiteOutcome, detail: str, *, concept_id: str | None = None, edge_id: str | None = None) -> None:
        candidate = PrerequisiteIssue(outcome=outcome, concept_id=concept_id, edge_id=edge_id, detail=detail)
        if candidate not in issues:
            issues.append(candidate)

    def visit(current_id: str, depth: int, path: tuple[str, ...]) -> None:
        for edge in incoming.get(current_id, []):
            prerequisite_id = edge.source
            if prerequisite_id not in concepts:
                add_issue(
                    PrerequisiteOutcome.missing,
                    "A requires edge points to a concept that is absent from this graph version.",
                    concept_id=prerequisite_id,
                    edge_id=edge.id,
                )
                continue
            if depth == 0 and prerequisite_id not in direct:
                direct.append(prerequisite_id)
            if edge.support_status not in {"supported", "partial"}:
                add_issue(
                    PrerequisiteOutcome.unsupported,
                    "The prerequisite relationship is proposed rather than source-supported.",
                    concept_id=prerequisite_id,
                    edge_id=edge.id,
                )
            if prerequisite_id in path:
                add_issue(
                    PrerequisiteOutcome.cyclic,
                    "The requires path loops back to an active concept.",
                    concept_id=prerequisite_id,
                    edge_id=edge.id,
                )
                continue
            if depth + 1 > max_depth:
                add_issue(
                    PrerequisiteOutcome.excessive,
                    f"The requires path exceeds the configured depth budget of {max_depth}.",
                    concept_id=prerequisite_id,
                    edge_id=edge.id,
                )
                continue
            if prerequisite_id not in visited and len(visited) >= max_nodes:
                add_issue(
                    PrerequisiteOutcome.excessive,
                    f"The requires path exceeds the configured node budget of {max_nodes}.",
                    concept_id=prerequisite_id,
                    edge_id=edge.id,
                )
                continue
            if prerequisite_id in visited:
                continue
            visited.add(prerequisite_id)
            prerequisites.append(prerequisite_id)
            visit(prerequisite_id, depth + 1, (*path, prerequisite_id))

    visit(context.target_concept_id, 0, (context.target_concept_id,))
    evidence = {item.concept_id: item for item in context.learner_evidence.concepts}
    known = [item for item in prerequisites if evidence.get(item) and evidence[item].demonstrated]
    gaps = [
        item
        for item in prerequisites
        if evidence.get(item) and evidence[item].state == "misconception_detected"
    ]
    uncertain = [item for item in prerequisites if item not in known and item not in gaps]
    outcomes: list[PrerequisiteOutcome] = []
    for outcome in PrerequisiteOutcome:
        if any(issue.outcome == outcome for issue in issues):
            outcomes.append(outcome)
    if not outcomes:
        outcomes.append(PrerequisiteOutcome.complete)
    return PrerequisiteResolution(
        outcomes=outcomes,
        prerequisite_ids=prerequisites,
        direct_prerequisite_ids=direct,
        known_prerequisite_ids=known,
        uncertain_prerequisite_ids=uncertain,
        gap_prerequisite_ids=gaps,
        issues=issues,
        traversed_nodes=len(visited),
        max_depth=max_depth,
        max_nodes=max_nodes,
    )


def _base_representations(profile: ResolvedTeachingProfile) -> list[str]:
    if profile.gear == TeachingGear.quick.value:
        return ["essential_explanation", "brief_response_opportunity"]
    if profile.gear == TeachingGear.guided.value:
        return ["intuition", "worked_example", "guided_steps", "guided_response_opportunity"]
    return [
        "mechanism",
        "assumptions",
        "derivation",
        "boundary_case",
        "meaningful_connections",
        "independent_response_opportunity",
    ]


def _apply_local_override(sequence: list[str], intent: TeachingIntent) -> list[str]:
    if intent == TeachingIntent.simplify:
        return ["plain_language_definition", *sequence]
    if intent in {TeachingIntent.why, TeachingIntent.deepen}:
        return ["causal_or_logical_justification", *sequence]
    if intent == TeachingIntent.example:
        return ["worked_example", "explicit_assumptions", "checked_result", "response_opportunity"]
    if intent == TeachingIntent.visualize:
        return ["relationship_diagram", "labeled_text_equivalent", "response_opportunity"]
    if intent == TeachingIntent.resume:
        return ["position_recap", *sequence]
    if intent == TeachingIntent.check_understanding:
        return ["independent_check"]
    return sequence


def choose_teaching_plan(
    graph: GraphVersion,
    context: ActionContext,
    prerequisite_resolution: PrerequisiteResolution,
    intent: TeachingIntent,
) -> TeachingPlan:
    blocking_outcomes = {
        PrerequisiteOutcome.missing,
        PrerequisiteOutcome.cyclic,
        PrerequisiteOutcome.excessive,
    }
    if any(item in blocking_outcomes for item in prerequisite_resolution.outcomes):
        gap = GapClassification.graph_constraint
        strategy = TeachingStrategy.proposed_learning_path
        next_action = "offer_path_choice"
    elif len(prerequisite_resolution.gap_prerequisite_ids) > 1:
        gap = GapClassification.multiple_foundation_gaps
        strategy = TeachingStrategy.proposed_learning_path
        next_action = "offer_path_choice"
    elif prerequisite_resolution.gap_prerequisite_ids:
        gap = GapClassification.missing_foundation
        strategy = TeachingStrategy.focused_bridge
        next_action = "complete_bridge_then_return"
    elif prerequisite_resolution.uncertain_prerequisite_ids:
        gap = GapClassification.uncertain_foundation
        if context.teaching_profile.gear == TeachingGear.quick.value and len(prerequisite_resolution.direct_prerequisite_ids) == 1:
            strategy = TeachingStrategy.inline_definition
            next_action = "continue_target"
        elif len(prerequisite_resolution.uncertain_prerequisite_ids) == 1:
            strategy = TeachingStrategy.targeted_diagnostic
            next_action = "await_diagnostic_response"
        else:
            strategy = TeachingStrategy.proposed_learning_path
            next_action = "offer_path_choice"
    else:
        gap = GapClassification.none
        strategy = TeachingStrategy.direct_explanation
        next_action = "continue_target"

    if intent == TeachingIntent.check_understanding:
        strategy = TeachingStrategy.targeted_diagnostic
        next_action = "await_understanding_response"

    prerequisite_ids = set(prerequisite_resolution.prerequisite_ids)
    concepts_to_avoid = [
        concept.id
        for concept in graph.concepts
        if concept.id != context.target_concept_id and concept.id not in prerequisite_ids
    ]
    limitations: list[str] = []
    # This provider can exercise policy deterministically, but it never turns
    # a plan into source-backed domain verification by itself.
    limitations.append("deterministic_provider_not_domain_verifier")
    if graph.publication_state != "published":
        limitations.append("graph_not_published")
    if context.target_support_status != "supported":
        limitations.append("target_not_source_supported")
    if not context.source_ids:
        limitations.append("target_has_no_source_bindings")
    elif "missing" in context.source_support_statuses.values():
        limitations.append("source_reference_missing")
    if any(status != "supported" for status in context.source_support_statuses.values()):
        limitations.append("source_reference_not_supported")
    if PrerequisiteOutcome.unsupported in prerequisite_resolution.outcomes:
        limitations.append("prerequisite_edges_not_source_supported")
    for item in prerequisite_resolution.outcomes:
        if item in blocking_outcomes:
            limitations.append(f"prerequisite_{item.value}")

    return TeachingPlan(
        id=f"plan_{uuid4().hex}",
        action_id=context.action_id,
        session_id=context.session_id,
        policy_version=POLICY_VERSION,
        context_schema_version=context.schema_version,
        target_concept_id=context.target_concept_id,
        target_objective=context.target_objective,
        known_prerequisite_ids=prerequisite_resolution.known_prerequisite_ids,
        uncertain_prerequisite_ids=prerequisite_resolution.uncertain_prerequisite_ids,
        gap_prerequisite_ids=prerequisite_resolution.gap_prerequisite_ids,
        prerequisite_resolution=prerequisite_resolution,
        gap_classification=gap,
        strategy=strategy,
        teaching_profile=context.teaching_profile,
        representation_sequence=_apply_local_override(_base_representations(context.teaching_profile), intent),
        concepts_to_avoid=concepts_to_avoid,
        intended_next_action=next_action,  # type: ignore[arg-type]
        limited=bool(limitations),
        limitation_reasons=limitations,
    )


def validate_teaching_plan(graph: GraphVersion, context: ActionContext, plan: TeachingPlan) -> PolicyValidationResult:
    graph_concept_ids = {concept.id for concept in graph.concepts}
    checks = {
        "action_matches_context": plan.action_id == context.action_id,
        "session_matches_context": plan.session_id == context.session_id,
        "target_is_fixed": plan.target_concept_id == context.target_concept_id,
        "target_exists": plan.target_concept_id in graph_concept_ids,
        "only_graph_concepts_referenced": all(
            concept_id in graph_concept_ids
            for concept_id in (
                plan.known_prerequisite_ids
                + plan.uncertain_prerequisite_ids
                + plan.gap_prerequisite_ids
                + plan.concepts_to_avoid
            )
        ),
        "target_not_avoided": plan.target_concept_id not in plan.concepts_to_avoid,
        "prerequisite_budget_respected": plan.prerequisite_resolution.traversed_nodes
        <= plan.prerequisite_resolution.max_nodes,
        "unsupported_material_is_limited": (
            PrerequisiteOutcome.unsupported not in plan.prerequisite_resolution.outcomes or plan.limited
        ),
        "deterministic_provider_is_qualified": plan.limited,
        "profile_is_auditable": bool(plan.teaching_profile.profile_version) and bool(plan.plan_version),
        "check_withholds_answer": (
            context.request_intent != TeachingIntent.check_understanding.value
            or plan.representation_sequence == ["independent_check"]
        ),
    }
    accepted = all(checks.values())
    outcome = "rejected" if not accepted else ("accepted_limited" if plan.limited else "accepted")
    limitations = list(plan.limitation_reasons)
    limitations.append("deterministic_baseline_does_not_establish_domain_correctness")
    return PolicyValidationResult(
        id=f"validation_{uuid4().hex}",
        action_id=context.action_id,
        plan_id=plan.id,
        policy_version=POLICY_VERSION,
        accepted=accepted,
        outcome=outcome,  # type: ignore[arg-type]
        checks=checks,
        limitations=list(dict.fromkeys(limitations)),
    )
