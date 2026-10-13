"""Operator-only aggregate quiz report; exports no prompts, answers or identities."""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from sqlalchemy import text


def aggregate(records, costs, now=None):
    now = now or datetime.now(timezone.utc)
    quizzes = [value for kind, value in records if kind == "quiz"]
    quiz_ids = {value["id"] for value in quizzes}
    attempts = [value for kind, value in records if kind == "attempt" and value.get("quizId") in quiz_ids]
    items = [value for kind, value in records if kind == "item" and value.get("_parentId") in quiz_ids]
    challenges = [value for kind, value in records if kind == "challenge" and value.get("_parentId") in quiz_ids]
    completed = [value for value in quizzes if value["status"] == "completed"]
    stale = 0
    for quiz in quizzes:
        timestamp = quiz.get("updatedAt") or quiz.get("createdAt")
        if timestamp and quiz["status"] != "completed" and now - datetime.fromisoformat(timestamp) > timedelta(days=7):
            stale += 1
    diagnostic = [value for value in attempts if value.get("parentAttemptId")]
    usefulness = [value for kind, value in records if kind == "quiz_feedback" and value.get("_parentId") in quiz_ids]
    rejected_ids = {value["rejectedItemId"] for kind, value in records if kind == "assessment_author" and value.get("_parentId") in quiz_ids and value.get("rejectedItemId")}
    reasons = Counter(reason for kind, value in records if kind == "assessment_checker" and value.get("rejectedItemId") in rejected_ids for reason in value.get("deterministicFailures", []))
    total_cost = sum(costs.get(identifier, 0) for identifier in quiz_ids)
    return {"quizCount": len(quizzes), "completedCount": len(completed),
        "completionRate": len(completed) / len(quizzes) if quizzes else None,
        "inactiveSevenDaysCount": stale, "inactiveDefinition": "unfinished and no artifact update for seven days; not proof of abandonment",
        "attemptCount": len(attempts), "skips": sum(value.get("outcome") == "skip" for value in attempts),
        "gradingUncertainty": sum(value.get("status") == "uncertain" for value in attempts),
        "diagnosticCount": len(diagnostic), "diagnosticResolved": sum(value.get("status") == "evaluated" for value in diagnostic),
        "challengeCount": len(challenges), "challengeOutcomes": dict(Counter(value.get("outcome", "pending") for value in challenges)),
        "approvedItemCount": sum(value.get("qualityStatus") == "approved" for value in items),
        "rejectedCandidateCount": len(rejected_ids),
        "rejectionReasons": dict(reasons), "quizCostUsd": total_cost / 1_000_000_000,
        "meanCostPerPresentedQuestionUsd": total_cost / len(items) / 1_000_000_000 if items else None,
        "meanCompletedQuizCostUsd": sum(costs.get(value["id"], 0) for value in completed) / len(completed) / 1_000_000_000 if completed else None,
        "costIncludes": "all quiz-root ledger settlements, including rejected and discarded prefetched candidates",
        "waitingTimeSource": "assessment_model_call and learning command latency logs",
        "usefulnessResponses": len(usefulness), "usefulResponses": sum(value["useful"] for value in usefulness),
        "humanGradingAgreementSource": "assessment_grading_benchmark"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from backend.app.storage import Store
    from backend.app.database import database_url
    store = Store(database_url())
    try:
        with store.engine.connect() as conn:
            records = [(row.kind, {**json.loads(row.payload), "_parentId": row.parent_id}) for row in conn.execute(text("SELECT kind,parent_id,payload FROM practice_records WHERE owner_id=:owner AND kind IN ('quiz','attempt','item','assessment_author','assessment_checker','challenge','quiz_feedback')"), {"owner": args.owner})]
            costs = dict(conn.execute(text("SELECT root_id,SUM(cost_nano) FROM usage_events WHERE owner_id=:owner GROUP BY root_id"), {"owner": args.owner}).all())
        report = aggregate(records, costs)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
    finally:
        store.close()


if __name__ == "__main__":
    main()
