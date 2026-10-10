"""Owner-scoped portability using declared ownership and relational dependencies."""
import json
from sqlalchemy import MetaData, select, or_, and_, text
from .identity import assert_owner_active

PRIVATE_TABLES = {'identity_devices', 'identity_accounts', 'browser_session_leases', 'browser_provider_cleanup', 'notification_subscriptions', 'assistant_steps','agent_sandbox_cleanup','agent_sandbox_leases'}
PRIVATE_TABLES.update({'agent_app_connections','agent_app_oauth','agent_standing_grants','agent_action_decisions'})
PRIVATE_TABLES.update({'calendar_permissions','calendar_proposals','calendar_operations','calendar_sync'})


def owned_rows(connection, owner):
    metadata = MetaData()
    metadata.reflect(bind=connection)
    result = {}
    # A row with explicit ownership never inherits another account's ownership.
    for name, table in metadata.tables.items():
        key = next((k for k in ('owner_id', 'learner_id', 'owner_learner_id') if k in table.c), None)
        if key:
            result[name] = list(connection.execute(select(table).where(table.c[key] == owner)).mappings())
        elif name == 'learners' and 'id' in table.c:
            result[name] = list(connection.execute(select(table).where(table.c.id == owner)).mappings())
        else:
            result[name] = []
    # Add legacy graph records from the explicit ownership index.
    for grant in result.get('identity_resources', []):
        table = metadata.tables.get(grant['kind'])
        if table is not None and 'id' in table.c:
            result[grant['kind']].extend(connection.execute(select(table).where(table.c.id == grant['id'])).mappings())
    changed = True
    while changed:
        changed = False
        for name, table in metadata.tables.items():
            if any(k in table.c for k in ('owner_id', 'learner_id', 'owner_learner_id')) or name.startswith('identity_'):
                continue
            predicates = []
            for constraint in table.foreign_key_constraints:
                if not constraint.elements:
                    continue
                parent = constraint.elements[0].column.table.name
                for row in result.get(parent, []):
                    predicates.append(and_(*(element.parent == row[element.column.name] for element in constraint.elements)))
            if predicates:
                known = {tuple(row[k.name] for k in table.primary_key) for row in result[name]}
                for offset in range(0, len(predicates), 100):
                    for row in connection.execute(select(table).where(or_(*predicates[offset:offset+100]))).mappings():
                        identity = tuple(row[k.name] for k in table.primary_key)
                        if identity not in known:
                            result[name].append(row)
                            known.add(identity)
                            changed = True
    return metadata, result


def export_owner(store, owner):
    with store.transaction() as conn:
        assert_owner_active(conn, owner)
        _, records = owned_rows(conn, owner)
        from .privacy_routes import _json_value
        exported = {'format': 'openlearn-account-export', 'version': 1, 'ownerId': owner,
                'tables': {name: [{key: _json_value(value) for key, value in row.items()} for row in rows]
                           for name, rows in records.items() if rows and name not in PRIVATE_TABLES}}
    import base64
    for row in exported['tables'].get('voice_sessions', []):
        row['capability_hash'] = ''
        row['status'] = 'ended'
    from .identity import digest
    import hashlib
    files = []
    for item in object_manifest(records, owner):
        try:
            data = object_operation(store, item, delete=False)
            files.append({**item, 'sha256': hashlib.sha256(data).hexdigest(), 'encoding': 'base64', 'content': base64.b64encode(data).decode()})
        except FileNotFoundError:
            files.append({**item, 'status': 'missing'})
    exported['files'] = files
    for row in exported['tables'].get('canvas_connections',[]):
        payload=json.loads(row['payload'])
        payload.pop('grantHash',None)
        payload['status']='exported_disconnected'
        row['payload']=json.dumps(payload)
    for row in exported['tables'].get('site_connections', []):
        payload = json.loads(row['payload'])
        for key in ('providerContextId', 'loginSessionId', 'deviceId', 'connectUrl', 'liveViewUrl'):
            payload.pop(key, None)
        payload['status'] = 'exported_disconnected'
        row['device_id'] = None
        row['payload'] = json.dumps(payload)
    # Portable restore intentionally accepts only safe content, never live
    # execution state. Make the export/import boundary machine-readable so a
    # package consumer does not mistake exported task history for restorable
    # checkpoints, approvals, schedules, or provider credentials.
    from .identity_import import OMIT
    exported['compatibility'] = {
        'policyVersion': 1,
        'restoreMode': 'safe_content_only',
        'restorableTables': sorted(set(exported['tables']) - OMIT),
        'exportOnlyTables': sorted(set(exported['tables']) & OMIT),
        'privateTablesNotExported': sorted(PRIVATE_TABLES),
        'executionStateRestored': False,
        'externalApprovalsRestored': False,
        'providerCredentialsRestored': False,
        'limitations': [
            'Agent and browser tasks, checkpoints, messages, activity, artifacts, schedules, leases, and approvals are not resumed by portable import.',
            'Exported files linked only to excluded execution records remain archival export data and are not imported as runnable artifacts.',
            'Infrastructure backup restore requires a separate revocation-reconciliation step before traffic or workers resume.',
        ],
    }
    exported['readme'] = 'Tables retain original IDs and relationships. Files contain base64 originals with SHA-256. Transcript and note text are in their source tables; derived rows are not evidence of mastery. The compatibility manifest states which exported records portable import can restore.'
    return exported


