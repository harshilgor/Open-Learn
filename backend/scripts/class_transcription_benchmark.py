"""Offline, reproducible recognition scoring; never sends lecture data anywhere.

Input JSON: {"samples": [{"id": "...", "group": "...", "reference": "...",
"hypothesis": "...", "terms": ["..."], "latencyMs": 1, "costUsd": 0.1}]}.
Optional metrics must be measured externally. Text normalization is versioned.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+(?:['’]\w+)*", unicodedata.normalize("NFKC", text).casefold())


def word_errors(reference: list[str], hypothesis: list[str]) -> dict:
    # Linear memory; each cell carries edit counts for reproducible alignment.
    previous = [(j, 0, 0, j) for j in range(len(hypothesis) + 1)]
    for i, expected in enumerate(reference, 1):
        current = [(i, 0, i, 0)]
        for j, observed in enumerate(hypothesis, 1):
            if expected == observed:
                current.append(previous[j - 1])
                continue
            distance, s, d, ins = previous[j - 1]
            substitution = (distance + 1, s + 1, d, ins)
            distance, s, d, ins = previous[j]
            deletion = (distance + 1, s, d + 1, ins)
            distance, s, d, ins = current[j - 1]
            insertion = (distance + 1, s, d, ins + 1)
            current.append(min((substitution, deletion, insertion), key=lambda item: item[0]))
        previous = current
    errors, substitutions, deletions, insertions = previous[-1]
    return {"referenceWords": len(reference), "errors": errors, "substitutions": substitutions,
            "deletions": deletions, "insertions": insertions,
            "wer": errors / len(reference) if reference else None}


def occurrences(words, phrase):
    return sum(words[index:index + len(phrase)] == phrase for index in range(len(words) - len(phrase) + 1)) if phrase else 0


def score(samples):
    if not isinstance(samples, list) or not 1 <= len(samples) <= 1000:
        raise ValueError("Provide 1–1000 samples.")
    results, seen = [], set()
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("Each sample must be an object.")
        identifier = sample.get("id")
        if not isinstance(identifier, str) or not identifier or len(identifier) > 160 or identifier in seen:
            raise ValueError("Sample IDs must be nonempty and unique.")
        seen.add(identifier)
        reference, hypothesis = sample.get("reference"), sample.get("hypothesis")
        if any(not isinstance(value, str) or len(value) > 50_000 for value in (reference, hypothesis)):
            raise ValueError("Reference and hypothesis must be bounded text.")
        ref, hyp = tokens(reference), tokens(hypothesis)
        if len(ref) > 5000 or len(hyp) > 5000:
            raise ValueError("Split long recordings into samples of at most 5000 words.")
        terms = sample.get("terms", [])
        if not isinstance(terms, list) or len(terms) > 100 or any(not isinstance(term, str) or len(term) > 256 or not tokens(term) for term in terms):
            raise ValueError("Terms must contain at most 100 nonempty phrases.")
        expected_terms = recovered_terms = 0
        for term in dict.fromkeys(terms):
            expected = occurrences(ref, tokens(term))
            expected_terms += expected
            recovered_terms += min(expected, occurrences(hyp, tokens(term)))
        group = sample.get("group", "unspecified")
        if not isinstance(group, str) or not group or len(group) > 160:
            raise ValueError("Group must be bounded text.")
        result = {"id": identifier, "group": group, **word_errors(ref, hyp),
                  "expectedTermOccurrences": expected_terms, "recoveredTermOccurrences": recovered_terms}
        for metric in ("latencyMs", "costUsd"):
            value = sample.get(metric)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError("Optional measurements must be nonnegative finite numbers.")
            result[metric] = value
        results.append(result)
    def aggregate(values):
        counts = Counter()
        for value in values:
            counts.update({key: value[key] for key in ("referenceWords", "errors", "substitutions", "deletions", "insertions", "expectedTermOccurrences", "recoveredTermOccurrences")})
        latencies = sorted(value["latencyMs"] for value in values if value["latencyMs"] is not None)
        costs = [value["costUsd"] for value in values if value["costUsd"] is not None]
        return {**counts, "sampleCount": len(values),
                "wer": counts["errors"] / counts["referenceWords"] if counts["referenceWords"] else None,
                "termRecall": counts["recoveredTermOccurrences"] / counts["expectedTermOccurrences"] if counts["expectedTermOccurrences"] else None,
                "latencySampleCount": len(latencies),
                "latencyP95Ms": latencies[math.ceil(len(latencies) * 0.95) - 1] if latencies else None,
                "costSampleCount": len(costs), "measuredCostUsd": sum(costs) if costs else None}
    return {"schemaVersion": 1, "normalization": "nfkc-casefold-word-apostrophe-v1",
            "overall": aggregate(results),
            "groups": {group: aggregate([r for r in results if r["group"] == group]) for group in sorted({r["group"] for r in results})},
            "samples": results,
            "limitations": ["Term recall measures phrase occurrence, not correct context or placement.",
                             "Numeric/equation meaning and speaker attribution require separate manual evaluation."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = json.dumps(score(payload["samples"]), indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
