"""Owner-scoped portability using declared ownership and relational dependencies."""
import json
from sqlalchemy import MetaData, select, or_, and_, text
from .identity import assert_owner_active

PRIVATE_TABLES = {'identity_devices', 'identity_accounts'}


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
    exported['readme'] = 'Tables retain original IDs and relationships. Files contain base64 originals with SHA-256. Transcript and note text are in their source tables; derived rows are not evidence of mastery.'
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
    return items


def object_operation(store, item, delete):
    if item['kind'] == 'lecture':
        from .lecture_storage import LectureObjectStore
        objects = LectureObjectStore()
        return objects.delete(item['owner_id'], item['recording_id'], item['object_key']) if delete else objects.read(item['owner_id'], item['recording_id'], item['object_key'])
    if item['kind'] == 'material':
        from .material_service import MaterialService
        path = MaterialService(store).object_path(item['object_key'])
    elif item['kind'] == 'note':
        from .workspace_note_service import WorkspaceNoteService
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


def erase_owner(store, owner):
    from .identity_import import _profile_locks
    with _profile_locks[owner]:
        return _erase_owner(store, owner)


def _erase_owner(store, owner):
    import time
    with store.engine.begin() as conn:
        assert_owner_active(conn, owner)
        conn.execute(text("UPDATE identity_accounts SET status='deleted',deleted_at=:now,display_name='' WHERE id=:owner"), {'now': time.time(), 'owner': owner})
        conn.execute(text('UPDATE identity_devices SET revoked_at=:now WHERE owner_id=:owner'), {'now': time.time(), 'owner': owner})
        conn.execute(text("UPDATE learning_jobs SET status='cancelled',lease=NULL,expires=NULL,cancellation_requested=true WHERE owner_id=:owner"), {'owner': owner})
        metadata, records = owned_rows(conn, owner)
        from uuid import uuid4
        objects = object_manifest(records, owner)
        for checkpoint in records.get('identity_imports', []):
            if checkpoint['status'] == 'copying':
                objects.extend(json.loads(checkpoint['objects']))
        for item in objects:
            conn.execute(text('INSERT INTO identity_object_cleanup(id,owner_id,kind,recording_id,object_key) VALUES(:id,:owner_id,:kind,:recording_id,:object_key)'), {'id': uuid4().hex, **item})
        for table in reversed(metadata.sorted_tables):
            if table.name in {'identity_accounts', 'identity_object_cleanup'}:
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
