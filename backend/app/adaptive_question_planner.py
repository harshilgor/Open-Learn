"""Bounded, auditable objective selection before any question authoring call."""
from collections import Counter
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
    return QuestionPlan(concept_id=target, objective=objective, reason_codes=reasons,
        capability="transfer" if objective == "transfer_check" else "recall" if objective == "due_retrieval" else "explain",
        requested_complexity=quiz.get("difficulty", "standard"), remaining_items=remaining,
        diagnostic_distinction=diagnostic,
        excluded_families=list(dict.fromkeys(p.get("family") for p in previous[-20:] if p.get("family"))))
