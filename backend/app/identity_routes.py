"""Account management and acknowledged, owner-scoped device synchronization."""
import json
import secrets
import time
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, ConfigDict, AwareDatetime
from sqlalchemy import text

from .identity import current_principal, assert_owner_active, digest, fail


class DeviceInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal['desktop', 'canvas']


class SyncEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=10, max_length=120, pattern=r'^[A-Za-z0-9_.:-]+$')
    device_sequence: int = Field(ge=1)
    occurred_at: AwareDatetime
    kind: Literal['activity.observed', 'client.checkpoint']
    payload: dict


class SyncUpload(BaseModel):
    events: list[SyncEvent] = Field(max_length=100)


class PreferencesInput(BaseModel):
    expected_revision: int = Field(ge=0)
    preferences: dict


class DeleteInput(BaseModel):
    confirmation: Literal['DELETE']


class ImportInput(BaseModel):
    checksum: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirm_copy: Literal[True]

class PackageImportInput(ImportInput):
    package: dict


def build_identity_router(store_provider):
    router = APIRouter(prefix='/v1/account', tags=['identity'])

    def web_account():
        principal = current_principal()
        if principal.kind != 'web':
            fail('account_session_required', 'Sign in with your account to manage devices.', 403)
        return principal

    @router.get('')
    def account():
        p = current_principal()
        import os
        from .identity import hosted
        return {'ownerId': p.owner_id, 'displayName': p.display_name, 'mode': p.kind, 'deviceId': p.device_id,
                'localImportAvailable': not hosted() and bool(os.getenv('FORMA_API_TOKEN'))}

    def local_account(request):
        import os
        import hmac
        from .identity import hosted
        p = web_account()
        token = os.getenv('FORMA_API_TOKEN')
        if hosted() or not token or not hmac.compare_digest(request.headers.get('X-Forma-Desktop-Token', ''), token) or store_provider().engine.dialect.name != 'sqlite':
            fail('local_import_unavailable', 'Import requires the signed-in local desktop installation.', 403)
        return p

    @router.get('/local-profile')
    def profile_inventory(request: Request):
        from .identity_import import inventory
        return inventory(store_provider(), local_account(request).owner_id)

    @router.post('/local-profile/import')
    def profile_import(body: ImportInput, request: Request):
        from .identity_import import import_profile
        return import_profile(store_provider(), local_account(request).owner_id, body.checksum)

    @router.delete('/local-profile/import')
    def cancel_profile_import(request: Request):
        from .identity_import import reset_import
        return reset_import(store_provider(), local_account(request).owner_id)

    @router.get('/devices')
    def devices():
        p = web_account()
        with store_provider().engine.connect() as conn:
            rows = conn.execute(text('SELECT id,name,kind,created_at,expires_at,revoked_at,last_seen_at FROM identity_devices WHERE owner_id=:owner ORDER BY created_at DESC'), {'owner': p.owner_id}).mappings().all()
        return {'devices': [dict(row) for row in rows]}

    @router.post('/import-package')
    def package_import(body: PackageImportInput):
        from .identity_import import import_package
        return import_package(store_provider(),web_account().owner_id,body.package,body.checksum)

    @router.post('/import-package/review')
    def review_package(package: dict):
        web_account()
        import hashlib
        raw=json.dumps(package,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        if len(raw)>100_000_000 or package.get('format')!='openlearn-account-export' or package.get('version')!=1:
            fail('invalid_package','Unsupported or oversized account export.',422)
        return {'checksum':hashlib.sha256(raw).hexdigest(),'sourceProfile':package.get('ownerId'),'tables':{name:len(rows) for name,rows in package.get('tables',{}).items() if isinstance(rows,list)},'message':'Copy into an empty account with new identifiers. Existing local history is retained; device grants and jobs are excluded.'}

    @router.get('/export')
    def export():
        from .identity_data import export_owner
        return export_owner(store_provider(), current_principal().owner_id)

    @router.delete('')
    def delete_account(body: DeleteInput):
        from .identity_data import erase_owner
        return erase_owner(store_provider(), web_account().owner_id)

    @router.post('/devices', status_code=201)
    def link_device(body: DeviceInput):
        p = web_account()
        token, device = 'oldv_' + secrets.token_urlsafe(48), 'device_' + uuid4().hex
        now = time.time()
        with store_provider().transaction() as conn:
            assert_owner_active(conn, p.owner_id)
            conn.execute(text('INSERT INTO identity_devices(id,owner_id,name,kind,token_hash,created_at,expires_at,sequence) VALUES(:id,:owner,:name,:kind,:hash,:now,:expires,0)'), {'id': device, 'owner': p.owner_id, 'name': body.name, 'kind': body.kind, 'hash': digest(token), 'now': now, 'expires': now + 30*86400})
        return {'id': device, 'token': token, 'expiresAt': now + 30*86400, 'message': 'Save this grant on the linked device. It is shown only once.'}

    @router.delete('/devices/{device_id}')
    def revoke(device_id: str):
        p = web_account()
        from .identity_revocation import configured_revocation_journal, device_revocation_record
        journal = configured_revocation_journal()
        if journal is not None:
            with store_provider().engine.connect() as conn:
                exists = conn.execute(text('SELECT 1 FROM identity_devices WHERE id=:id AND owner_id=:owner AND revoked_at IS NULL'), {'id': device_id, 'owner': p.owner_id}).first()
            if not exists:
                fail('device_not_found', 'Device not found.', 404)
            journal.append(device_revocation_record(p.owner_id, device_id))
        with store_provider().transaction() as conn:
            result = conn.execute(text('UPDATE identity_devices SET revoked_at=:now WHERE id=:id AND owner_id=:owner'), {'now': time.time(), 'id': device_id, 'owner': p.owner_id})
            if not result.rowcount:
                fail('device_not_found', 'Device not found.', 404)
        return {'revoked': True}

    @router.post('/sync')
    def upload(body: SyncUpload):
        p = current_principal()
        if p.kind != 'desktop' or not p.device_id:
            fail('desktop_grant_required', 'Link this desktop before synchronizing.', 403)
        accepted = []
        with store_provider().transaction() as conn:
            assert_owner_active(conn, p.owner_id)
            # Locks the device across order allocation, retries and batch commit.
            changed = conn.execute(text('UPDATE identity_devices SET sequence=sequence WHERE id=:id AND revoked_at IS NULL AND expires_at>:now'), {'id': p.device_id, 'now': time.time()})
            if not changed.rowcount:
                fail('device_revoked', 'This device is no longer authorized.')
            sequence = conn.execute(text('SELECT sequence FROM identity_devices WHERE id=:id'), {'id': p.device_id}).scalar_one()
            for event in body.events:
                encoded = json.dumps(event.model_dump(mode='json'), sort_keys=True, separators=(',', ':'))
                if len(encoded.encode()) > 65536:
                    fail('event_too_large', 'A synchronization event exceeds 64 KB.', 413)
                fingerprint = digest(encoded)
                old = conn.execute(text('SELECT * FROM identity_sync_events WHERE id=:id OR (device_id=:device AND device_sequence=:seq)'), {'id': event.id, 'device': p.device_id, 'seq': event.device_sequence}).mappings().first()
                if old:
                    if old['owner_id'] != p.owner_id or old['device_id'] != p.device_id or old['payload_hash'] != fingerprint:
                        fail('sync_identity_conflict', 'An event identity or sequence was reused with different content.', 409)
                    accepted.append({'id': event.id, 'acceptedOrder': old['accepted_order']})
                    continue
                if event.device_sequence != sequence + 1:
                    fail('sync_sequence_gap', f'Upload device sequence {sequence + 1} next.', 409)
                conn.execute(text('INSERT INTO identity_sync_events(id,owner_id,device_id,device_sequence,occurred_at,accepted_at,kind,payload,payload_hash) VALUES(:id,:owner,:device,:seq,:occurred,:now,:kind,:payload,:hash)'), {'id': event.id, 'owner': p.owner_id, 'device': p.device_id, 'seq': event.device_sequence, 'occurred': event.occurred_at.isoformat(), 'now': time.time(), 'kind': event.kind, 'payload': encoded, 'hash': fingerprint})
                order = conn.execute(text('SELECT accepted_order FROM identity_sync_events WHERE id=:id'), {'id': event.id}).scalar_one()
                accepted.append({'id': event.id, 'acceptedOrder': order})
                sequence = event.device_sequence
            conn.execute(text('UPDATE identity_devices SET sequence=:seq WHERE id=:id'), {'seq': sequence, 'id': p.device_id})
        # Transport observations are not automatically admitted as learning evidence.
        return {'acknowledged': accepted, 'deviceSequence': sequence}

    @router.get('/sync')
    def pull(after: int = 0):
        p = current_principal()
        if after < 0:
            fail('invalid_cursor', 'Invalid synchronization cursor.', 422)
        with store_provider().engine.connect() as conn:
            rows = conn.execute(text('SELECT accepted_order,payload FROM identity_sync_events WHERE owner_id=:owner AND accepted_order>:after ORDER BY accepted_order LIMIT 100'), {'owner': p.owner_id, 'after': after}).mappings().all()
        return {'events': [{'acceptedOrder': r['accepted_order'], **json.loads(r['payload'])} for r in rows], 'cursor': rows[-1]['accepted_order'] if rows else after, 'hasMore': len(rows) == 100}

    @router.get('/preferences')
    def get_preferences():
        p = current_principal()
        with store_provider().engine.connect() as conn:
            row = conn.execute(text('SELECT revision,payload FROM identity_preferences WHERE owner_id=:owner'), {'owner': p.owner_id}).mappings().first()
        return {'revision': row['revision'], 'preferences': json.loads(row['payload'])} if row else {'revision': 0, 'preferences': {}}

    @router.put('/preferences')
    def update_preferences(body: PreferencesInput):
        p = current_principal()
        encoded = json.dumps(body.preferences, separators=(',', ':'))
        if len(encoded.encode()) > 32768:
            fail('preferences_too_large', 'Preferences exceed 32 KB.', 413)
        with store_provider().transaction() as conn:
            assert_owner_active(conn, p.owner_id)
            conn.execute(text("INSERT INTO identity_preferences(owner_id,revision,payload) VALUES(:owner,0,'{}') ON CONFLICT DO NOTHING"), {'owner': p.owner_id})
            result = conn.execute(text('UPDATE identity_preferences SET revision=revision+1,payload=:payload WHERE owner_id=:owner AND revision=:revision'), {'owner': p.owner_id, 'payload': encoded, 'revision': body.expected_revision})
            if not result.rowcount:
                row = conn.execute(text('SELECT revision,payload FROM identity_preferences WHERE owner_id=:owner'), {'owner': p.owner_id}).mappings().one()
                from fastapi import HTTPException
                raise HTTPException(409, detail={'code': 'revision_conflict', 'message': 'Preferences changed on another device. Reload before saving.', 'currentRevision': row['revision'], 'current': json.loads(row['payload'])})
        return {'revision': body.expected_revision + 1, 'preferences': body.preferences}

    return router
