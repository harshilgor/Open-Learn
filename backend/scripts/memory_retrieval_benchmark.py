"""Learner-memory retrieval latency (spec §8.2 Phase D acceptance, §11.4).

Seeds one synthetic owner with 2,000 facts and 300 episodes in a disposable
database, then times LearnerMemoryService.context over varied queries. Pass
--database-url-env with an isolated local PostgreSQL database named
openlearn_qualification_* to measure PostgreSQL; the default is SQLite.
--core-profile turns on consolidation (Phase E), times one consolidation run
for the owner, and then measures retrieval with the stored core profile.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import tempfile
import time
from pathlib import Path

from sqlalchemy import text

KINDS = ["goal", "deadline", "preference", "constraint", "background", "interest", "strategy_feedback", "note_to_self"]
TOPICS = ["calculus", "chain rule", "limits", "statistics", "probability", "chemistry", "essay", "linear algebra", "vectors",
          "python", "history", "biology", "physics", "economics", "spanish", "integration", "derivatives", "matrices"]
QUERIES = ["how do I prepare for my calculus midterm", "what did we cover last week", "when is my next deadline",
           "explain the chain rule again", "help me with my statistics project", "what's due this week",
           "can we revisit probability", "summarize our chemistry sessions", "give me a basketball analogy for vectors",
           "what did we do in September", "quiz me on integration", "ok thanks"]


def percentile(values, fraction):
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 3)


def seed(store, owner, facts, episodes, now):
    from backend.app.learner_memory import store as memory_store
    rng = random.Random(7)
    with store.transaction() as conn:
        for index in range(facts):
            kind = KINDS[index % len(KINDS)]
            topic = rng.choice(TOPICS)
            day = 1 + index % 28
            event_date = f"2026-{11 + index % 2:02d}-{day:02d}" if kind == "deadline" else None
            importance = 0.5
            learned = now - rng.uniform(0, 400) * 86400
            conn.execute(text(f"""INSERT INTO memory_facts({memory_store.FACT_COLUMNS}) VALUES(:owner,:id,:kind,:statement,:subject,NULL,'[]',:event_date,
                'user_stated','active',:false,0.9,:importance,:learned,:learned,NULL,NULL,'[]',:used,0,NULL,60,:false,'bench',1)"""),
                {"owner": owner, "id": f"fact_{index}", "kind": kind, "subject": f"{kind}:{topic.replace(' ', '-')}-{index}",
                 "statement": f"Synthetic {kind.replace('_', ' ')} about {topic} number {index}.", "event_date": event_date,
                 "false": False, "importance": importance, "learned": learned, "used": learned if index % 3 else None})
        for index in range(episodes):
            end = now - rng.uniform(0, 360) * 86400
            conn.execute(text("""INSERT INTO memory_episodes(owner_id,id,session_id,course_id,period_start,period_end,turn_range,summary,topics,method,basis,status,created_at,revision)
                VALUES(:owner,:id,'bench',NULL,:start,:end,'{}',:summary,'[]','extractive-v1','[]','active',:end,1)"""),
                {"owner": owner, "id": f"episode_{index}", "start": end - 3600, "end": end,
                 "summary": f"Covered {rng.choice(TOPICS)} and {rng.choice(TOPICS)}; practiced problems."})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=int, default=2000)
    parser.add_argument("--episodes", type=int, default=300)
    parser.add_argument("--runs", type=int, default=240)
    parser.add_argument("--out", required=True)
    parser.add_argument("--core-profile", action="store_true", help="Consolidate first and read the stored core profile (Phase E)")
    parser.add_argument("--database-url-env", help="Isolated local PostgreSQL URL variable (database openlearn_qualification_*); never DATABASE_URL")
    args = parser.parse_args()
    url = None
    if args.database_url_env:
        from sqlalchemy.engine import make_url
        if args.database_url_env == "DATABASE_URL":
            parser.error("DATABASE_URL cannot be used for qualification.")
        url = os.getenv(args.database_url_env)
        parsed = make_url(url) if url else None
        if not parsed or parsed.get_backend_name() != "postgresql" or parsed.host not in {"localhost", "127.0.0.1"} or not (parsed.database or "").startswith("openlearn_qualification_"):
            parser.error("Require a local PostgreSQL database named openlearn_qualification_*.")
    os.environ.setdefault("AI_TUTOR_ENV", "development")
    os.environ["OPENLEARN_MEMORY_CONSOLIDATION"] = "on" if args.core_profile else "off"
    from backend.app.learner_memory.service import LearnerMemoryService
    from backend.app.storage import Store
    with tempfile.TemporaryDirectory(prefix="openlearn-memory-bench-") as directory:
        store = Store(url or f"sqlite+pysqlite:///{(Path(directory) / 'bench.db').resolve()}")
        owner = "memory-bench-" + str(int(time.time()))
        now = time.time()
        try:
            seed(store, owner, args.facts, args.episodes, now)
            consolidation_ms = None
            if args.core_profile:
                from backend.app.learner_memory import consolidation
                started = time.perf_counter()
                consolidation_report = consolidation.consolidate(store, owner, now=now)
                consolidation_ms = round((time.perf_counter() - started) * 1000, 1)
            service = LearnerMemoryService(store)
            for query in QUERIES:  # warm caches and imports
                service.context(owner, None, query, now=now)
            timings, tokens = [], []
            for index in range(args.runs):
                started = time.perf_counter()
                result = service.context(owner, None, QUERIES[index % len(QUERIES)], now=now, timezone_name="UTC")
                timings.append((time.perf_counter() - started) * 1000)
                tokens.append(len(result.text) // 3 if result else 0)
            # Cold: the first turn for an owner, or the first after their facts change.
            from backend.app.learner_memory import service as memory_service
            cold = []
            for index in range(max(20, args.runs // 6)):
                memory_service._FACTS.clear(); memory_service._EPISODES.clear(); memory_service._PROFILES.clear()
                started = time.perf_counter()
                service.context(owner, None, QUERIES[index % len(QUERIES)], now=now, timezone_name="UTC")
                cold.append((time.perf_counter() - started) * 1000)
            with store.transaction() as conn:
                for table in ("memory_facts", "memory_episodes", "context_records", "memory_fact_versions"):
                    conn.execute(text(f"DELETE FROM {table} WHERE owner_id=:owner"), {"owner": owner})
        finally:
            store.close()
    report = {"scope": "isolated local PostgreSQL" if url else "disposable SQLite", "facts": args.facts, "episodes": args.episodes,
              "runs": args.runs, "p50Ms": percentile(timings, .5), "p95Ms": percentile(timings, .95), "p99Ms": percentile(timings, .99),
              "maxMs": round(max(timings), 3), "coldP50Ms": percentile(cold, .5), "coldP95Ms": percentile(cold, .95),
              "meanMemoryTokens": round(sum(tokens) / len(tokens), 1), "targetP95Ms": 25,
              "coreProfile": args.core_profile, "consolidationMs": consolidation_ms,
              "consolidation": consolidation_report if args.core_profile else None,
              "note": "p50/p95/p99 are warm (cached static rows, watermark revalidated); cold reloads the owner's facts"}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
