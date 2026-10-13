"""Read-only release audit. Report all configuration blockers before migrations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qsl, urlsplit

import httpx
from dotenv import dotenv_values

from .frontend_release_metadata import fetch_metadata, validate_origin

ROOT = Path(__file__).resolve().parents[2]


def configuration_errors(env) -> list[str]:
    errors = []
    required = ["DATABASE_MIGRATION_URL", "OPENLEARN_API_ORIGIN", "RENDER_SERVICE_ID",
                "VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID", "RELEASE_SHA",
                "OPENLEARN_FRONTEND_ORIGIN"]
    if env.get("RELEASE_ENVIRONMENT") == "production":
        required += ["LIVE_BRANCHING_METRICS_TOKEN"]
    errors += ["missing:" + key for key in required if not env.get(key)]
    if env.get("RELEASE_ENVIRONMENT") not in {"staging", "production"}:
        errors.append("release_environment_invalid")
    for key in ("OPENLEARN_API_ORIGIN", "OPENLEARN_FRONTEND_ORIGIN"):
        if env.get(key) and not validate_origin(env[key]):
            errors.append("invalid_origin:" + key)
    if env.get("API_ORIGIN") and env.get("API_ORIGIN").rstrip("/") != env.get("OPENLEARN_API_ORIGIN", "").rstrip("/"):
        errors.append("backend_origin_alias_mismatch")
    if env.get("RELEASE_SHA") and not re.fullmatch(r"[a-f0-9]{40}", env["RELEASE_SHA"]):
        errors.append("release_sha_invalid")
    if env.get("DATABASE_MIGRATION_URL"):
        try:
            db = urlsplit(env["DATABASE_MIGRATION_URL"])
            if db.scheme not in {"postgresql", "postgresql+psycopg"} or not db.hostname or not db.path.strip("/"):
                errors.append("migration_connection_invalid")
            if db.port == 6543:
                errors.append("migration_connection_transaction_pooler")
        except ValueError:
            errors.append("migration_connection_invalid")
    service = env.get("RENDER_SERVICE_ID", "")
    if service and not re.fullmatch(r"srv-[a-z0-9]+", service):
        errors.append("render_service_id_invalid")
    hook = env.get("RENDER_DEPLOY_HOOK_URL")
    if hook:
        try:
            parsed = urlsplit(hook)
            if (parsed.scheme != "https" or parsed.hostname != "api.render.com"
                    or parsed.path != "/deploy/" + service or parsed.username or parsed.password
                    or not any(key == "key" and value for key, value in parse_qsl(parsed.query))):
                errors.append("render_hook_service_mismatch_or_invalid")
        except ValueError:
            errors.append("render_hook_service_mismatch_or_invalid")
    elif not env.get("RENDER_API_TOKEN"):
        errors.append("missing:render_deployment_credential")
    for key, prefix in (("VERCEL_ORG_ID", "team_"), ("VERCEL_PROJECT_ID", "prj_")):
        if env.get(key) and not re.fullmatch(prefix + r"[A-Za-z0-9]+", env[key]):
            errors.append("invalid_identifier:" + key)
    return sorted(set(errors))


def repository_errors(root=ROOT, expected_sha=None) -> list[str]:
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    errors = []
    if git("merge-base", "--is-ancestor", "origin/main", "HEAD").returncode != 0:
        errors.append("candidate_missing_current_main")
    status = git("status", "--porcelain", "--untracked-files=normal")
    if status.returncode or status.stdout.strip():
        errors.append("candidate_has_uncommitted_changes")
    if expected_sha and git("rev-parse", "HEAD").stdout.strip() != expected_sha:
        errors.append("candidate_commit_mismatch")
    return errors


def project_errors(root, env) -> list[str]:
    errors = []
    try:
        project = json.loads((root / ".vercel/project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["vercel_project_configuration_unavailable"]
    for key, variable in (("projectId", "VERCEL_PROJECT_ID"), ("orgId", "VERCEL_ORG_ID")):
        if project.get(key) != env.get(variable):
            errors.append("vercel_project_link_mismatch:" + key)
    settings = project.get("settings", {})
    if settings.get("rootDirectory") != "web":
        errors.append("vercel_project_root_must_be_web")
    if settings.get("nodeVersion") != "24.x":
        errors.append("vercel_node_version_must_match_ci_24")
    environment = "production" if env.get("RELEASE_ENVIRONMENT") == "production" else "preview"
    path = root / ".vercel" / (".env." + environment + ".local")
    if not path.exists():
        return errors + ["vercel_pulled_environment_unavailable"]
    pulled = dotenv_values(path)
    public = (pulled.get("NEXT_PUBLIC_LEARNING_API_URL") or "").strip()
    if public and (not validate_origin(public) or public.rstrip("/") != env.get("OPENLEARN_API_ORIGIN", "").rstrip("/")):
        errors.append("compiled_public_api_origin_mismatch")
    return errors


def live_state(client, env) -> tuple[dict, list[str]]:
    """Baseline may have older schema/capabilities; validate health, not future SHA."""
    state, errors = {}, []
    api = env["OPENLEARN_API_ORIGIN"].rstrip("/")
    for name, path in (("readiness", "/ready"), ("backend", "/release")):
        try:
            response = client.get(api + path)
            if response.status_code != 200:
                errors.append(name + "_http_" + str(response.status_code))
                continue
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError()
            state[name] = body
        except httpx.TimeoutException:
            errors.append(name + "_timeout")
        except httpx.HTTPError:
            errors.append(name + "_connection_failed")
        except (ValueError, TypeError):
            errors.append(name + "_metadata_invalid")
    backend = state.get("backend", {})
    schema = backend.get("schema") if isinstance(backend.get("schema"), dict) else {}
    if backend and (schema.get("compatible") is not True
                    or backend.get("migrationOwner") != "single-release-job"):
        errors.append("current_backend_schema_or_migration_owner_invalid")
    token = env.get("LIVE_BRANCHING_METRICS_TOKEN")
    if token:
        try:
            response = client.get(api + "/operations/performance", headers={"X-OpenLearn-Metrics-Token": token})
            if response.status_code != 200:
                errors.append("diagnostics_authentication_or_availability_failed")
        except httpx.HTTPError:
            errors.append("diagnostics_connection_failed")
    return state, errors


def database_errors(url, backend_heads) -> list[str]:
    """SELECT-only check; never instantiate Store or invoke migration startup."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.pool import NullPool
    engine = None
    try:
        engine = create_engine(make_url(url).set(drivername="postgresql+psycopg"),
                               poolclass=NullPool, connect_args={"connect_timeout": 10})
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '10s'"))
            heads = sorted(connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all())
            if heads != sorted(backend_heads):
                return ["migration_connection_schema_differs_from_api"]
    except Exception:
        return ["migration_connection_read_probe_failed"]
    finally:
        if engine is not None:
            engine.dispose()
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true", help="Use existing credentials for read-only DB/platform probes")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    env = os.environ
    errors = configuration_errors(env) + repository_errors(expected_sha=env.get("RELEASE_SHA"))
    state = {}
    if args.online:
        errors += project_errors(ROOT, env)
        if validate_origin(env.get("OPENLEARN_API_ORIGIN", "")):
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                state, failures = live_state(client, env)
                errors += failures
        frontend = env.get("OPENLEARN_FRONTEND_ORIGIN")
        if frontend and validate_origin(frontend):
            try:
                state["frontend"] = fetch_metadata(frontend)
                fingerprint = hashlib.sha256(env.get("OPENLEARN_API_ORIGIN", "").rstrip("/").encode()).hexdigest()
                if state["frontend"].get("apiOriginFingerprint") != fingerprint:
                    errors.append("current_frontend_api_origin_mismatch")
            except ValueError as error:
                errors.append(str(error))
        backend = state.get("backend", {})
        schema = backend.get("schema") if isinstance(backend.get("schema"), dict) else {}
        heads = schema.get("actualHeads")
        if backend and isinstance(heads, list) and all(isinstance(value, str) for value in heads) and not any("migration_connection" in error or error == "missing:DATABASE_MIGRATION_URL" for error in errors):
            errors += database_errors(env["DATABASE_MIGRATION_URL"], heads)
    result = {"passed": not errors, "mode": "read-only", "errors": sorted(set(errors)), "baseline": state,
              "limitations": ["Matching schema heads do not independently prove database project identity.",
                              "Read access does not prove future DDL permissions or deployment success."]}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "baseline"}))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
