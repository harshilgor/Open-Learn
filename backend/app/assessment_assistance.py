"""Observed assistance lineage shared by assessment workflows.

This records disclosed/observed help; it makes no claim to detect external help.
"""
import json
from difflib import SequenceMatcher
from sqlalchemy import text
from .assessment_generation import fingerprint


def assistance_for(conn, owner, presentation, item, disclosed=False):
    if disclosed or presentation.get("hints") or presentation.get("retryOf"):
        return {"condition": "assisted", "reason": "disclosed_or_recorded_help", "supportingIds": list(presentation.get("hints") or [])}
    rows = conn.execute(text("SELECT id,payload FROM practice_records WHERE owner_id=:owner AND kind='presentation' AND id<>:id"), {"owner": owner, "id": presentation["id"]}).mappings().all()
    related = []
    for row in rows:
        prior = json.loads(row["payload"])
        same_family = str(prior.get("family", "")).strip().casefold() == item.family.strip().casefold()
        repeated = SequenceMatcher(None, fingerprint(prior.get("stem", "")), fingerprint(item.stem)).ratio() > .82
        if (same_family or repeated) and (prior.get("attemptId") or prior.get("hints")):
            related.append(row["id"])
    for payload in conn.execute(text("SELECT payload FROM learning_event_ledger WHERE owner_id=:owner AND event_type IN ('ANSWER_EXPOSED','HINT_REQUESTED','RETRY_SUBMITTED')"), {"owner": owner}).scalars():
        prior = json.loads(payload)
        if prior.get("family_id") == item.family:
            related.append(prior["event"]["id"])
    return {"condition": "assisted" if related else "independent",
        "reason": "prior_family_feedback" if related else "no_recorded_help_or_prior_solution",
        "supportingIds": sorted(set(related))}
