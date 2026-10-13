"""Aggregate shadow-extraction report (spec §12 rollout step 3). Read-only.

Before switching OPENLEARN_MEMORY_EXTRACTION from ``shadow`` to ``on``, the
owner reviews shadow output in aggregate only. This report never selects a
statement, quote, message, or owner ID. It reports counts:

- memory_extract job outcomes (status, skip reasons, candidates proposed,
  facts accepted, validator rejection reasons)
- shadow facts by kind and by sensitivity
- distinct owners, as a number only, plus a small-sample warning

Usage:
  python -m backend.scripts.memory_shadow_report --days 14 --out outputs/memory/shadow-report.json
  (database from DATABASE_URL, or --database-url-env NAME)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, text

# Below this many distinct owners, per-kind counts could describe one person.
MIN_OWNERS = 20


def report(engine, *, since: float) -> dict:
    jobs, skipped, rejected = Counter(), Counter(), Counter()
    proposed = accepted = superseded = 0
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT status,result FROM learning_jobs
            WHERE kind='memory_extract' AND created_at>=:since"""), {"since": since}).all()
        for status, raw in rows:
            jobs[status] += 1
            try:
                result = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except ValueError:
                result = {}
            if result.get("status") == "skipped":
                skipped[str(result.get("reason"))] += 1
            proposed += int(result.get("candidates") or 0)
            accepted += sum(int(result.get(key) or 0) for key in ("created", "deduplicated", "existing"))
            superseded += int(result.get("superseded") or 0)
            for reason, count in (result.get("rejected") or {}).items():
                rejected[str(reason)] += int(count)
        by_kind = dict(conn.execute(text("""SELECT kind,COUNT(*) FROM memory_facts WHERE status='shadow' AND learned_at>=:since
            GROUP BY kind"""), {"since": since}).all())
        sensitive = conn.execute(text("""SELECT COUNT(*) FROM memory_facts WHERE status='shadow' AND sensitive=:true AND learned_at>=:since"""),
                                 {"since": since, "true": True}).scalar_one()
        owners = conn.execute(text("""SELECT COUNT(DISTINCT owner_id) FROM learning_jobs WHERE kind='memory_extract' AND created_at>=:since"""),
                              {"since": since}).scalar_one()
    completed = jobs.get("completed", 0)
    return {
        "windowDays": round((time.time() - since) / 86400, 1),
        "distinctOwners": owners,
        "smallSample": owners < MIN_OWNERS,
        "jobs": dict(jobs),
        "skipped": dict(skipped),
        "candidatesProposed": proposed,
        "factsAccepted": accepted,
        "acceptanceRate": round(accepted / proposed, 4) if proposed else None,
        "factsPerCompletedJob": round(accepted / completed, 4) if completed else None,
        "supersessions": superseded,
        "rejectionReasons": dict(rejected.most_common()),
        "shadowFactsByKind": {} if owners < MIN_OWNERS else by_kind,
        "shadowFactsSensitive": None if owners < MIN_OWNERS else sensitive,
        "note": "Counts only. Per-kind and sensitivity counts are withheld below "
                f"{MIN_OWNERS} distinct owners. Promotion to 'on' also requires the evaluation gates (§11.3).",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=float, default=14)
    parser.add_argument("--database-url-env", default="DATABASE_URL")
    parser.add_argument("--out")
    args = parser.parse_args()
    url = os.getenv(args.database_url_env)
    if not url:
        parser.error(f"{args.database_url_env} is not set.")
    engine = create_engine(url)
    try:
        result = report(engine, since=time.time() - args.days * 86400)
    finally:
        engine.dispose()
    text_ = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text_, encoding="utf-8")
    print(text_)


if __name__ == "__main__":
    main()
