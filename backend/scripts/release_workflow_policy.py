"""Offline policy for release workflows: reject regressions before dispatch."""
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("duplicate_yaml_key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def policy_errors(source: str, *, release=False) -> list[str]:
    try:
        workflow = yaml.load(source, Loader=UniqueKeyLoader)
    except (yaml.YAMLError, ValueError, TypeError):
        return ["invalid_or_duplicate_workflow_yaml"]
    if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
        return ["workflow_jobs_invalid"]
    errors = []
    for job in workflow["jobs"].values():
        ids = set()
        for step in job.get("steps", []):
            identifier = step.get("id")
            if identifier in ids:
                errors.append("duplicate_step_id")
            if identifier:
                ids.add(identifier)
            if re.search(r"\bvercel\s+curl\b[^\n]*--token(?:[=\s]|$)", step.get("run", "")):
                errors.append("vercel_curl_forwards_token_to_native_curl")
    if not release:
        return sorted(set(errors))
    trigger = workflow.get("on", workflow.get(True, {}))
    operation = trigger.get("workflow_dispatch", {}).get("inputs", {}).get("operation", {})
    if operation.get("default") != "preflight":
        errors.append("release_must_default_to_preflight")
    if "freshness" not in workflow["jobs"] or workflow["jobs"].get("quality", {}).get("needs") != "freshness":
        errors.append("missing_candidate_freshness_gate")
    steps = workflow["jobs"].get("release", {}).get("steps", [])
    indexed = {step.get("id"): (index, step) for index, step in enumerate(steps) if step.get("id")}
    required = ["preflight", "build", "migrate", "backend", "stage", "promote", "alias"]
    if any(identifier not in indexed for identifier in required):
        errors.append("release_phase_missing")
    else:
        if [indexed[key][0] for key in required] != sorted(indexed[key][0] for key in required):
            errors.append("release_phase_order_invalid")
        for identifier in ("migrate", "backend", "stage", "promote", "alias"):
            if "inputs.operation == 'release'" not in str(indexed[identifier][1].get("if", "")):
                errors.append("production_write_not_gated:" + identifier)
        if "--skip-domain" not in indexed["stage"][1].get("run", ""):
            errors.append("candidate_can_promote_before_verification")
        before_stage = steps[indexed["backend"][0] + 1:indexed["stage"][0]]
        before_promote = steps[indexed["stage"][0] + 1:indexed["promote"][0]]
        for name, segment in (("backend", before_stage), ("candidate", before_promote)):
            if not any("release_gate" in step.get("run", "") and "--require-external-migrations" in step.get("run", "") for step in segment):
                errors.append("missing_compatibility_gate:" + name)
        if "frontend_release_metadata" not in indexed["alias"][1].get("run", ""):
            errors.append("production_alias_not_verified_with_same_authentication")
    if not any(step.get("if") == "always()" and "release_summary" in step.get("run", "") for step in steps):
        errors.append("missing_failure_state_report")
    if not any(step.get("if") == "always()" and "upload-artifact" in step.get("uses", "") for step in steps):
        errors.append("missing_failure_evidence")
    return sorted(set(errors))


def main():
    import json
    errors = {}
    for name in ("platform-release.yml", "platform-release-validation.yml"):
        failures = policy_errors((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"), release=name == "platform-release.yml")
        if failures:
            errors[name] = failures
    print(json.dumps({"passed": not errors, "errors": errors}))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
