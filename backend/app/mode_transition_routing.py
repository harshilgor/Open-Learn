"""Shared mode classification for the legacy endpoint and generation command."""
from __future__ import annotations

from .journey_service import JourneyService
from .material_service import MaterialService, problem
from .mode_transition_models import ModeClassificationRequest
from .mode_transition_service import ModeTransitionService


def classify_mode_for_session(store, owner: str, session_id: str,
                              command: ModeClassificationRequest, provider=None):
    session = MaterialService(store).session(owner, session_id)
    journey = JourneyService(store, None).get(owner, session_id)
    transitions = ModeTransitionService(store)
    if command.bypass_suggestion_id and not transitions.valid_bypass(
            owner, session_id, command.bypass_suggestion_id):
        problem("transition_unavailable", "This transition request has expired.", 409)

    graph = store.get_graph(session.graph_id)
    steps = journey.get("steps", [])
    position = min(journey.get("position", 0), max(0, len(steps) - 1))
    concept_title = steps[position].get("title") if steps else (graph.title if graph else session.goal)
    concept_id = steps[position].get("conceptId") if steps else session.current_concept_id
    result = transitions.classify(
        command.message, journey.get("turns", []), command.current_mode,
        session_id=session_id, owner=owner, concept_title=concept_title,
        concept_id=concept_id, course_id=session.course_id, provider=provider,
        bypass_suggestion_id=command.bypass_suggestion_id,
    )
    if result.suggestion:
        suggestion = result.suggestion.model_copy(update={
            "source_turn_id": f"request:{session_id}:{journey.get('revision', 1)}",
            "mode_revision": journey.get("modeRevision", 1),
        })
        result.suggestion = suggestion
        transitions.attach_suggestion_metadata(owner, session_id, suggestion)
    return result
