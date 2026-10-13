"""Read Vercel release metadata using environment authentication, never deploy."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import urlsplit


def validate_origin(value: str) -> bool:
    try:
        if not isinstance(value, str) or any(char.isspace() or ord(char) < 32 for char in value):
            return False
        parsed = urlsplit(value)
        parsed.port  # Reject invalid or out-of-range ports as well.
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and parsed.path in {"", "/"} and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def metadata_command(executable: str, origin: str) -> list[str]:
    if not validate_origin(origin):
        raise ValueError("frontend_origin_invalid")
    # `vercel curl` passes unrecognized flags to native curl. In particular,
    # --token after this subcommand is NOT a Vercel authentication option.
    # VERCEL_TOKEN is inherited through the environment instead.
    return [executable, "curl", "/api/release", "--deployment", origin,
            "--yes", "--fail", "--silent", "--show-error", "--max-time", "30"]


def fetch_metadata(origin: str, *, runner=subprocess.run, executable=None) -> dict:
    executable = executable or shutil.which("vercel.cmd" if os.name == "nt" else "vercel")
    if not executable:
        raise ValueError("vercel_cli_missing")
    try:
        result = runner(metadata_command(executable, origin), capture_output=True,
                        text=True, timeout=45, check=False)
    except subprocess.TimeoutExpired:
        raise ValueError("frontend_metadata_timeout") from None
    except OSError:
        raise ValueError("vercel_cli_unavailable") from None
    if result.returncode:
        # Never echo CLI stderr: it can include credential-bearing arguments.
        diagnostic = result.stderr.lower()
        if "unknown" in diagnostic and "option" in diagnostic:
            code = "frontend_cli_argument_error"
        elif "401" in diagnostic or "403" in diagnostic or "authentication" in diagnostic:
            code = "frontend_authentication_failed"
        else:
            code = "frontend_metadata_fetch_failed"
        raise ValueError(code)
    try:
        report = json.loads(result.stdout.lstrip("\ufeff"))
    except (ValueError, TypeError):
        raise ValueError("frontend_metadata_not_json") from None
    if not isinstance(report, dict) or not re.fullmatch(r"[a-f0-9]{40}", str(report.get("commit", ""))):
        raise ValueError("frontend_metadata_invalid")
    if (not isinstance(report.get("protocolVersion"), int)
            or not isinstance(report.get("schemaHeads"), list)
            or not isinstance(report.get("requiredCapabilities"), list)
            or not all(isinstance(value, str) for value in report["schemaHeads"] + report["requiredCapabilities"])):
        raise ValueError("frontend_contract_metadata_invalid")
    return report


def fetch_expected_metadata(origin, expected_sha=None, *, attempts=3, fetcher=fetch_metadata, pause=time.sleep):
    if expected_sha and not re.fullmatch(r"[a-f0-9]{40}", expected_sha):
        raise ValueError("expected_frontend_sha_invalid")
    retryable = {"frontend_metadata_timeout", "frontend_metadata_fetch_failed", "frontend_commit_mismatch"}
    for attempt in range(max(1, min(3, attempts))):
        try:
            report = fetcher(origin)
            if expected_sha and report["commit"] != expected_sha:
                raise ValueError("frontend_commit_mismatch")
            return report
        except ValueError as error:
            if str(error) not in retryable or attempt + 1 >= max(1, min(3, attempts)):
                raise
            pause(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-sha")
    args = parser.parse_args()
    try:
        report = fetch_expected_metadata(args.frontend, args.expected_sha)
    except ValueError as error:
        print(json.dumps({"passed": False, "errors": [str(error)]}))
        raise SystemExit(1) from None
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "commit": report["commit"]}))


if __name__ == "__main__":
    main()
