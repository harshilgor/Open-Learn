from uuid import uuid4

from fastapi.testclient import TestClient

try:
    import backend.app.main as main_module
    from backend.app.graph_generator import GraphGenerator
    from backend.app.learner_graph import LearnerGraph
    from backend.app.learning_policy import (
        assemble_action_context,
        choose_teaching_plan,
        resolve_prerequisites,
    )
    from backend.app.models import Edge, TopicScope, utc_now
    from backend.app.policy_models import PrerequisiteOutcome
    from backend.app.session_models import LearningSession, TeachingGear, TeachingIntent
except ModuleNotFoundError:
    import app.main as main_module
    from app.graph_generator import GraphGenerator
    from app.learner_graph import LearnerGraph
    from app.learning_policy import assemble_action_context, choose_teaching_plan, resolve_prerequisites
    from app.models import Edge, TopicScope, utc_now
    from app.policy_models import PrerequisiteOutcome
    from app.session_models import LearningSession, TeachingGear, TeachingIntent


client = TestClient(main_module.app)


def make_graph_and_session(topic: str = "policy-fixture", gear: str = "Guided", learner_id: str | None = None) -> tuple[dict, dict]:
    scope = client.post("/v1/topic-scopes", json={"topic": f"{topic}-{uuid4().hex[:8]}"}).json()
    graph = client.post(f"/v1/topic-scopes/{scope['id']}/graph-jobs").json()["graph"]
    session = client.post(
        "/v1/sessions",
        json={"graphId": graph["id"], "learnerId": learner_id or f"learner-{uuid4().hex}", "gear": gear},
    ).json()
    return graph, session


def post_action(session: dict, graph: dict, *, intent: str = "teach", gear: str | None = None, concept_index: int = 0, key: str | None = None):
    headers = {"Idempotency-Key": key} if key else {}
    payload = {"intent": intent, "conceptId": graph["concepts"][concept_index]["id"]}
    if gear:
        payload["gear"] = gear
    return client.post(f"/v1/sessions/{session['id']}/actions", headers=headers, json=payload)


def test_direct_teaching_has_explicit_typed_context_plan_and_validation():
    graph, session = make_graph_and_session()
    response = post_action(session, graph, concept_index=0)
    assert response.status_code == 202
    action = response.json()
    assert action["actionContext"]["targetConceptId"] == graph["concepts"][0]["id"]
    assert action["actionContext"]["learnerEvidence"]["interpretation"] == "uncalibrated_projection"
    assert action["teachingPlan"]["strategy"] == "direct_explanation"
    assert action["teachingPlan"]["gapClassification"] == "none"
    assert action["policyValidation"]["outcome"] == "accepted_limited"
    assert action["policyValidation"]["sourceBackedCorrectness"] is False
    plan_id = action["teachingPlan"]["id"]
    assert client.get(f"/v1/teaching-plans/{plan_id}").json()["id"] == plan_id


def test_uncertain_prerequisite_gets_one_targeted_diagnostic():
    graph, session = make_graph_and_session()
    action = post_action(session, graph, concept_index=1).json()
    plan = action["teachingPlan"]
    assert plan["gapClassification"] == "uncertain_foundation"
    assert plan["strategy"] == "targeted_diagnostic"
    assert plan["intendedNextAction"] == "await_diagnostic_response"
    assert action["lesson"]["blocks"][0]["kind"] == "check"
    assert action["lesson"]["blocks"][0]["metadata"]["answerWithheld"] is True


