"""Record phase outcomes without credentials, including incomplete releases."""
import json
import os
from pathlib import Path


def summarize(steps):
    def state(key):
        outcome = steps.get(key, {}).get("outcome", "skipped")
        return "completed" if outcome == "success" else "may have changed; inspect before retrying" if outcome in {"failure", "cancelled"} else "not started"
    return {"migration": state("migrate"), "backend_deployment": state("backend"),
            "frontend_staging": state("stage"), "production_promotion": state("promote"),
            "public_alias_verification": steps.get("alias", {}).get("outcome", "skipped")}


def main():
    result = {"commit": os.getenv("RELEASE_SHA"), "run": os.getenv("GITHUB_RUN_ID"),
              **summarize(json.loads(os.getenv("RELEASE_STEP_OUTCOMES", "{}")))}
    path = Path("outputs/release/state.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write("Release state for `" + str(result["commit"]) + "`\n\n")
            for key, value in result.items():
                output.write("- " + key.replace("_", " ") + ": " + str(value) + "\n")
            output.write("\nA failed workflow does not undo completed migrations or deployments.\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