def object_manifest(records, owner):
    items = []
    for row in records.get('material_versions', []):
        if row.get('object_key'):
            items.append({'owner_id': owner, 'kind': 'material', 'recording_id': None, 'object_key': row['object_key']})
    for row in records.get('class_recordings', []):
        items.append({'owner_id': owner, 'kind': 'class', 'recording_id': row['id'], 'object_key': row['id']})
    for row in records.get('workspace_notes', []):
        items.append({'owner_id': owner, 'kind': 'note', 'recording_id': None, 'object_key': row['id']})
    for row in records.get('lecture_audio_chunks', []):
        items.append({'owner_id': owner, 'kind': 'lecture', 'recording_id': row['recording_id'], 'object_key': row['storage_key']})
    for row in records.get('assistant_objects', []):
        items.append({'owner_id': owner, 'kind': 'assistant', 'recording_id': None, 'object_key': row['object_key']})
    for row in records.get('agent_artifacts', []):
        if row.get('status') != 'deleted':
            items.append({'owner_id': owner, 'kind': 'assistant', 'recording_id': None, 'object_key': row['object_key']})
    for row in records.get('agent_sandbox_leases',[]):
        for output in json.loads(row['payload']).get('outputs',{}).values():
            items.append({'owner_id':owner,'kind':'assistant','recording_id':None,'object_key':output['key']})
    return items


def object_operation(store, item, delete):
    if item['kind'] == 'assistant':
        from .browser_assistant.evidence import evidence_objects
        objects = evidence_objects(store)
        return objects.delete(item['owner_id'], item['object_key']) if delete else objects.read(item['owner_id'], item['object_key'])
    if item['kind'] == 'lecture':
        from .lecture_storage import LectureObjectStore
        objects = LectureObjectStore()
        return objects.delete(item['owner_id'], item['recording_id'], item['object_key']) if delete else objects.read(item['owner_id'], item['recording_id'], item['object_key'])
    if item['kind'] == 'material':
        from .material_service import MaterialService
        objects=MaterialService(store).objects
        return objects.delete(item['object_key']) if delete else objects.read(item['object_key'])
    elif item['kind'] == 'note':
        from .workspace_note_service import WorkspaceNoteService
        from .identity import hosted
        if hosted() and not delete:
            service=WorkspaceNoteService(store)
            service._read_file(item['owner_id'],item['object_key'])
        path = WorkspaceNoteService(store).note_path(item['owner_id'], item['object_key'])
    else:
        from .class_recording_service import ClassRecordingService
        path = ClassRecordingService(store)._path(item['owner_id'], item['recording_id'])
    return path.unlink(missing_ok=True) if delete else path.read_bytes()


def cleanup_objects(store):
    with store.engine.connect() as conn:
        items = conn.execute(text('SELECT * FROM identity_object_cleanup LIMIT 20')).mappings().all()
    for item in items:
        object_operation(store, item, delete=True)
        with store.engine.begin() as conn:
            conn.execute(text('DELETE FROM identity_object_cleanup WHERE id=:id'), {'id': item['id']})
    return bool(items)


