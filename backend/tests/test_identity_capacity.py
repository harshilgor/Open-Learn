from types import SimpleNamespace
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, event
from sqlalchemy.exc import TimeoutError as DatabasePoolTimeout
from starlette.middleware.cors import CORSMiddleware
from backend.app import identity
from backend.app.identity_middleware import IdentityMiddleware


def test_repeated_web_authentication_does_not_write_unchanged_account(monkeypatch):
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE identity_accounts(id TEXT PRIMARY KEY,subject_hash TEXT UNIQUE,display_name TEXT,status TEXT,created_at REAL,verified_email TEXT)'))
    claims={'sub':'test-subject','name':'Learner','email':'learner@example.invalid','exp':9999999999}
    import jwt
    monkeypatch.setattr(jwt,'decode',lambda *args,**kwargs:claims)
    monkeypatch.setattr(identity,'jwks_client',lambda url:SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key='test')))
    for key,value in [('ISSUER','https://issuer.invalid'),('AUDIENCE','test'),('JWKS_URL','https://issuer.invalid/jwks')]:monkeypatch.setenv('OPENLEARN_OIDC_'+key,value)
    store=SimpleNamespace(engine=engine)
    principal=identity.authenticate(store,'Bearer test',None)
    statements=[]
    def record(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
    event.listen(engine,'before_cursor_execute',record)
    assert identity.authenticate(store,'Bearer test',None).owner_id==principal.owner_id
    assert not any(query.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for query in statements)
    claims['email']='changed@example.invalid'
    assert identity.authenticate(store,'Bearer test',None).email==claims['email']
    with engine.begin() as conn:conn.execute(text("UPDATE identity_accounts SET status='deleted'"))
    with pytest.raises(HTTPException) as denied:identity.authenticate(store,'Bearer test',None)
    assert denied.value.status_code==403
    engine.dispose()


def test_owner_validation_share_lock_allows_concurrency_and_blocks_deletion():
    statements=[]
    def execute(query,params):
        statements.append(str(query))
        return SimpleNamespace(scalar_one_or_none=lambda:'active')
    connection=SimpleNamespace(dialect=SimpleNamespace(name='postgresql'),execute=execute)
    identity.assert_owner_active(connection,'owner')
    assert statements==['SELECT status FROM identity_accounts WHERE id=:id FOR SHARE']


@pytest.mark.parametrize('failure_at',['authentication','endpoint'])
def test_database_capacity_error_is_retryable_and_has_cors(monkeypatch,failure_at):
    import backend.app.identity_middleware as middleware
    def authenticate(*args):
        if failure_at=='authentication':raise DatabasePoolTimeout('pool full')
        return identity.Principal('owner','web')
    monkeypatch.setattr(middleware,'authenticate',authenticate)
    app=FastAPI()
    @app.get('/v1/account')
    def endpoint():raise DatabasePoolTimeout('pool full')
    app.add_middleware(IdentityMiddleware,store_provider=lambda:object())
    app.add_middleware(CORSMiddleware,allow_origins=['https://open-learn-eta.vercel.app'])
    response=TestClient(app).get('/v1/account',headers={'Origin':'https://open-learn-eta.vercel.app'})
    assert response.status_code==503
    assert response.headers['access-control-allow-origin']=='https://open-learn-eta.vercel.app'
    assert response.headers['retry-after']=='3'
    assert response.json()['detail']['code']=='database_busy'