def test_detected_gap_uses_bridge_while_many_unknowns_offer_a_path():
    learner_id = f"learner-{uuid4().hex}"
    graph, session = make_graph_and_session(learner_id=learner_id)
    projection = client.get(f"/v1/learners/{learner_id}/knowledge-graph").json()
    source_prerequisite = graph["concepts"][0]["id"]
    learner_prerequisite = next(
        concept for concept in projection["concepts"] if source_prerequisite in concept["source_concept_ids"]
    )
    client.post(
        f"/v1/learners/{learner_id}/knowledge-graph/events",
        json={"event_type": "misconception_detected", "concept_id": learner_prerequisite["id"]},
    )
    bridge = post_action(session, graph, concept_index=1).json()["teachingPlan"]
    assert bridge["strategy"] == "focused_bridge"
    assert bridge["intendedNextAction"] == "complete_bridge_then_return"

    _, fresh_session = make_graph_and_session(topic="path", learner_id=f"learner-{uuid4().hex}")
    fresh_graph = client.get(f"/v1/graphs/{fresh_session['graphId']}").json()
    path = post_action(fresh_session, fresh_graph, concept_index=3).json()["teachingPlan"]
    assert path["strategy"] == "proposed_learning_path"
    assert len(path["uncertainPrerequisiteIds"]) >= 2


def _policy_fixture():
    scope = TopicScope(
        id="scope_policy", topic="policy", resolved_meaning="policy", objective="Understand policy", depth="introductory", created_at=utc_now()
    )
    graph = GraphGenerator().generate(scope)
    graph = graph.model_copy(update={
        "publication_state": "published",
        "concepts": [concept.model_copy(update={"support_status": "supported", "source_ids": ["source_reviewed"]}) for concept in graph.concepts],
        "edges": [edge.model_copy(update={"support_status": "supported"}) for edge in graph.edges],
    })
    session = LearningSession(
        id="session_policy", learner_id="learner_policy", graph_id=graph.id, graph_revision=1,
        gear=TeachingGear.guided, created_at=utc_now(), updated_at=utc_now(),
    )
    learner_graph = LearnerGraph(
        id="learner_graph_policy", learner_id="learner_policy", revision=0, state_version=0,
        created_at=utc_now(), updated_at=utc_now(),
    )
    context = assemble_action_context(
        action_id="run_policy", graph=graph, session=session, target_concept_id=graph.concepts[0].id,
        intent=TeachingIntent.teach, gear=TeachingGear.guided, learner_graph=learner_graph,
    )
    return graph, context


def test_prerequisite_cycle_and_budgets_stop_with_clear_outcomes():
    graph, context = _policy_fixture()
    first, second = graph.concepts[:2]
    cyclic = graph.model_copy(update={"edges": [
        Edge(id="requires_1", source=first.id, target=second.id, type="requires", justification="fixture", support_status="supported"),
        Edge(id="requires_2", source=second.id, target=first.id, type="requires", justification="fixture", support_status="supported"),
    ]})
    cycle_context = context.model_copy(update={"target_concept_id": first.id, "target_title": first.title})
    cycle = resolve_prerequisites(cyclic, cycle_context)
    assert PrerequisiteOutcome.cyclic in cycle.outcomes
    cycle_plan = choose_teaching_plan(cyclic, cycle_context, cycle, TeachingIntent.teach)
    assert cycle_plan.strategy.value == "proposed_learning_path"

    chain_target = graph.concepts[4]
    budget_context = context.model_copy(update={"target_concept_id": chain_target.id, "target_title": chain_target.title})
    budget = resolve_prerequisites(graph, budget_context, max_depth=1, max_nodes=12)
    assert PrerequisiteOutcome.excessive in budget.outcomes
    assert budget.traversed_nodes <= budget.max_nodes