def erase_owner(store, owner, *, revocation_journal=None):
    from .identity_import import _profile_locks
    from .identity_revocation import account_deletion_record, configured_revocation_journal
    with _profile_locks[owner]:
        journal = revocation_journal if revocation_journal is not None else configured_revocation_journal()
        if journal is not None:
            # The append-only authority receives the tombstone before local data
            # is erased, so a later database restore cannot revive the account.
            journal.append(account_deletion_record(owner))
        return _erase_owner(store, owner)


def _erase_owner(store, owner):
    import time
    with store.engine.begin() as conn:
        assert_owner_active(conn, owner)
        conn.execute(text("UPDATE identity_accounts SET status='deleted',deleted_at=:now,display_name='' WHERE id=:owner"), {'now': time.time(), 'owner': owner})
        conn.execute(text('UPDATE identity_devices SET revoked_at=:now WHERE owner_id=:owner'), {'now': time.time(), 'owner': owner})
        conn.execute(text("UPDATE learning_jobs SET status='cancelled',lease=NULL,expires=NULL,cancellation_requested=true WHERE owner_id=:owner"), {'owner': owner})
        metadata, records = owned_rows(conn, owner)
        if 'agent_sandbox_budgets' in metadata.tables:
            from .agent_execution.repository import digest as agent_digest
            conn.execute(text('DELETE FROM agent_sandbox_budgets WHERE scope=:scope'),{'scope':'owner:'+agent_digest(owner)})
        from uuid import uuid4
        objects = object_manifest(records, owner)
        for lease in records.get('agent_sandbox_leases',[]):
            if lease['status'] not in {'released','deleted'}:
                conn.execute(text('INSERT INTO agent_sandbox_cleanup(id,owner_id,creation_key,provider_id,created_at) VALUES(:id,:owner,:key,:provider,:now)'),
                    {'id':uuid4().hex,'owner':owner,'key':lease['creation_key'],'provider':lease['provider_id'],'now':time.time()})
        for connection in records.get('site_connections', []):
            payload = json.loads(connection['payload'])
            if payload.get('providerContextId'):
                conn.execute(text('INSERT INTO browser_provider_cleanup(id,owner_id,context_id,session_id,created_at) VALUES(:id,:owner,:context,NULL,:now)'),
                             {'id': uuid4().hex, 'owner': owner, 'context': payload['providerContextId'], 'now': time.time()})
        for session in records.get('browser_session_leases', []):
            if session['status'] in {'active','login'}:
                conn.execute(text('INSERT INTO browser_provider_cleanup(id,owner_id,context_id,session_id,created_at) VALUES(:id,:owner,NULL,:session,:now)'),
                             {'id': uuid4().hex, 'owner': owner, 'session': session['provider_session'], 'now': time.time()})
        for checkpoint in records.get('identity_imports', []):
            if checkpoint['status'] == 'copying':
                objects.extend(json.loads(checkpoint['objects']))
        for item in objects:
            conn.execute(text('INSERT INTO identity_object_cleanup(id,owner_id,kind,recording_id,object_key) VALUES(:id,:owner_id,:kind,:recording_id,:object_key)'), {'id': uuid4().hex, **item})
        for table in reversed(metadata.sorted_tables):
            if table.name in {'identity_accounts', 'identity_object_cleanup', 'browser_provider_cleanup','agent_sandbox_cleanup'}:
                continue
            for row in records[table.name]:
                # Shared immutable legacy graph records remain for their other owner.
                if table.name in {'graph_versions', 'topic_scopes', 'graph_jobs'}:
                    others = conn.execute(text('SELECT 1 FROM identity_resources WHERE kind=:kind AND id=:id AND owner_id<>:owner'), {'kind': table.name, 'id': row['id'], 'owner': owner}).first()
                    if others:
                        continue
                keys = [key == row[key.name] for key in table.primary_key]
                if keys:
                    conn.execute(table.delete().where(and_(*keys)))
        return {'status': 'access_revoked', 'objectCleanup': 'queued', 'ownerId': owner}
