import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.release import build_release_router, code_schema_heads, release_contract, release_status, queue_health
from backend.app.storage import Store
from backend.scripts.release_gate import check_backend, validate_report, validate_frontend_report
from backend.scripts.render_release import deploy
from backend.scripts import release_gate
import hashlib


def compatible():
    contract = release_contract()
    return {'commit': 'a' * 40, 'protocolVersion': contract['protocolVersion'],
        'capabilities': contract['requiredCapabilities'],
        'schema': {'actualHeads': contract['schemaHeads'], 'compatible': True}}


@pytest.mark.parametrize('change,expected', [
    ({'protocolVersion': -1}, 'protocol_version_mismatch'),
    ({'capabilities': []}, 'missing_capability'),
    ({'schema': {'actualHeads': ['old'], 'compatible': False}}, 'schema_mismatch'),
    ({'commit': 'wrong'}, 'commit_mismatch'),
])
def test_release_gate_fails_closed_on_incompatible_versions(change, expected):
    assert expected in validate_report({**compatible(), **change}, release_contract(), 'a' * 40)


def test_network_gate_requires_readiness_and_metadata():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200,
        json={'status': 'ready'} if request.url.path == '/ready' else compatible()))) as client:
        assert check_backend(client, 'https://api.example', release_contract(), 'a' * 40) == []
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404))) as client:
        assert check_backend(client, 'https://api.example', release_contract()) == ['backend_not_ready']


def test_malformed_metadata_returns_explicit_errors_instead_of_crashing():
    assert validate_report([], release_contract()) == ['backend_metadata_invalid']
    assert 'backend_capability_metadata_invalid' in validate_report({**compatible(), 'capabilities': [[]]}, release_contract())
    assert validate_frontend_report([], release_contract(), 'https://api.example') == ['frontend_metadata_invalid']


def test_contract_heads_match_migrations_and_gate_detects_schema_drift(tmp_path, monkeypatch):
    assert release_contract()['schemaHeads'] == code_schema_heads()
    monkeypatch.setenv('OPENLEARN_MIGRATE_ON_START', 'true')
    store = Store(tmp_path / 'release.db')
    try:
        assert release_status(store)['schema']['compatible'] is True
        assert queue_health(store)['available'] is True
        assert queue_health(store)['generations']['activeIncludingQueued'] == 0
        with store.engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num='unexpected'"))
        assert release_status(store)['schema']['compatible'] is False
    finally:
        store.close()


def test_process_metrics_are_private_even_without_identity_middleware(monkeypatch):
    app = FastAPI()
    app.include_router(build_release_router(lambda: None))
    monkeypatch.delenv('LIVE_BRANCHING_METRICS_TOKEN', raising=False)
    with TestClient(app) as client:
        assert client.get('/operations/performance').status_code == 404
        monkeypatch.setenv('LIVE_BRANCHING_METRICS_TOKEN', 'operator-only')
        assert client.get('/operations/performance').status_code == 401
        assert client.get('/operations/performance', headers={'X-OpenLearn-Metrics-Token': 'incorrect'}).status_code == 401
        response = client.get('/operations/performance', headers={'X-OpenLearn-Metrics-Token': 'operator-only'})
        assert response.status_code == 200 and response.json()['scope'] == 'process'
        assert response.headers['cache-control'] == 'no-store'


def test_render_release_uses_one_immutable_deploy_and_checks_its_result():
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == 'POST':
            assert json.loads(request.content)['commitId'] == 'a' * 40
            return httpx.Response(201, json={'id': 'dep-test'})
        return httpx.Response(200, json={'status': 'live', 'commit': {'id': 'a' * 40}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert deploy(client, 'srv-test', 'a' * 40, pause=lambda _: None)['status'] == 'live'
    assert [request.method for request in requests] == ['POST', 'GET']


def test_render_failure_stops_before_frontend_release():
    def handler(request):
        return httpx.Response(201, json={'id': 'dep-test'}) if request.method == 'POST' else httpx.Response(200, json={'status': 'build_failed'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match='build_failed'):
            deploy(client, 'srv-test', 'a' * 40, pause=lambda _: None)


@pytest.mark.parametrize('frontend_api,exit_code', [('https://api.example', 0), ('https://old-api.example', 1)])
def test_pair_gate_rejects_frontend_pointing_at_a_different_api(monkeypatch, frontend_api, exit_code):
    import sys
    contract = release_contract()
    frontend = {'protocolVersion': contract['protocolVersion'], 'schemaHeads': contract['schemaHeads'],
        'requiredCapabilities': contract['requiredCapabilities'],
        'apiOriginFingerprint': hashlib.sha256(frontend_api.encode()).hexdigest()}
    def handler(request):
        body = frontend if request.url.host == 'frontend.example' else compatible() if request.url.path == '/release' else {'status': 'ready'}
        return httpx.Response(200, json=body)
    client_type = httpx.Client
    monkeypatch.setattr(release_gate.httpx, 'Client', lambda **kwargs: client_type(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(sys, 'argv', ['release_gate', '--api', 'https://api.example', '--frontend', 'https://frontend.example'])
    with pytest.raises(SystemExit) as outcome:
        release_gate.main()
    assert outcome.value.code == exit_code
