"""Policies are tested against real persistence and durable HTTP commands."""
import json
from datetime import timedelta

import pytest
from fastapi import HTTPException

from backend.tests.test_learning_workflows import env, command, Provider
from backend.app.assessment_profiles import profile_snapshot, resolve_provider, approved_tariff, schema_for_transport
from backend.app.model_provider import OpenRouterLessonProvider, ModelProviderError
from backend.app.assessment_numeric import arithmetic, verify
from backend.app.assessment_models import NumericCheck
from backend.app.adaptive_question_planner import choose_question_plan
from backend.app.assessment_benchmark import fixtures
from backend.app.quiz_policy import remaining_seconds, start_answering, stop_answering, public_attempt, public_presentation
from backend.app.quiz_service import QuizService
from backend.app.models import utc_now
from backend.app.workflow_store import WorkflowStore
from backend.app.state_service import LearnerStateService


def test_model_roles_do_not_mutate_shared_provider(monkeypatch):
    monkeypatch.setenv("AI_TUTOR_ASSESSMENT_MODEL_PROFILES", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    base = OpenRouterLessonProvider("base-key", "openrouter/free", None, None)
    profiles = profile_snapshot()
    author = resolve_provider(base, "quiz_author", profiles)
    assert author is not base and base.model == "openrouter/free"
    assert author.model == "openai/gpt-6.1-sol" and author.assessment_profile["effort"] == "high"
    assert "test-key" not in json.dumps(profiles)
    monkeypatch.setenv("AI_TUTOR_QUIZ_AUTHOR_EFFORT", "invalid")
    with pytest.raises(ModelProviderError):
        profile_snapshot()


def test_paid_role_requires_pinned_tariff(monkeypatch):
    monkeypatch.setenv("AI_TUTOR_ASSESSMENT_MODEL_PROFILES", "true")
    profile = profile_snapshot()["quiz_author"]
    with pytest.raises(ValueError):
        approved_tariff(profile["model"], profile)
    monkeypatch.setenv("OPENLEARN_ASSESSMENT_RATE_VERSION", "catalog-20261009")
    monkeypatch.setenv("OPENLEARN_ASSESSMENT_MODEL_TARIFFS", json.dumps({"openrouter/openai/gpt-6.1-sol": {
        "usd_per_million_input": 2, "usd_per_million_output": 10, "usd_per_million_cache_read": .1}}))
    profile = profile_snapshot()["quiz_author"]
    assert approved_tariff(profile["model"], profile)["usd_per_million_output"] == 10
    monkeypatch.setenv("AI_TUTOR_ASSESSMENT_MODEL_PROFILES", "false")
    assert approved_tariff(profile["model"], profile)["usd_per_million_output"] == 10
    with pytest.raises(ValueError):
        approved_tariff(profile["model"], {**profile, "maxOutputTokens": 15000})


def test_numeric_verifier_is_bounded_and_not_code():
    assert arithmetic("(8 + 4) / 3") == 4
    assert verify(NumericCheck(expression="12 / 3", expected=4))
    assert not verify(NumericCheck(expression="12 / 3", expected=5))
    for expression in ("__import__('os').getcwd()", "2 ** 100000", "1 / 0", "x + 1"):
        assert not verify(NumericCheck(expression=expression, expected=4))


def test_diagnostic_preserves_coverage_and_count():
    quiz = {"id": "q", "count": 4, "conceptIds": ["a", "b"], "sessionPlan": {
        "schemaVersion": 2, "challengePreference": "challenge_me", "diagnosticsEnabled": True, "diagnosticBudget": 1}}
    attempts = [{"id": "answer", "conceptId": "a", "status": "uncertain", "response": "A substantive but unclear explanation."}]
    plan = choose_question_plan(quiz, attempts)
    assert plan.parent_attempt_id == "answer" and plan.concept_id == "a"
    attempts += [{"id": "follow", "conceptId": "a", "status": "uncertain", "response": "Still unclear", "questionPlan": plan.model_dump()}]
    assert choose_question_plan(quiz, attempts).concept_id == "b"
    quiz["count"] = 2
    assert choose_question_plan(quiz, attempts[:1]).concept_id == "b"


def test_timer_only_consumes_answering_intervals():
    now = utc_now()
    quiz = {"mode": "timed_short_quiz", "remainingSeconds": 100,
        "sessionPlan": {"timingPolicy": "answering-v2"}, "answeringStartedAt": (now - timedelta(seconds=25)).isoformat()}
    assert remaining_seconds(quiz, now) == 75
    stop_answering(quiz, now)
    assert remaining_seconds(quiz, now + timedelta(minutes=5)) == 75
    start_answering(quiz)
    assert quiz["deadlineAt"] and quiz["answeringStartedAt"]


def test_public_serializers_withhold_private_data():
    value = {"id": "p", "stem": "Question", "options": [], "solution": "SECRET", "modelProfiles": {}, "hints": ["SECRET"],
        "questionPlan": {"public_objective": "Apply the idea", "diagnostic_distinction": {"answer": "SECRET"}}}
    assert "SECRET" not in json.dumps(public_presentation(value, True))
    attempt = {"id": "a", "score": 1, "feedback": "SECRET", "solution": "SECRET", "correctIds": ["SECRET"], "criteria": [], "feedbackDetails": {"explanation": "SECRET"}}
    assert "SECRET" not in json.dumps(public_attempt(attempt, True))


def test_benchmark_has_holdout_and_no_invented_ratings():
    cases = fixtures()
    assert len(cases) == 30 and len({case["id"] for case in cases}) == 30
    assert sum(case["split"] == "holdout" for case in cases) == 6
    assert all(case["humanReviewStatus"] == "pending" for case in cases)


def prepare_v2(env, monkeypatch, **settings):
    monkeypatch.setenv("AI_TUTOR_QUIZ_V2", "true")
    monkeypatch.setenv("AI_TUTOR_ASSESSMENT_MODEL_PROFILES", "false")
    client, store, provider, session = env
    original = provider.complete_json
    def complete(prompt, max_tokens=4000):
        result = original(prompt, max_tokens)
        if prompt.startswith("You author") and result["kind"] != "short":
            result["distractor_rationale"] = [{"option_id": "a", "reason": "Keeps the full population despite the condition."}]
        if prompt.startswith("Independently"):
            result.update(skill_alignment="pass", visible_cues="pass", reasoning_depth="pass")
        return result
    provider.complete_json = complete
    created = command(client, "/quizzes", {"sessionId": session.id, "count": 2, **settings})
    assert created["status"] == "completed", created
    qid = created["result"]["quizId"]
    prepared = command(client, f"/quizzes/{qid}/next", {"expectedRevision": 1})
    assert prepared["status"] == "completed", prepared
    return client, store, provider, client.get(f"/v1/quizzes/{qid}").json()


def test_exam_withholds_answers_and_evidence_until_finish(env, monkeypatch):
    client, store, provider, quiz = prepare_v2(env, monkeypatch, feedbackPolicy="exam_deferred")
    qid, pid = quiz["id"], quiz["current"]["id"]
    result = command(client, f"/quizzes/{qid}/attempts", {"presentationId": pid, "expectedRevision": quiz["revision"], "selectedIds": ["b"]})
    assert result["status"] == "completed", result
    public = client.get(f"/v1/quizzes/{qid}").json()
    assert public["attempts"][0]["status"] == "submitted" and public["summary"]["score"] is None
    assert "solution" not in public["attempts"][0]
    assert not LearnerStateService(store).list_evidence("local")
    finish = command(client, f"/quizzes/{qid}/finish", {"expectedRevision": public["revision"]})
    assert finish["status"] == "completed", finish
    final = client.get(f"/v1/quizzes/{qid}").json()
    assert final["status"] == "completed" and final["attempts"][0]["solution"]
    assert final["summary"]["score"] == 100
    assert len(LearnerStateService(store).list_evidence("local")) == 1


def test_v2_spec_public_objective_and_private_profiles(env, monkeypatch):
    client, store, _, quiz = prepare_v2(env, monkeypatch, challengePreference="challenge_me")
    assert quiz["sessionPlan"]["challengePreference"] == "challenge_me"
    assert quiz["current"]["questionPlan"]["public_objective"]
    assert "modelProfiles" not in json.dumps(quiz)
    stored = WorkflowStore(store).read("local", quiz["id"], "quiz")
    assert stored["sessionPlan"]["schemaVersion"] == 2


def test_invalid_submission_does_not_pause_timer(env, monkeypatch):
    client, store, _, quiz = prepare_v2(env, monkeypatch, mode="timed_short_quiz", modeConfig={"duration_seconds": 300})
    failed = command(client, f"/quizzes/{quiz['id']}/attempts", {"presentationId": quiz["current"]["id"], "expectedRevision": quiz["revision"], "selectedIds": ["missing"]})
    assert failed["status"] == "failed"
    public = client.get(f"/v1/quizzes/{quiz['id']}").json()
    assert public["deadlineAt"] and not public["checkingAnswer"]


def test_checking_reservation_survives_reload_and_stops_answering(env, monkeypatch):
    client, store, provider, quiz = prepare_v2(env, monkeypatch, mode="timed_short_quiz", modeConfig={"duration_seconds": 300})
    from backend.app.assessment_models import AnswerCommand
    service = QuizService(store, provider)
    prepared = service.grade("local", quiz["id"], AnswerCommand(presentation_id=quiz["current"]["id"], expected_revision=quiz["revision"], selected_ids=["b"]))
    during = service.public("local", quiz["id"])
    assert during["checkingAnswer"] and during["deadlineAt"] is None
    with store.transaction() as conn:
        service.commit_grade(conn, "local", prepared)
    after = service.public("local", quiz["id"])
    assert not after["checkingAnswer"] and after["deadlineAt"] is None
    assert after["remainingSeconds"] <= during["remainingSeconds"] + .01


def test_background_candidate_is_not_exposed_until_promotion(env, monkeypatch):
    from backend.app.learning_routes import run_job
    from sqlalchemy import text
    monkeypatch.setenv("AI_TUTOR_QUIZ_PREFETCH", "true")
    client, store, provider, quiz = prepare_v2(env, monkeypatch)
    original = provider.complete_json
    def varied(prompt, max_tokens=4000):
        result = original(prompt, max_tokens)
        if prompt.startswith("You author"):
            data, _ = json.JSONDecoder().raw_decode(prompt[prompt.index('\n{') + 1:])
            if data["context"]["questionNumber"] > 1:
                result["stem"] = "A selected sample omits incompatible observations. Explain which reference population remains when a condition is known, and whether that implies a causal mechanism in a new experiment."
        return result
    provider.complete_json = varied
    answered = command(client, f"/quizzes/{quiz['id']}/attempts", {"presentationId": quiz["current"]["id"], "expectedRevision": quiz["revision"], "selectedIds": ["b"]})
    assert answered["status"] == "completed"
    with store.engine.connect() as conn:
        identifier = conn.execute(text("SELECT id FROM learning_jobs WHERE target_id=:qid AND kind='quiz_prefetch'"), {"qid": quiz["id"]}).scalar_one()
        before = conn.execute(text("SELECT COUNT(*) FROM assessment_presentation_links")).scalar_one()
    run_job(store, provider, identifier)
    assert WorkflowStore(store).job("local", identifier)["status"] == "completed"
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM assessment_presentation_links")).scalar_one() == before
    public = client.get(f"/v1/quizzes/{quiz['id']}").json()
    previous_calls = len(provider.prompts)
    next_job = command(client, f"/quizzes/{quiz['id']}/next", {"expectedRevision": public["revision"]})
    assert next_job["status"] == "completed", next_job
    assert len(provider.prompts) == previous_calls


def test_source_deletion_fences_prepared_candidate(env, monkeypatch):
    from sqlalchemy import text
    client, store, provider, quiz = prepare_v2(env, monkeypatch)
    with store.transaction() as conn:
        conn.execute(text("UPDATE materials SET deleted=true WHERE owner_id='local'"))
    stored = WorkflowStore(store).read("local", quiz["id"], "quiz")
    presentation = WorkflowStore(store).read("local", stored["current"], "presentation")
    with store.engine.connect() as conn, pytest.raises(HTTPException):
        QuizService(store, provider)._validate_sources(conn, "local", stored, presentation)


def test_distinct_jobs_cannot_grade_one_submission_twice(env, monkeypatch):
    from backend.app.assessment_models import AnswerCommand
    _, store, provider, quiz = prepare_v2(env, monkeypatch)
    service = QuizService(store, provider)
    answer = AnswerCommand(presentation_id=quiz["current"]["id"], expected_revision=quiz["revision"], selected_ids=["b"])
    service.grade("local", quiz["id"], answer, job_id="first-job")
    with pytest.raises(HTTPException) as error:
        service.grade("local", quiz["id"], answer, job_id="second-job")
    assert error.value.detail["code"] == "answer_checking"


def test_source_deletion_during_grading_cannot_admit_evidence(env, monkeypatch):
    from backend.app.assessment_models import AnswerCommand
    from sqlalchemy import text
    _, store, provider, quiz = prepare_v2(env, monkeypatch)
    service = QuizService(store, provider)
    prepared = service.grade("local", quiz["id"], AnswerCommand(presentation_id=quiz["current"]["id"], expected_revision=quiz["revision"], selected_ids=["b"]))
    with store.transaction() as conn:
        conn.execute(text("UPDATE materials SET deleted=true WHERE owner_id='local'"))
    with pytest.raises(HTTPException), store.transaction() as conn:
        service.commit_grade(conn, "local", prepared)
    assert not LearnerStateService(store).list_evidence("local")


def test_finish_cannot_release_an_answer_being_checked(env, monkeypatch):
    from backend.app.assessment_models import AnswerCommand
    _, store, provider, quiz = prepare_v2(env, monkeypatch, feedbackPolicy="exam_deferred")
    service = QuizService(store, provider)
    service.grade("local", quiz["id"], AnswerCommand(presentation_id=quiz["current"]["id"], expected_revision=quiz["revision"], selected_ids=["b"]), job_id="grading")
    with pytest.raises(HTTPException) as error, store.transaction() as conn:
        service.finish(conn, "local", quiz["id"], quiz["revision"])
    assert error.value.detail["code"] == "answer_checking"
    assert not LearnerStateService(store).list_evidence("local")


def test_exam_feedback_cannot_be_used_for_note_generation(env, monkeypatch):
    from backend.app.note_draft_service import NoteDraftService
    from backend.app.note_draft_models import CreateNoteDraft
    client, store, provider, quiz = prepare_v2(env, monkeypatch, feedbackPolicy="exam_deferred")
    command(client, f"/quizzes/{quiz['id']}/attempts", {"presentationId": quiz["current"]["id"], "expectedRevision": quiz["revision"], "selectedIds": ["b"]})
    attempt = WorkflowStore(store).read("local", quiz["id"], "quiz")["attempts"][0]
    with pytest.raises(HTTPException) as error:
        NoteDraftService(store, provider)._context("local", quiz["sessionId"], CreateNoteDraft(origin_kind="quiz_feedback", quiz_attempt_id=attempt))
    assert error.value.detail["code"] == "exam_feedback_deferred"


def test_exam_challenges_wait_for_finish(env, monkeypatch):
    from sqlalchemy import text
    from backend.app.assessment_adjudication import ChallengeService
    client, store, provider, quiz = prepare_v2(env, monkeypatch, feedbackPolicy="exam_deferred")
    records = WorkflowStore(store)
    with store.transaction() as conn:
        result = QuizService(store, provider).challenge(conn, "local", quiz["current"]["id"], "The wording is ambiguous.")
    with store.engine.connect() as conn:
        assert not conn.execute(text("SELECT id FROM learning_jobs WHERE target_id=:id AND kind='adjudicate'"), {"id": result["challengeId"]}).first()
    with pytest.raises(HTTPException) as error:
        ChallengeService(store, provider).prepare("local", result["challengeId"])
    assert error.value.detail["code"] == "exam_feedback_deferred"
    fresh = records.read("local", quiz["id"], "quiz")
    with store.transaction() as conn:
        QuizService(store, provider).finish(conn, "local", quiz["id"], fresh["revision"])
    with store.engine.connect() as conn:
        assert conn.execute(text("SELECT id FROM learning_jobs WHERE target_id=:id AND kind='adjudicate'"), {"id": result["challengeId"]}).first()


def test_grading_report_counts_errors_and_uncertainty():
    from backend.scripts.assessment_grading_benchmark import summarize, validate_cases
    with pytest.raises(ValueError):
        validate_cases([{"id": "unreviewed", "humanReviewed": False}])
    rows = [{"configuration": "candidate", "expectedScore": 0, "expectedStatus": "evaluated", "result": {"score": 1, "status": "evaluated"}, "latencySeconds": 2},
        {"configuration": "candidate", "expectedScore": None, "expectedStatus": "uncertain", "result": {"score": None, "status": "uncertain"}, "latencySeconds": 4}]
    report = summarize(rows)["candidate"]
    assert report["meanAbsoluteScoreError"] == 1 and report["unsupportedFullCredit"] == 1
    assert report["uncertainCount"] == 1 and report["statusAgreement"] == 1


def test_operational_report_exports_counts_without_learner_content():
    from backend.scripts.quiz_quality_report import aggregate
    now = utc_now()
    records = [("quiz", {"id": "q", "status": "completed", "createdAt": now.isoformat()}),
        ("attempt", {"quizId": "q", "status": "uncertain", "response": "PRIVATE ANSWER", "outcome": "answer"}),
        ("item", {"_parentId": "q", "qualityStatus": "approved", "stem": "PRIVATE QUESTION"}),
        ("challenge", {"_parentId": "q", "outcome": "invalidate", "reason": "PRIVATE CHALLENGE"})]
    report = aggregate(records, {"q": 1_000_000_000}, now)
    assert report["gradingUncertainty"] == 1 and report["quizCostUsd"] == 1
    assert report["challengeOutcomes"] == {"invalidate": 1}
    assert "PRIVATE" not in json.dumps(report)


def test_final_grading_failure_releases_timer_reservation(env, monkeypatch):
    from backend.app.learning_routes import run_job
    from backend.app.assessment_lifecycle import AssessmentLifecycle
    client, store, provider, quiz = prepare_v2(env, monkeypatch, mode="timed_short_quiz", modeConfig={"duration_seconds": 300})
    def unavailable(*args, **kwargs):
        raise ModelProviderError("Provider temporarily unavailable")
    monkeypatch.setattr(AssessmentLifecycle, "evaluate_response", unavailable)
    job = WorkflowStore(store).enqueue("local", quiz["id"], "answer", {"presentation_id": quiz["current"]["id"], "expected_revision": quiz["revision"], "selected_ids": ["b"]}, "final-failure", max_attempts=1)
    run_job(store, provider, job["id"])
    assert WorkflowStore(store).job("local", job["id"])["status"] == "failed"
    public = client.get(f"/v1/quizzes/{quiz['id']}").json()
    assert not public["checkingAnswer"] and public["deadlineAt"]
    assert public["remainingSeconds"] > 290 and not public["attempts"]


def test_answering_timeout_completes_without_fabricating_answers(env, monkeypatch):
    client, store, _, quiz = prepare_v2(env, monkeypatch, mode="timed_short_quiz", modeConfig={"duration_seconds": 300})
    records = WorkflowStore(store)
    saved = records.read("local", quiz["id"], "quiz")
    saved["answeringStartedAt"] = (utc_now() - timedelta(seconds=400)).isoformat()
    with store.transaction() as conn:
        records.put(conn, "local", "quiz", saved, expected=saved["revision"])
    public = client.get(f"/v1/quizzes/{quiz['id']}").json()
    assert public["status"] == "completed" and not public["attempts"]
    assert public["summary"]["score"] is None and public["summary"]["attempted"] == 0


def test_usefulness_feedback_is_owner_scoped_and_does_not_change_evidence(env, monkeypatch):
    client, store, provider, quiz = prepare_v2(env, monkeypatch)
    service = QuizService(store, provider)
    with pytest.raises(HTTPException) as error, store.transaction() as conn:
        service.record_usefulness(conn, "local", quiz["id"], True)
    assert error.value.detail["code"] == "quiz_not_completed"
    with store.transaction() as conn:
        service.finish(conn, "local", quiz["id"], quiz["revision"])
    with store.transaction() as conn:
        service.record_usefulness(conn, "local", quiz["id"], True)
    with store.transaction() as conn:
        service.record_usefulness(conn, "local", quiz["id"], False)
    assert client.get(f"/v1/quizzes/{quiz['id']}").json()["usefulness"] is False
    with pytest.raises(HTTPException), store.transaction() as conn:
        service.record_usefulness(conn, "another-owner", quiz["id"], True)
    assert not LearnerStateService(store).list_evidence("local")


def test_cancellation_fences_late_grade_and_resumes_answering(env, monkeypatch):
    from backend.app.learning_routes import run_job
    from backend.app.assessment_lifecycle import AssessmentLifecycle
    client, store, provider, quiz = prepare_v2(env, monkeypatch, mode="timed_short_quiz", modeConfig={"duration_seconds": 300})
    records = WorkflowStore(store)
    job = records.enqueue("local", quiz["id"], "answer", {"presentation_id": quiz["current"]["id"], "expected_revision": quiz["revision"], "selected_ids": ["b"]}, "cancel-grading")
    original = AssessmentLifecycle.evaluate_response
    def cancel_before_return(self, *args, **kwargs):
        assert client.post(f"/v1/learning-jobs/{job['id']}/cancel").status_code == 200
        return original(self, *args, **kwargs)
    monkeypatch.setattr(AssessmentLifecycle, "evaluate_response", cancel_before_return)
    run_job(store, provider, job["id"])
    public = client.get(f"/v1/quizzes/{quiz['id']}").json()
    assert records.job("local", job["id"])["status"] == "cancelled"
    assert public["deadlineAt"] and not public["checkingAnswer"] and not public["attempts"]
    assert not LearnerStateService(store).list_evidence("local")


def test_exam_finalization_revalidates_source_before_releasing_evidence(env, monkeypatch):
    from sqlalchemy import text
    client, store, _, quiz = prepare_v2(env, monkeypatch, feedbackPolicy="exam_deferred")
    command(client, f"/quizzes/{quiz['id']}/attempts", {"presentationId": quiz["current"]["id"], "expectedRevision": quiz["revision"], "selectedIds": ["b"]})
    public = client.get(f"/v1/quizzes/{quiz['id']}").json()
    with store.transaction() as conn:
        conn.execute(text("UPDATE materials SET deleted=true WHERE owner_id='local'"))
    result = command(client, f"/quizzes/{quiz['id']}/finish", {"expectedRevision": public["revision"]})
    assert result["status"] == "failed"
    assert not LearnerStateService(store).list_evidence("local")


def test_written_grading_reanchors_only_exact_unique_learner_quotes():
    from backend.tests.test_assessment_quality import item as candidate
    from backend.app.assessment_generation import evaluate
    item = candidate(kind="short", options=[], correct_ids=[])
    class OffsetProvider:
        provider_name = "test-only"
        def complete_json(self, prompt):
            return {"certain": True, "criteria": [{"id": "population", "score": 1, "outcome": "correct",
                "spans": [{"start": 0, "end": 1, "quote": "outcomes"}], "reason": "Identifies the population."}], "feedback": "The population is identified."}
    result = evaluate(OffsetProvider(), item, {"outcome": "answer", "response": "These outcomes are compatible.", "selected_ids": []})
    assert result["score"] == 1 and result["criteria"][0]["spans"][0]["start"] == 6
    for response in ("No supporting quotation here.", "outcomes outcomes"):
        rejected = evaluate(OffsetProvider(), item, {"outcome": "answer", "response": response, "selected_ids": []})
        assert rejected["status"] == "uncertain" and rejected["uncertaintyReason"] == "invalid_response_span"
