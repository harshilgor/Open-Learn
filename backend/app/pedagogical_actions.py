"""Explicit teaching interventions; evidence and learner choice govern eligibility."""
from pydantic import BaseModel


class TeachingAction(BaseModel):
    policy_revision: str = "teaching-actions-v1"
    action: str
    reason_codes: list[str]
    completion: str
    disclosure_limits: list[str]
    optional_follow_up: str | None = None


def select_teaching_action(request, workflow, states=(), hypothesis=None, history=(), declined_check=False):
    explicit = request.strip().lower()
    declined_check = declined_check or any(phrase in explicit for phrase in ("no quiz", "don't quiz", "do not quiz", "no check", "don't test"))
    recent = list(history)[-3:]
    if explicit:
        action = "minimal_hint" if "hint" in explicit else "self_explanation" if "self explanation" in explicit else "transfer_check" if "transfer check" in explicit else "independent_retrieval_check" if "recall check" in explicit else "worked_example" if "example" in explicit else "guided_reasoning" if "guide me" in explicit else "direct_explanation"
        reason = "explicit_learner_request"
    elif len(recent) >= 3 and all(h.get("productive") is False for h in recent):
        action, reason = "worked_example", "unproductive_loop_bound"
    elif hypothesis and hypothesis.get("action") in {"contrastive_explanation", "prerequisite_repair"}:
        action, reason = hypothesis["action"], "supported_diagnostic_evidence"
    elif not declined_check and any(s.get("assistedEventIds") for s in states):
        action, reason = "independent_retrieval_check", "assisted_success_follow_up"
    elif not declined_check and states and all(s.get("state") == "demonstrated" for s in states):
        action, reason = "transfer_check", "supported_procedure_transfer_unknown"
    else:
        action, reason = "direct_explanation", "requested_level_without_diagnostic_evidence"
    check = action in {"independent_retrieval_check", "transfer_check", "self_explanation"}
    return TeachingAction(action=action, reason_codes=[reason, "learner_may_continue_directly"],
        completion="Evaluate a separately submitted response; delivery is exposure only." if check else "Deliver a grounded explanation; offer a distinct evaluable task with consent.",
        disclosure_limits=["Do not disclose the final answer or worked solution before submission."] if check or action == "minimal_hint" else [],
        optional_follow_up=None if declined_check else "distinct_independent_check")