def test_missing_and_unsupported_prerequisite_paths_remain_explicitly_limited():
    graph, context = _policy_fixture()
    target = graph.concepts[1]
    unsupported_graph = graph.model_copy(update={"edges": [
        Edge(
            id="unsupported_edge", source=graph.concepts[0].id, target=target.id, type="requires",
            justification="fixture", support_status="inferred",
        )
    ]})
    target_context = context.model_copy(update={"target_concept_id": target.id, "target_title": target.title})
    unsupported = resolve_prerequisites(unsupported_graph, target_context)
    assert unsupported.outcomes == [PrerequisiteOutcome.unsupported]
    unsupported_plan = choose_teaching_plan(unsupported_graph, target_context, unsupported, TeachingIntent.teach)
    assert unsupported_plan.limited is True
    assert "prerequisite_edges_not_source_supported" in unsupported_plan.limitation_reasons

    missing_graph = graph.model_copy(update={"edges": [
        Edge(
            id="missing_edge", source="concept_absent", target=target.id, type="requires",
            justification="fixture", support_status="supported",
        )
    ]})
    missing = resolve_prerequisites(missing_graph, target_context)
    assert missing.outcomes == [PrerequisiteOutcome.missing]
    missing_plan = choose_teaching_plan(missing_graph, target_context, missing, TeachingIntent.teach)
    assert missing_plan.strategy.value == "proposed_learning_path"
    assert "prerequisite_missing" in missing_plan.limitation_reasons


def test_all_teaching_gears_change_policy_dimensions_and_representation_sequence():
    graph, session = make_graph_and_session()
    plans = {}
    for gear in ("Quick", "Guided", "Deep"):
        plans[gear] = post_action(session, graph, gear=gear, key=f"gear-{gear}").json()["teachingPlan"]
    assert plans["Quick"]["teachingProfile"]["depth"] == "essential"
    assert plans["Guided"]["teachingProfile"]["depth"] == "scaffolded"
    assert plans["Deep"]["teachingProfile"]["depth"] == "mechanistic"
    assert plans["Quick"]["representationSequence"] == ["essential_explanation", "brief_response_opportunity"]
    assert "worked_example" in plans["Guided"]["representationSequence"]
    assert "derivation" in plans["Deep"]["representationSequence"]
    assert "boundary_case" in plans["Deep"]["representationSequence"]


def test_each_local_action_is_a_typed_local_override_not_a_prose_hint():
    expected_first = {
        "simplify": "plain_language_definition",
        "why": "causal_or_logical_justification",
        "example": "worked_example",
        "visualize": "relationship_diagram",
        "resume": "position_recap",
        "check_understanding": "independent_check",
        "deepen": "causal_or_logical_justification",
    }
    for intent, representation in expected_first.items():
        graph, session = make_graph_and_session(topic=intent, gear="Deep")
        action = post_action(session, graph, intent=intent).json()
        profile = action["teachingPlan"]["teachingProfile"]
        assert profile["localOverride"] == intent
        assert profile["gear"] == "Deep"
        assert action["teachingPlan"]["representationSequence"][0] == representation
        if intent == "simplify":
            assert profile["depth"] == "mechanistic"
            assert profile["abstraction"] == "accessible"
        if intent == "visualize":
            assert profile["visualizeFormat"] == "relationship_diagram_with_text"


def test_profiles_expose_semantic_dimensions_and_safe_visual_data():
    graph, session = make_graph_and_session(topic="visual-policy", gear="Deep")
    visual = post_action(session, graph, intent="visualize").json()
    profile = visual["teachingPlan"]["teachingProfile"]
    assert profile["profileVersion"] == "teaching_profile_v2"
    assert profile["visualSpecKind"] == "relationship_diagram"
    assert profile["includeAssumptions"] is True
    block = next(item for item in visual["lesson"]["blocks"] if item["kind"] == "visual")
    spec = block["metadata"]["visualSpec"]
    assert spec["kind"] == "relationship_diagram"
    assert "textEquivalent" in spec
    assert "html" not in spec and "javascript" not in spec


def test_session_gear_changes_future_actions_without_rewriting_prior_lesson():
    graph, session = make_graph_and_session(topic="gear-persistence")
    first = post_action(session, graph).json()
    update = client.patch(
        f"/v1/sessions/{session['id']}/gear",
        json={"gear": "Deep", "expectedStateVersion": first["lesson"] and 2},
    )
    assert update.status_code == 200
    assert update.json()["gear"] == "Deep"
    assert client.get(f"/v1/lessons/{first['lesson']['id']}").json()["gear"] == "Guided"
    later = post_action(update.json(), graph).json()
    assert later["teachingPlan"]["teachingProfile"]["gear"] == "Deep"


