"""Compare two content-free Open Learn performance snapshots.

The output is an evidence summary, not an automatic production approval. The
input snapshots must represent the same workload, environment, regions, and
measurement definitions.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def series(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize dashboard-series or offline-fixture timing shapes."""
    result: dict[str, dict[str, Any]] = {}
    for row in report.get("series", []):
        if not isinstance(row, dict):
            continue
        key = f"{row.get('resource', 'unknown')}::{row.get('stage', 'unknown')}"
        result[key] = {
            "samples": row.get("sampleCount", 0),
            "failures": row.get("sampleFailures", 0),
            "p50Ms": _number(row.get("p50Ms")),
            "p95Ms": _number(row.get("p95Ms")),
            "p99Ms": _number(row.get("p99Ms")),
        }
    for key, row in report.get("timings", {}).items():
        if not isinstance(row, dict):
            continue
        result[f"fixture::{key}"] = {
            "samples": row.get("count", report.get("attempts", 0)),
            "failures": report.get("failures", 0),
            "p50Ms": _number(row.get("p50Ms")),
            "p95Ms": _number(row.get("p95Ms")),
            "p99Ms": _number(row.get("p99Ms")),
        }
    return result


def compare(before: dict[str, Any], after: dict[str, Any], *, minimum_samples: int,
            max_p95_regression_percent: float) -> dict[str, Any]:
    before_series, after_series = series(before), series(after)
    common = sorted(set(before_series) & set(after_series))
    missing = {"beforeOnly": sorted(set(before_series) - set(after_series)),
               "afterOnly": sorted(set(after_series) - set(before_series))}
    results = []
    insufficient = []
    regressions = []
    for key in common:
        old, new = before_series[key], after_series[key]
        row = {"metric": key, "before": old, "after": new}
        if int(old["samples"] or 0) < minimum_samples or int(new["samples"] or 0) < minimum_samples:
            row["status"] = "insufficient_samples"
            insufficient.append(key)
        elif old["p95Ms"] is None or new["p95Ms"] is None:
            row["status"] = "missing_p95"
            insufficient.append(key)
        else:
            delta = new["p95Ms"] - old["p95Ms"]
            percent = (delta / old["p95Ms"] * 100) if old["p95Ms"] else (0.0 if delta == 0 else None)
            row["p95DeltaMs"] = round(delta, 3)
            row["p95DeltaPercent"] = round(percent, 2) if percent is not None else None
            row["status"] = "regression" if (
                (percent is not None and percent > max_p95_regression_percent)
                or (old["p95Ms"] == 0 and delta > 0)
            ) else "compared"
            if row["status"] == "regression":
                regressions.append(key)
        if int(new["failures"] or 0) > int(old["failures"] or 0):
            row["failureCountIncreased"] = True
            regressions.append(key)
        results.append(row)

    same_scope = bool(before.get("scope")) and before.get("scope") == after.get("scope")
    if not common or not same_scope:
        status = "incomparable"
    elif insufficient or missing["beforeOnly"] or missing["afterOnly"]:
        status = "insufficient_evidence"
    elif regressions:
        status = "regression_detected"
    else:
        status = "no_regression_detected"
    return {
        "version": 1,
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "rolloutApproval": False,
        "scopeMatched": same_scope,
        "scope": after.get("scope"),
        "beforeObservedAt": before.get("observedAt"),
        "afterObservedAt": after.get("observedAt"),
        "beforeCommit": before.get("commit") or before.get("release", {}).get("commit"),
        "afterCommit": after.get("commit") or after.get("release", {}).get("commit"),
        "minimumSamplesPerMetric": minimum_samples,
        "maximumAllowedP95RegressionPercent": max_p95_regression_percent,
        "metrics": results,
        "insufficientMetrics": insufficient,
        "regressions": sorted(set(regressions)),
        "unmatchedMetrics": missing,
        "limitations": [
            "A process snapshot is not a fleet-wide SLO or availability measurement.",
            "Overlapping spans must not be summed. Compare the same named stages only.",
            "Quality, note integrity, queue recovery, cost, and rollback evidence require separate review.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--minimum-samples", type=int, default=100)
    parser.add_argument("--max-p95-regression-percent", type=float, default=20.0)
    args = parser.parse_args()
    if args.minimum_samples < 1 or args.max_p95_regression_percent < 0:
        parser.error("Sample count must be positive and regression threshold nonnegative")
    try:
        before = json.loads(args.before.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"Could not read a JSON snapshot: {error}")
    report = compare(before, after, minimum_samples=args.minimum_samples,
                     max_p95_regression_percent=args.max_p95_regression_percent)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "limitations"}, indent=2))
    raise SystemExit(1 if report["status"] in {"incomparable", "insufficient_evidence", "regression_detected"} else 0)


if __name__ == "__main__":
    main()
