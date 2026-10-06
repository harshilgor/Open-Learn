"""Trusted identity boundary. Provider passwords and refresh tokens stay with OIDC."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import os
import re
import time

from fastapi import HTTPException
from sqlalchemy import text


@dataclass(frozen=True)
class Principal:
    owner_id: str
    kind: str
    device_id: str | None = None
    display_name: str = ''
    expires_at: float | None = None
    email: str = ''


principal_context: ContextVar[Principal | None] = ContextVar('openlearn_principal', default=None)


def hosted() -> bool:
    return os.getenv('AI_TUTOR_ENV', 'development').lower() in {'production', 'deployed'}


def fail(code, message, status=401):
    raise HTTPException(status, detail={'code': code, 'message': message})


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def issue_device_grant(connection, owner, name, kind='canvas'):
    """Issue a narrow grant in the pairing transaction; never copy browser JWTs."""
    import secrets
    from uuid import uuid4
    principal=current_principal()
    if principal.owner_id!=owner or principal.kind not in {'web','local'}:
        fail('account_session_required','Pair a device using the account browser or local profile.',403)
    if kind not in {'canvas','desktop','browser'}: fail('invalid_device_kind','Unknown device capability.',422)
    assert_principal_active(connection,principal)
    token='oldv_'+secrets.token_urlsafe(48)
    identifier='device_'+uuid4().hex
    now=time.time(); expires=now+30*86400
    connection.execute(text('INSERT INTO identity_devices(id,owner_id,name,kind,token_hash,created_at,expires_at,sequence) VALUES(:id,:owner,:name,:kind,:hash,:now,:expires,0)'),{'id':identifier,'owner':owner,'name':name[:120],'kind':kind,'hash':digest(token),'now':now,'expires':expires})
    return {'id':identifier,'token':token,'expiresAt':expires}


def validate_identity_configuration():
    if hosted():
        if os.getenv('AI_TUTOR_DEV_IDENTITY', 'false').lower() != 'false':
            raise RuntimeError('Hosted environments must set AI_TUTOR_DEV_IDENTITY=false.')
        for name in ('OPENLEARN_OIDC_ISSUER', 'OPENLEARN_OIDC_AUDIENCE', 'OPENLEARN_OIDC_JWKS_URL'):
            if not os.getenv(name):
                raise RuntimeError(f'{name} is required for hosted authentication.')
    for name in ('OPENLEARN_OIDC_ISSUER', 'OPENLEARN_OIDC_JWKS_URL'):
        if os.getenv(name) and not os.environ[name].startswith('https://'):
            raise RuntimeError(f'{name} must use HTTPS.')


def assert_owner_active(connection, owner: str):
    # Lock the account through the caller's transaction; deletion waits for commits
    # already in flight and later work observes the durable tombstone.
    suffix = ' FOR UPDATE' if connection.dialect.name == 'postgresql' else ''
    status = connection.execute(text('SELECT status FROM identity_accounts WHERE id=:id' + suffix), {'id': owner}).scalar_one_or_none()
    if status == 'deleted':
        fail('account_deleted', 'This account has been deleted.', 403)


def current_principal() -> Principal:
    value = principal_context.get()
    if value is None:
        fail('authentication_required', 'A verified session is required.')
    return value


def assert_principal_active(connection, principal):
    assert_owner_active(connection, principal.owner_id)
    if principal.expires_at is not None and principal.expires_at <= time.time():
        fail('session_expired', 'Your session expired before this change was saved.')
    if principal.device_id:
        row = connection.execute(text('SELECT revoked_at,expires_at FROM identity_devices WHERE id=:id AND owner_id=:owner'), {'id': principal.device_id, 'owner': principal.owner_id}).mappings().first()
        if not row or row['revoked_at'] is not None or row['expires_at'] <= time.time():
            fail('device_revoked', 'This device is no longer authorized.')


def authorize_owner(owner: str, claimed=None):
    if current_principal().owner_id != owner:
        fail('owner_scope_mismatch', 'This resource belongs to another account.', 403)


@lru_cache(maxsize=2)
def jwks_client(url):
    from jwt import PyJWKClient
    return PyJWKClient(url, cache_jwk_set=True, lifespan=300, timeout=10)


def authenticate(store, authorization: str | None, local_owner: str | None) -> Principal:
    if authorization:
        if not authorization.startswith('Bearer '):
            fail('invalid_session', 'Use a bearer session.')
        token = authorization[7:]
        if token.startswith('oldv_'):
            with store.engine.begin() as conn:
                row = conn.execute(text('SELECT * FROM identity_devices WHERE token_hash=:hash'), {'hash': digest(token)}).mappings().first()
                if not row or row['revoked_at'] is not None or row['expires_at'] <= time.time():
                    fail('device_revoked', 'This device is expired or revoked. Link it again.')
                assert_owner_active(conn, row['owner_id'])
                conn.execute(text('UPDATE identity_devices SET last_seen_at=:now WHERE id=:id'), {'now': time.time(), 'id': row['id']})
                return Principal(row['owner_id'], row['kind'], row['id'], expires_at=row['expires_at'])
        issuer, audience, jwks = (os.getenv('OPENLEARN_OIDC_' + name) for name in ('ISSUER', 'AUDIENCE', 'JWKS_URL'))
        if not all((issuer, audience, jwks)):
            fail('authentication_unconfigured', 'Configure the account provider before signing in.', 503)
        try:
            import jwt
            key = jwks_client(jwks).get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=['RS256', 'ES256'], issuer=issuer, audience=audience,
                                options={'require': ['exp', 'iat', 'sub', 'iss', 'aud']}, leeway=30)
            subject = claims['sub']
            if not isinstance(subject, str) or not subject:
                raise ValueError('missing subject')
        except Exception:
            fail('invalid_session', 'Your session has expired or is invalid. Sign in again.')
        subject_hash = digest(issuer + '\0' + subject)
        owner = 'account_' + subject_hash[:48]
        display = str(claims.get('name') or claims.get('email') or 'Learner')[:250]
        with store.engine.begin() as conn:
            conn.execute(text("INSERT INTO identity_accounts(id,subject_hash,display_name,status,created_at) VALUES(:id,:hash,:name,'active',:now) ON CONFLICT(subject_hash) DO NOTHING"), {'id': owner, 'hash': subject_hash, 'name': display, 'now': time.time()})
            assert_owner_active(conn, owner)
        return Principal(owner, 'web', display_name=display, expires_at=float(claims['exp']),
                         email=str(claims.get('email') or '').strip().lower())
    if hosted() and not all(os.getenv('OPENLEARN_OIDC_' + name) for name in ('ISSUER', 'AUDIENCE', 'JWKS_URL')):
        fail('authentication_unconfigured', 'Configure the account provider before signing in.', 503)
    if hosted() or os.getenv('AI_TUTOR_DEV_IDENTITY', 'true').lower() not in {'true', '1', 'yes'}:
        fail('authentication_required', 'Sign in to continue.')
    owner = local_owner or 'local'
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', owner) or owner.startswith('account_'):
        fail('invalid_local_profile', 'Invalid local profile.', 400)
    return Principal(owner, 'local', display_name='Local profile')


def grant_resource(connection, kind, resource_id, owner=None):
    principal = principal_context.get()
    owner = owner or (principal.owner_id if principal else None)
    if owner:
        assert_owner_active(connection, owner)
        connection.execute(text('INSERT INTO identity_resources(kind,id,owner_id) VALUES(:kind,:id,:owner) ON CONFLICT DO NOTHING'), {'kind': kind, 'id': resource_id, 'owner': owner})


def authorize_resource(connection, kind, resource_id):
    principal = principal_context.get()
    if principal is None:
        return  # Internal workers retain their explicit owner/service checks.
    row = connection.execute(text('SELECT 1 FROM identity_resources WHERE kind=:kind AND id=:id AND owner_id=:owner'), {'kind': kind, 'id': resource_id, 'owner': principal.owner_id}).first()
    if not row:
        fail('resource_not_found', 'Resource not found.', 404)
