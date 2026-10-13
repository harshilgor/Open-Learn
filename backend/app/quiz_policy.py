"""Versioned session policies, public serialization, and answering-time accounting."""
from datetime import datetime, timedelta
import math

from .assessment_profiles import enabled, profile_snapshot
from .models import utc_now
from .material_service import problem


def session_plan(request, concepts, canonical, graph):
    if not enabled("quiz_v2", False):
        return {}
    preference = request.challenge_preference or {"foundational": "build_confidence", "stretch": "challenge_me"}.get(request.difficulty, "balanced")
    return {"schemaVersion": 2, "policyVersion": "quiz-quality-v2", "conceptIds": concepts,
        "canonicalConceptIds": canonical, "graphVersion": graph.version,
        "challengePreference": preference, "feedbackPolicy": request.feedback_policy,
        "coverageTargets": [{"conceptId": c, "minimum": 1} for c in concepts],
        "count": request.count, "diagnosticBudget": min(2, max(0, request.count - len(concepts))),
        "timingPolicy": "answering-v2" if enabled("quiz_timing_v2", True) else "deadline-v1",
        "diagnosticsEnabled": enabled("quiz_diagnostics", True),
        "uiVersion": 2 if enabled("quiz_ui_v2", False) else 1,
        "prefetchEnabled": enabled("quiz_prefetch", False),
        "sourceRevisionRefs": [], "modelProfiles": profile_snapshot()}


def remaining_seconds(quiz, now=None):
    now = now or utc_now()
    remaining = float(quiz.get("remainingSeconds") or 0)
    if quiz.get("answeringStartedAt"):
        remaining -= max(0, (now - datetime.fromisoformat(quiz["answeringStartedAt"])).total_seconds())
    return max(0, remaining)


def is_answering_timer(quiz):
    return quiz.get("mode") == "timed_short_quiz" and (quiz.get("sessionPlan") or {}).get("timingPolicy") == "answering-v2"


def start_answering(quiz):
    if is_answering_timer(quiz):
        if float(quiz.get("remainingSeconds") or 0) <= 0:
            problem("quiz_time_elapsed", "This quiz has no answering time remaining.", 409)
        quiz["answeringStartedAt"] = utc_now().isoformat()
        quiz["deadlineAt"] = (utc_now() + timedelta(seconds=float(quiz["remainingSeconds"]))).isoformat()


def stop_answering(quiz, at=None):
    if is_answering_timer(quiz):
        quiz["remainingSeconds"] = remaining_seconds(quiz, at)
        quiz["answeringStartedAt"] = None
        quiz["deadlineAt"] = None


def deferred(quiz):
    return (quiz.get("sessionPlan") or {}).get("feedbackPolicy") == "exam_deferred" and quiz.get("status") != "completed"


PRESENTATION_FIELDS = {"id", "quizId", "reviewSessionId", "concept_id", "kind", "stem", "options", "hints", "attemptId", "difficulty", "hintCount", "sources", "retryOf", "lessonNoteId", "contested", "questionPlan", "rationaleRequested", "feedbackDeferred", "uiVersion"}
ATTEMPT_FIELDS = {"id", "presentationId", "quizId", "reviewSessionId", "conceptId", "response", "selectedIds", "outcome", "assisted", "retryOf", "createdAt", "score", "status", "feedback", "solution", "correctIds", "criteria", "conceptState", "feedbackDetails", "uncertaintyReason", "parentAttemptId", "evidenceId", "rationale", "question", "uiVersion"}


def public_presentation(value, hide=False):
    if value is None:
        return None
    result = {key: value[key] for key in PRESENTATION_FIELDS if key in value}
    plan = value.get("questionPlan") or {}
    if plan:
        result["questionPlan"] = {key: plan[key] for key in ("objective", "capability", "reason_codes", "public_objective", "parent_attempt_id") if key in plan}
    if hide:
        result["hints"] = []
        result["feedbackDeferred"] = True
        result["hintCount"] = 0
    return result


def public_attempt(value, hide=False):
    result = {key: value[key] for key in ATTEMPT_FIELDS if key in value}
    if hide:
        for key in ("solution", "correctIds", "criteria", "feedbackDetails", "conceptState", "uncertaintyReason", "evidenceId"):
            result.pop(key, None)
        result.update(score=None, status="submitted", feedback="Answer saved. Feedback is available when the quiz ends.")
    return result
