"""Deterministic lesson rendering behind the typed learning policy."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from .models import Concept, GraphVersion
from .model_provider import LessonProvider
from .policy_models import ActionContext, TeachingPlan, TeachingStrategy
from .session_models import ConceptTrust, LessonArtifact, LessonBlock, TeachingActionInput, TeachingGear, TeachingIntent
from .classification.config import min_score, rollout_mode, should_sample_shadow
from .classification.service import ClassificationService


def classify_intent(request: TeachingActionInput) -> TeachingIntent:
    if request.intent != TeachingIntent.teach:
        return request.intent
    message = (request.message or "").lower()
    classifier_mode = rollout_mode("teaching_intent")
    if message and (classifier_mode == "active" or classifier_mode == "shadow" and should_sample_shadow("teaching_intent", message)):
        try:
            decision = ClassificationService().teaching_intent(message)
            if classifier_mode == "active" and decision.score >= min_score("teaching_intent", decision.value, default=0.82):
                return TeachingIntent(decision.value)
        except Exception:
            # A missing JEV key, unavailable usage reservation, or invalid
            # answer leaves the existing deterministic teaching policy intact.
            pass
    rules = (
        (("simpler", "simple", "plain language", "easier"), TeachingIntent.simplify),
        (("example", "apply", "application"), TeachingIntent.example),
        (("why", "how does", "how do"), TeachingIntent.why),
        (("visual", "diagram", "draw"), TeachingIntent.visualize),
        (("test me", "check me", "quiz", "understanding"), TeachingIntent.check_understanding),
        (("continue", "resume", "where i left"), TeachingIntent.resume),
    )
    return next((intent for tokens, intent in rules if any(token in message for token in tokens)), TeachingIntent.teach)


def resolve_concept(graph: GraphVersion, requested_id: str | None) -> Concept:
    if requested_id:
        for concept in graph.concepts:
            if concept.id == requested_id:
                return concept
    return graph.concepts[0]


def _trust(concept: Concept) -> ConceptTrust:
    status = {"supported": "supported", "partial": "partially_supported", "unverified": "insufficient"}.get(
        concept.support_status, "insufficient"
    )
    return ConceptTrust(status=status, source_ids=list(concept.source_ids))


def _representation_block(representation: str, graph: GraphVersion, concept: Concept, plan: TeachingPlan, order: int) -> LessonBlock:
    bodies = {
        "essential_explanation": f"{concept.summary} Focus on the one relationship needed for the current objective before adding detail.",
        "brief_response_opportunity": f"In one sentence, what is {concept.title.lower()} helping you explain?",
        "intuition": f"Build an intuition for {concept.title.lower()} by naming what changes, what stays fixed, and why that matters.",
        "worked_example": f"Use one concrete {graph.title} situation. Identify the starting condition, apply the relationship step by step, and state the observable consequence.",
        "guided_steps": "Step 1: name the relevant parts. Step 2: connect them. Step 3: test whether the connection answers the objective.",
        "guided_response_opportunity": "Which of those three steps feels least certain? Your answer can locate the next useful explanation.",
        "mechanism": f"Explain the mechanism inside {concept.title.lower()}: identify the inputs, the transformation or relationship, and the resulting behavior.",
        "assumptions": "Keep the boundary explicit: identify which conditions the explanation assumes and which claims remain outside this limited graph.",
        "derivation": "Develop the reasoning from the stated assumptions in small steps. This scaffold does not claim that a domain-specific derivation has been source-verified.",
        "boundary_case": "Change one assumption and inspect where the explanation stops applying. A shortcut is not treated as a universal rule.",
        "meaningful_connections": f"Connect the mechanism back to the objective for {concept.title}, without introducing unrelated map concepts.",
        "independent_response_opportunity": f"Explain or apply {concept.title.lower()} in a changed situation without copying the scaffold.",
        "plain_language_definition": f"In everyday language: {concept.summary} Introduce a technical term only when it becomes useful.",
        "causal_or_logical_justification": f"Focus on why the selected claim about {concept.title.lower()} follows: state the premise, connecting reason, and conclusion.",
        "explicit_assumptions": "List the assumptions before using the example so its conclusion is not presented as universally true.",
        "checked_result": "Show how the result would be checked. The deterministic baseline cannot certify domain correctness, so this remains qualified.",
        "response_opportunity": "What part of the relationship would you test next?",
        "relationship_diagram": f"Structured view: {concept.title} → relevant parts → relationship → observable consequence.",
        "labeled_text_equivalent": f"Text equivalent: begin at {concept.title}, follow one labeled relationship, and read the consequence at the final node.",
        "position_recap": f"Resume at {concept.title}. Reopening preserves position; it does not infer progress or mastery.",
        "independent_check": f"Without looking at a worked answer, explain what role {concept.title.lower()} plays in {graph.title} and name one assumption. No answer is revealed here.",
    }
    check_like = representation in {"brief_response_opportunity", "guided_response_opportunity", "independent_response_opportunity", "response_opportunity", "independent_check"}
    kind = "example" if representation in {"worked_example", "explicit_assumptions", "checked_result"} else "visual" if representation == "relationship_diagram" else "check" if check_like else "explanation"
    return LessonBlock(
        id=f"block_{uuid4().hex[:10]}", kind=kind, heading=representation.replace("_", " ").title(), body=bodies[representation],
        concept_ids=[concept.id], source_ids=list(concept.source_ids), trust=_trust(concept), order=order,
        metadata={"representation": representation, "policyVersion": plan.policy_version},
    )


def build_lesson(
    graph: GraphVersion,
    concept: Concept,
    request: TeachingActionInput,
    session_id: str,
    intent: TeachingIntent,
    graph_revision: int,
    action_id: str,
    context: ActionContext,
    plan: TeachingPlan,
    lesson_provider: LessonProvider | None = None,
    note_context: list[dict[str, Any]] | None = None,
) -> LessonArtifact:
    """Render the validated plan. Rendering never creates learner evidence."""

    del request
    trust = _trust(concept)
    blocks: list[LessonBlock] = []
    if plan.strategy == TeachingStrategy.targeted_diagnostic and intent != TeachingIntent.check_understanding:
        prerequisite = plan.uncertain_prerequisite_ids[0] if plan.uncertain_prerequisite_ids else concept.id
        title = next((item.title for item in graph.concepts if item.id == prerequisite), "the prerequisite")
        blocks.append(LessonBlock(
            id=f"block_{uuid4().hex[:10]}", kind="check", heading="One focused diagnostic",
            body=f"Before relying on {title}, explain its role in one sentence. This locates uncertainty; it does not mark the prerequisite failed or demonstrated.",
            concept_ids=[prerequisite], trust=trust, order=0, metadata={"strategy": plan.strategy.value, "answerWithheld": True},
        ))
    elif plan.strategy == TeachingStrategy.focused_bridge:
        prerequisite = plan.gap_prerequisite_ids[0]
        title = next(item.title for item in graph.concepts if item.id == prerequisite)
        blocks.append(LessonBlock(
            id=f"block_{uuid4().hex[:10]}", kind="explanation", heading="Focused prerequisite bridge",
            body=f"Repair only the blocking idea, {title}, then return to {concept.title}. The original objective and lesson position stay fixed.",
            concept_ids=[prerequisite, concept.id], trust=trust, order=0,
            metadata={"strategy": plan.strategy.value, "returnConceptId": concept.id},
        ))
    elif plan.strategy == TeachingStrategy.proposed_learning_path:
        route = plan.prerequisite_resolution.direct_prerequisite_ids or plan.prerequisite_resolution.prerequisite_ids
        blocks.append(LessonBlock(
            id=f"block_{uuid4().hex[:10]}", kind="explanation", heading="Proposed learning path",
            body="The prerequisite route is too uncertain or constrained to start silently. Choose a bridge or an explicitly limited overview.",
            concept_ids=[*route, concept.id], trust=trust, order=0,
            metadata={"strategy": plan.strategy.value, "route": route, "outcomes": [item.value for item in plan.prerequisite_resolution.outcomes]},
        ))
    elif plan.strategy == TeachingStrategy.inline_definition:
        prerequisite = plan.uncertain_prerequisite_ids[0]
        title = next(item.title for item in graph.concepts if item.id == prerequisite)
        blocks.append(LessonBlock(
            id=f"block_{uuid4().hex[:10]}", kind="explanation", heading="Necessary definition",
            body=f"Use {title} only as a short working definition, then continue to {concept.title}; no mastery is assumed.",
            concept_ids=[prerequisite, concept.id], trust=trust, order=0, metadata={"strategy": plan.strategy.value},
        ))

    if lesson_provider is not None:
        provider_input = {
            "graph": graph, "concept": concept, "context": context,
            "plan": plan, "intent": intent,
        }
        if note_context:
            provider_input["note_context"] = note_context
        for generated in lesson_provider.generate(**provider_input):
            blocks.append(LessonBlock(
                id=f"block_{uuid4().hex[:10]}", kind=generated.kind, heading=generated.heading,
                body=generated.body, concept_ids=[concept.id], source_ids=list(concept.source_ids),
                trust=trust, order=len(blocks), metadata={"provider": lesson_provider.provider_name, "planId": plan.id},
            ))
    elif not (plan.strategy == TeachingStrategy.targeted_diagnostic and intent != TeachingIntent.check_understanding):
        for representation in plan.representation_sequence:
            blocks.append(_representation_block(representation, graph, concept, plan, len(blocks)))

    blocks.append(LessonBlock(
        id=f"block_{uuid4().hex[:10]}", kind="source_note", heading="This is a working scaffold",
        body=(
            "This model-assisted response has no retrieved citations or independent verification. "
            "It does not create evidence or make a mastery claim."
            if lesson_provider else
            "The deterministic local provider exercises policy and lesson flow only. It is not source-backed correctness, model verification, evidence, or calibrated mastery."
        ),
        concept_ids=[concept.id], source_ids=list(concept.source_ids), trust=trust, order=len(blocks),
        metadata={"provider": lesson_provider.provider_name if lesson_provider else "deterministic_baseline", "qualified": True, "planId": plan.id},
    ))
    return LessonArtifact(
        id=f"lesson_{uuid4().hex}", session_id=session_id, concept_id=concept.id, graph_revision=graph_revision,
        gear=TeachingGear(context.teaching_profile.gear), title=concept.title, blocks=blocks,
        next_action="repair_prerequisite" if plan.strategy in {TeachingStrategy.focused_bridge, TeachingStrategy.proposed_learning_path} else "continue" if intent == TeachingIntent.check_understanding else "check_understanding",
        status="qualified", teaching_plan_id=plan.id, verification_run_id=action_id,
        generated_by=lesson_provider.provider_name if lesson_provider else "deterministic_baseline",
    )
