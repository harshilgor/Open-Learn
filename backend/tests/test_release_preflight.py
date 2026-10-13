import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend.scripts.frontend_release_metadata import fetch_metadata, fetch_expected_metadata, metadata_command
from backend.scripts.release_preflight import configuration_errors, live_state, project_errors
from backend.scripts.release_summary import summarize
from backend.scripts.release_workflow_policy import policy_errors


def configuration():
    return {"RELEASE_ENVIRONMENT": "production", "RELEASE_SHA": "a" * 40,
            "DATABASE_MIGRATION_URL": "postgresql://role:private-password@db.example:5432/postgres",
            "OPENLEARN_API_ORIGIN": "https://api.example", "API_ORIGIN": "https://api.example",
            "OPENLEARN_FRONTEND_ORIGIN": "https://frontend.example", "RENDER_SERVICE_ID": "srv-test",
            "RENDER_DEPLOY_HOOK_URL": "https://api.render.com/deploy/srv-test?key=private-key",
            "VERCEL_TOKEN": "private-token", "VERCEL_ORG_ID": "team_test", "VERCEL_PROJECT_ID": "prj_test",
            "LIVE_BRANCHING_METRICS_TOKEN": "private-metrics"}


def metadata():
    return {"protocolVersion": 1, "commit": "a" * 40, "schemaHeads": ["older-schema"], "requiredCapabilities": ["existing"]}


def test_all_missing_configuration_is_reported_together_without_secrets():
    env = configuration()
    for key in ("OPENLEARN_FRONTEND_ORIGIN", "VERCEL_TOKEN", "LIVE_BRANCHING_METRICS_TOKEN"):
        del env[key]
    errors = configuration_errors(env)
    assert {"missing:OPENLEARN_FRONTEND_ORIGIN", "missing:VERCEL_TOKEN", "missing:LIVE_BRANCHING_METRICS_TOKEN"} <= set(errors)
    assert "private-" not in json.dumps(errors)


def test_wrong_render_service_transaction_pooler_and_origins_fail_before_writes():
    env = configuration()
    assert configuration_errors(env) == []
    env.update(DATABASE_MIGRATION_URL="postgresql://role:secret@db.example:6543/postgres",
               OPENLEARN_FRONTEND_ORIGIN="https://frontend.example/path?key=secret",
               RENDER_DEPLOY_HOOK_URL="https://api.render.com/deploy/srv-other?key=secret")
    assert {"migration_connection_transaction_pooler", "invalid_origin:OPENLEARN_FRONTEND_ORIGIN",
            "render_hook_service_mismatch_or_invalid"} <= set(configuration_errors(env))


def test_vercel_authentication_is_never_forwarded_to_native_curl(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "private-token")
    commands = []
    def runner(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(metadata()), stderr="")
    assert fetch_metadata("https://frontend.example", runner=runner, executable="vercel")["commit"] == "a" * 40
    assert "--token" not in " ".join(commands[0]) and "private-token" not in " ".join(commands[0])
    assert "--fail" in commands[0]
    with pytest.raises(ValueError, match="frontend_origin_invalid"):
        metadata_command("vercel", "https://frontend.example/\nunsafe")
    with pytest.raises(ValueError, match="frontend_origin_invalid"):
        metadata_command("vercel", "https://frontend.example\n")


@pytest.mark.parametrize("result,error", [
    (SimpleNamespace(returncode=2, stdout="", stderr="curl: option --token=private-token: is unknown"), "frontend_cli_argument_error"),
    (SimpleNamespace(returncode=22, stdout="", stderr="HTTP 403"), "frontend_authentication_failed"),
    (SimpleNamespace(returncode=0, stdout="<html>Login</html>", stderr=""), "frontend_metadata_not_json"),
    (SimpleNamespace(returncode=0, stdout="[]", stderr=""), "frontend_metadata_invalid"),
])
def test_authentication_cli_and_html_failures_are_distinct_and_redacted(result, error):
    with pytest.raises(ValueError) as caught:
        fetch_metadata("https://frontend.example", runner=lambda *args, **kwargs: result, executable="vercel")
    assert str(caught.value) == error and "private-token" not in str(caught.value)


def test_pulled_public_configuration_must_match_release_api(tmp_path):
    folder = tmp_path / ".vercel"
    folder.mkdir()
    (folder / "project.json").write_text(json.dumps({"orgId": "team_test", "projectId": "prj_test", "settings": {"rootDirectory": "web", "nodeVersion": "24.x"}}))
    (folder / ".env.production.local").write_text('NEXT_PUBLIC_LEARNING_API_URL="https://old-api.example"')
    assert project_errors(tmp_path, configuration()) == ["compiled_public_api_origin_mismatch"]


def test_baseline_probes_accept_healthy_old_schema_without_requiring_future_commit():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == "/release":
            return httpx.Response(200, json={"commit": "b" * 40, "schema": {"compatible": True, "actualHeads": ["older"]}, "migrationOwner": "single-release-job"})
        return httpx.Response(200, json={"status": "ready"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        state, errors = live_state(client, configuration())
    assert errors == [] and state["backend"]["commit"] == "b" * 40
    assert all(request.method == "GET" for request in requests)


def test_workflow_policy_rejects_reintroduced_cli_flag_and_yaml_duplication():
    assert policy_errors('jobs:\n  audit:\n    steps:\n      - run: vercel curl /api/release --token=secret\n') == ["vercel_curl_forwards_token_to_native_curl"]
    assert policy_errors('jobs: {}\njobs: {}\n') == ["invalid_or_duplicate_workflow_yaml"]


def test_mutation_conditions_and_phase_order_are_mandatory():
    source = (Path(__file__).resolve().parents[2] / ".github/workflows/platform-release.yml").read_text()
    assert policy_errors(source, release=True) == []
    invalid = source.replace("id: migrate\n        if: inputs.operation == 'release'", "id: migrate\n        if: always()")
    assert "production_write_not_gated:migrate" in policy_errors(invalid, release=True)
    assert "release_must_default_to_preflight" in policy_errors(source.replace("default: preflight", "default: release"), release=True)


def test_partial_failure_summary_never_implies_completed_changes_were_undone():
    result = summarize({"migrate": {"outcome": "success"}, "backend": {"outcome": "failure"}, "promote": {"outcome": "skipped"}})
    assert result["migration"] == "completed"
    assert result["backend_deployment"] == "may have changed; inspect before retrying"
    assert result["production_promotion"] == "not started"


def test_alias_propagation_retries_reads_but_never_retries_authentication_errors():
    reports = iter([{**metadata(), "commit": "b" * 40}, metadata()])
    pauses = []
    result = fetch_expected_metadata("https://frontend.example", "a" * 40,
                                     fetcher=lambda _: next(reports), pause=pauses.append)
    assert result["commit"] == "a" * 40 and pauses == [2]
    calls = []
    def reject(origin):
        calls.append(origin)
        raise ValueError("frontend_authentication_failed")
    with pytest.raises(ValueError, match="frontend_authentication_failed"):
        fetch_expected_metadata("https://frontend.example", fetcher=reject, pause=pauses.append)
    assert len(calls) == 1