def test_check_blocks_withhold_answers_and_do_not_create_evidence():
    learner_id = f"learner-{uuid4().hex}"
    graph, session = make_graph_and_session(topic="check-policy", learner_id=learner_id)
    before = client.get(f"/v1/learners/{learner_id}/knowledge-graph").json()
    action = post_action(session, graph, intent="check_understanding").json()
    check = action["lesson"]["blocks"][0]
    assert check["metadata"]["answerWithheld"] is True
    assert check["metadata"]["privateEvaluatorRef"] == "not_configured"
    after = client.get(f"/v1/learners/{learner_id}/knowledge-graph").json()
    assert after["state_version"] == before["state_version"]


def test_idempotent_retry_does_not_duplicate_plan_artifact_or_events():
    graph, session = make_graph_and_session()
    first = post_action(session, graph, key="same-command").json()
    event_count = len(main_module.store.list_events(first["runId"]))
    assert main_module.store.count_artifacts_for_action(first["runId"]) == 1
    repeated = post_action(session, graph, intent="why", key="same-command").json()
    assert repeated["runId"] == first["runId"]
    assert repeated["teachingPlan"]["id"] == first["teachingPlan"]["id"]
    assert main_module.store.count_artifacts_for_action(first["runId"]) == 1
    assert len(main_module.store.list_events(first["runId"])) == event_count


def test_lesson_reading_and_action_failure_do_not_advance_learner_state(monkeypatch):
    learner_id = f"learner-{uuid4().hex}"
    graph, session = make_graph_and_session(learner_id=learner_id)
    before = client.get(f"/v1/learners/{learner_id}/knowledge-graph").json()
    action = post_action(session, graph).json()
    assert client.get(f"/v1/lessons/{action['lesson']['id']}").status_code == 200
    after_read = client.get(f"/v1/learners/{learner_id}/knowledge-graph").json()
    assert after_read["state_version"] == before["state_version"]
    assert [item["state"] for item in after_read["concepts"]] == [item["state"] for item in before["concepts"]]
    assert [item["evidence_count"] for item in after_read["concepts"]] == [item["evidence_count"] for item in before["concepts"]]

    fresh_graph, fresh_session = make_graph_and_session(topic="failure", learner_id=learner_id)
    session_before = client.get(f"/v1/sessions/{fresh_session['id']}").json()
    learner_before_failure = client.get(f"/v1/learners/{learner_id}/knowledge-graph").json()

    def fail_render(*args, **kwargs):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(main_module, "build_lesson", fail_render)
    failed = post_action(fresh_session, fresh_graph, key="failing-command")
    assert failed.status_code == 500
    session_after = client.get(f"/v1/sessions/{fresh_session['id']}").json()
    learner_after_failure = client.get(f"/v1/learners/{learner_id}/knowledge-graph").json()
    assert session_after["stateVersion"] == session_before["stateVersion"]
    assert session_after["currentLessonId"] == session_before["currentLessonId"]
    assert learner_after_failure["state_version"] == learner_before_failure["state_version"]


def test_action_update_preserves_idempotency_and_policy_records():
    graph, session = make_graph_and_session()
    first = post_action(session, graph, key="preserve-command").json()
    action = main_module.store.get_action(first["runId"])
    # A later status write can omit the original command key.
    main_module.store.save_action(action)
    repeated = post_action(session, graph, key="preserve-command").json()
    assert repeated["runId"] == first["runId"]
    validation = main_module.store.get_policy_validation(first["runId"])
    assert validation.plan_id == first["teachingPlan"]["id"]
    assert main_module.store.count_artifacts_for_action(first["runId"]) == 1
