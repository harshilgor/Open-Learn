"""Summarize exported assessment_timing JSON lines; no provider access or spend."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path


def summarize(events):
    groups = defaultdict(list)
    seen = set()
    for event in events:
        if event.get("event") != "assessment_timing":
            continue
        value = event.get("durationMs")
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            continue
        # Do not deduplicate by duration: two real calls can have identical timings.
        identity = event.get("eventId")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        groups[(event.get("stage"), event.get("command"), event.get("status"))].append(value)
    rows = []
    for (stage, command, status), values in groups.items():
        ordered = sorted(values)
        rows.append({"stage": stage, "command": command, "status": status,
            "samples": len(values), "p50Ms": ordered[math.ceil(len(values) * .5) - 1],
            "p95Ms": ordered[math.ceil(len(values) * .95) - 1], "maxMs": max(values)})
    return {"scope": "exported observations, not a load/SLO qualification", "stages": rows,
        "warning": "prepare includes model calls; command includes prepare/publication. Do not add nested spans. Queue age includes retry backoff on later attempts. UI delivery is not measured here."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    events = []
    for line in args.input.read_text(encoding="utf-8").splitlines():
        # Hosting exports may prefix stdout records with timestamps.
        try:
            event = json.loads(line[line.index("{"):])
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(event, dict):
            events.append(event)
    result = summarize(events)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
