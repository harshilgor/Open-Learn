"""Run bounded local fixture profiles without contacting hosted services.

This is a capacity-regression harness, not a production/staging load generator.
It always delegates to performance_benchmark, which creates a disposable SQLite
database and uses a deterministic provider.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKLOAD = ROOT / "docs" / "performance" / "workload.json"


def main() -> None:
    workload = json.loads(WORKLOAD.read_text(encoding="utf-8"))
    profiles = workload["profiles"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", default="baseline,growth,burst",
                        help="Comma-separated workload profile names (default: all three)")
    parser.add_argument("--samples-per-scenario", type=int, default=100,
                        help="Fixture attempts per chat scenario and profile; P20 gate is 100")
    parser.add_argument("--profile-timeout-seconds", type=int, default=600,
                        help="Stop a stalled local profile instead of leaving a fixture process running")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    names = [part.strip() for part in args.profiles.split(",") if part.strip()]
    unknown = sorted(set(names) - set(profiles))
    if not names or unknown:
        parser.error("Unknown or empty profiles: " + ", ".join(unknown or names))
    if len(set(names)) != len(names):
        parser.error("Profiles must not be repeated")
    if not 1 <= args.samples_per_scenario <= 1000:
        parser.error("--samples-per-scenario must be between 1 and 1000")
    if not 10 <= args.profile_timeout_seconds <= 3600:
        parser.error("--profile-timeout-seconds must be between 10 and 3600")

    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    profile_results = []
    for name in names:
        concurrency = int(profiles[name]["concurrentUsers"])
        if not 1 <= concurrency <= 50:
            parser.error(f"Workload profile {name!r} is outside the fixture runner's 1–50 concurrency range")
        report_path = output.with_name(f"{output.stem}-{name}.json")
        command = [sys.executable, "-m", "backend.scripts.performance_benchmark",
                   "--runs", str(args.samples_per_scenario * 2),
                   "--concurrency", str(concurrency), "--out", str(report_path),
                   "--temp-dir", str(output.parent)]
        timed_out = False
        try:
            completed = subprocess.run(command, cwd=ROOT, check=False,
                                       timeout=args.profile_timeout_seconds)
            return_code = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            return_code = None
        detail = None
        if report_path.exists():
            try:
                detail = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                detail = None
        timings = (detail or {}).get("timings", {})
        profile_results.append({
            "profile": name,
            "targetConcurrentUsers": concurrency,
            "attemptsPerScenarioRequested": args.samples_per_scenario,
            "attempts": (detail or {}).get("attempts", 0),
            "failures": (detail or {}).get("failures"),
            "phaseAtTimeoutOrCompletion": (detail or {}).get("phase"),
            "requestedAttempts": (detail or {}).get("requestedAttempts"),
            "timings": timings,
            "processExitCode": return_code,
            "timedOut": timed_out,
            "artifact": report_path.name,
        })

    sample_gate_met = args.samples_per_scenario >= int(workload["minimumSamplesForPercentileGate"])
    report = {
        "version": 1,
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "scope": "local disposable SQLite with deterministic fixture provider; no hosted requests or provider charges",
        "productionQualification": False,
        "productionQualificationReason": "This fixture does not exercise PostgreSQL, browsers/tabs, real providers, separate workers, deployment overlap, or production resource limits.",
        "sampleGateMetForFixture": sample_gate_met,
        "profiles": profile_results,
        "allFixtureProfilesPassed": all(row["processExitCode"] == 0 and row["failures"] == 0 for row in profile_results),
        "limitations": [
            "Each run covers greeting or short tutoring plus a note update/revision-conflict check.",
            "Concurrency is simultaneous fixture work, not a calibrated arrival-rate model.",
            "Do not use this output as a hosted capacity, SLO, model-quality, or availability claim.",
        ],
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "limitations"}, indent=2))
    raise SystemExit(0 if report["allFixtureProfilesPassed"] else 1)


if __name__ == "__main__":
    main()
