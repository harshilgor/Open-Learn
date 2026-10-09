"""Bounded, auditable objective selection before any question authoring call."""
from collections import Counter
import hashlib
from pydantic import BaseModel, Field


class QuestionPlan(BaseModel):
    policy_revision: str = "adaptive-objectives-v1"
    concept_id: str
    capability: str = "explain"
    objective: str
    reason_codes: list[str]
    requested_complexity: str
    response_type: str = "any"
    estimated_duration_seconds: int = 120
    source_revisions: list[dict] = Field(default_factory=list)
    excluded_families: list[str] = Field(default_factory=list)
    remaining_items: int
    diagnostic_distinction: dict | None = None
    acceptance_criteria: list[str] = Field(default_factory=lambda: [
        "within_agreed_scope", "source_grounded", "independently_checked",
        "complete_weighted_rubric", "fresh_reasoning_family"])
    assistance_rules: str = "Hints are optional and mark subsequent performance as assisted."
    schema_version: int = 1
    spec_id: str | None = None
    parent_attempt_id: str | None = None
    reasoning_task: str = "explain"
    public_objective: str = "Explain how the idea applies."
    success_criteria: list[str] = Field(default_factory=list)
    challenge_dimensions: dict = Field(default_factory=dict)
    rationale_requested: bool = False


def choose_question_plan(quiz, attempts, states=(), previous=(), diagnostic=None):
    scope = list(dict.fromkeys(quiz["conceptIds"]))
    if not scope:
        raise ValueError("An explicit quiz scope is required")
    first = [a for a in attempts if not a.get("retryOf")]
    remaining = max(0, quiz["count"] - len(first))
    coverage = Counter(a.get("conceptId") for a in first)
    # Preserve remaining capacity for untouched scope; never let repeated errors
    # consume an entire fixed-length quiz.
    missing = [c for c in scope if not coverage[c]]
    target = min(scope, key=lambda c: (coverage[c], scope.index(c)))
    reasons = ["agreed_scope", "coverage_quota"]
    objective = "missing_capability_evidence"
    consecutive = 0
    for attempt in reversed(first):
        if (attempt.get("questionPlan") or {}).get("objective") != "distinguishing_check":
            break
        consecutive += 1
    diagnostic_target = diagnostic.get("conceptId", scope[0] if len(scope) == 1 else None) if diagnostic else None
    dedicated = bool(diagnostic and diagnostic.get("hypothesisId") and quiz["count"] == 1)
    if diagnostic and diagnostic_target in scope and consecutive < 2 and (dedicated or remaining > len(missing)):
        target, objective = diagnostic_target, "distinguishing_check"
        reasons.append("unresolved_distinction")
    else:
        diagnostic = None
        recent = next((a for a in reversed(first) if a.get("conceptId") == target and not a.get("contested")), None)
        relevant = [s for s in states if s.get("conceptId") == target]
        if recent and recent.get("score") == 1 and recent.get("assisted"):
            objective = "independent_verification"
            reasons.append("assisted_success_needs_fresh_check")
        elif any(s.get("retention") in {"review_due", "stale"} for s in relevant):
            objective = "due_retrieval"
            reasons.append("retention_due")
        elif relevant and all(s.get("state") == "demonstrated" for s in relevant):
            objective = "transfer_check"
            reasons.append("adequate_recent_evidence")
    session = quiz.get("sessionPlan") or {}
    parent = None
    if session.get("schemaVersion") == 2:
        used = sum((a.get("questionPlan") or {}).get("parent_attempt_id") is not None for a in first)
        recent = next((a for a in reversed(first) if not a.get("retryOf") and a.get("status") != "contested"), None)
        diagnosed = {((a.get("questionPlan") or {}).get("parent_attempt_id")) for a in first}
        if (recent and recent.get("status") == "uncertain" and recent.get("response", "").strip()
                and recent.get("id") not in diagnosed and not (recent.get("questionPlan") or {}).get("parent_attempt_id")
                and session.get("diagnosticsEnabled") and used < session.get("diagnosticBudget", 0)
                and session.get("feedbackPolicy") != "exam_deferred" and remaining > len(missing)
                and recent.get("conceptId") in scope):
            target, objective, parent = recent["conceptId"], "distinguishing_check", recent["id"]
            reasons.append("ambiguous_reasoning_needs_distinction")
        if session.get("feedbackPolicy") == "exam_deferred" and objective == "distinguishing_check":
            objective, diagnostic = "missing_capability_evidence", None
    plan = QuestionPlan(concept_id=target, objective=objective, reason_codes=reasons,
        capability="transfer" if objective == "transfer_check" else "recall" if objective == "due_retrieval" else "explain",
        requested_complexity=quiz.get("difficulty", "standard"), remaining_items=remaining,
        diagnostic_distinction=diagnostic,
        excluded_families=list(dict.fromkeys(p.get("family") for p in previous[-20:] if p.get("family"))))
    if session.get("schemaVersion") == 2:
        preference = session["challengePreference"]
        tasks = ["explain", "predict", "diagnose_error", "compare", "transfer"]
        plan.schema_version = 2
        plan.policy_revision = "adaptive-objectives-v2"
        plan.parent_attempt_id = parent
        plan.spec_id = hashlib.sha256(f"{quiz.get('id')}:{len(first)}:{target}:{objective}".encode()).hexdigest()[:24]
        plan.reasoning_task = "diagnose_error" if objective == "distinguishing_check" else "transfer" if objective == "transfer_check" else tasks[len(first) % len(tasks)]
        if preference == "build_confidence" and plan.reasoning_task == "transfer":
            plan.reasoning_task = "predict"
        plan.challenge_dimensions = {"conceptual_steps": 1 if preference == "build_confidence" else 3 if preference == "challenge_me" else 2,
            "context_novelty": "unfamiliar" if preference == "challenge_me" else "familiar",
            "scaffolding": "guided" if preference == "build_confidence" else "minimal",
            "difficulty_basis": "requested_design_not_calibrated"}
        plan.public_objective = {"explain": "Explain why the idea works.", "predict": "Predict what changes and explain why.",
            "diagnose_error": "Find the reasoning error and explain your correction.", "compare": "Compare two explanations using the principle.",
            "transfer": "Apply the idea in a new situation."}[plan.reasoning_task]
        plan.success_criteria = ["Identify the governing principle.", "Connect the principle to the scenario with valid reasoning.", "State necessary assumptions without introducing unrelated prerequisites."]
        plan.rationale_requested = session.get("feedbackPolicy") != "exam_deferred" and preference == "challenge_me"
    return plan
