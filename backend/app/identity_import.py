"""Explicit same-installation local-profile copy with deterministic ID remapping.

The source profile remains intact. This is not a name-based profile merge or an
arbitrary SQL upload endpoint. A failed copy resumes with the same manifest.
"""
import hashlib
import json
import time
from threading import RLock
from collections import defaultdict
from uuid import uuid4, uuid5, NAMESPACE_URL
from sqlalchemy import select, and_, text
from .identity import assert_owner_active, fail
from .identity_data import owned_rows, object_manifest, object_operation

OMIT = {'learning_jobs', 'material_jobs', 'execution_outbox', 'projection_watermarks','canvas_connections'}
_profile_locks = defaultdict(RLock)


def source_snapshot(conn, profile):
    metadata, records = owned_rows(conn, profile)
    records = {name: rows for name, rows in records.items() if not name.startswith('identity_') and name not in OMIT}
    # Imported graphs need their parent scopes. Follow only non-personal parents;
    # explicit foreign-owner rows are never imported through a relationship.
    for _ in range(len(metadata.tables)):
        changed = False
        for name, rows in list(records.items()):
            table = metadata.tables[name]
            for constraint in table.foreign_key_constraints:
                target = constraint.elements[0].column.table
                if target.name not in records or any(k in target.c for k in ('owner_id', 'learner_id', 'owner_learner_id')):
                    continue
                known = {tuple(r[k.name] for k in target.primary_key) for r in records[target.name]}
                for row in list(rows):
                    clauses = [element.column == row[element.parent.name] for element in constraint.elements]
                    for parent in conn.execute(select(target).where(and_(*clauses))).mappings():
                        key = tuple(parent[k.name] for k in target.primary_key)
                        if key not in known:
                            known.add(key); records[target.name].append(parent); changed = True
        if not changed:
            break
    checksum = hashlib.sha256(json.dumps({name: [dict(row) for row in sorted(rows, key=lambda r: str(dict(r)))] for name, rows in sorted(records.items())}, sort_keys=True, default=str).encode()).hexdigest()
    return metadata, records, checksum


def inventory(store, owner, profile='local'):
    with store.engine.connect() as conn:
        _, rows, checksum = source_snapshot(conn, profile)
        old = conn.execute(text('SELECT id,status,checksum FROM identity_imports WHERE owner_id=:owner AND source_profile=:source'), {'owner': owner, 'source': profile}).mappings().first()
    return {'sourceProfile': profile, 'checksum': checksum, 'tables': {name: len(values) for name, values in rows.items() if values}, 'previousImport': dict(old) if old else None,
            'message': 'Copy this local profile into the account. The source remains intact. An existing account history is never merged automatically.'}


def import_profile(store, owner, expected_checksum, profile='local'):
    # The supported local desktop API is one process. Serialize reset/retry with
    # object publication; durable checkpoints handle process interruption.
    with _profile_locks[owner]:
        return _import_profile(store, owner, expected_checksum, profile)


def _import_profile(store, owner, expected_checksum, profile='local', *, package_snapshot=None, package_files=None):
    with store.transaction() as conn:
        assert_owner_active(conn, owner)
        metadata, rows, checksum = package_snapshot if package_snapshot is not None else source_snapshot(conn, profile)
        previous = conn.execute(text('SELECT * FROM identity_imports WHERE owner_id=:owner AND source_profile=:source'), {'owner': owner, 'source': profile}).mappings().first()
        if previous and previous['status'] == 'completed':
            return {'id': previous['id'], 'status': 'completed'}
        if checksum != expected_checksum or previous and previous['checksum'] != checksum:
            fail('profile_changed', 'The local profile changed. Refresh the inventory before importing.', 409)
        _, target = owned_rows(conn, owner)
        if any(values for name, values in target.items() if not name.startswith('identity_') and name != 'learners'):
            fail('account_not_empty', 'This account already has history. A profile merge requires an explicit conflict-resolution flow.', 409)
        import_id = previous['id'] if previous else 'import_' + uuid4().hex
        mapping = {profile: owner}
        for name, values in rows.items():
            for row in values:
                for key in ('id', 'object_key', 'storage_key'):
                    value = row.get(key)
                    if isinstance(value, str) and value != profile:
                        prefix = value.split('_')[0] if '_' in value else 'imported'
                        mapping[value] = prefix + '_' + uuid5(NAMESPACE_URL, import_id + ':' + value).hex
        for value in list(mapping):
            if value.startswith('journey_') and value[8:] in mapping:
                mapping[value] = 'journey_' + mapping[value[8:]]
        if not previous:
            objects = [{key: mapping.get(value, value) if isinstance(value, str) else value for key, value in item.items()} for item in object_manifest(rows, profile)]
            conn.execute(text("INSERT INTO identity_imports(id,owner_id,source_profile,checksum,status,mapping,objects,created_at) VALUES(:id,:owner,:source,:checksum,'copying',:mapping,:objects,:now)"), {'id': import_id, 'owner': owner, 'source': profile, 'checksum': checksum, 'mapping': json.dumps(mapping), 'objects': json.dumps(objects), 'now': time.time()})

    def remap(value):
        if isinstance(value, str):
            if value in mapping:
                return mapping[value]
            if value.startswith(('{', '[')):
                try: return json.dumps(remap(json.loads(value)), ensure_ascii=False)
                except ValueError: pass
            return value
        if isinstance(value, dict): return {key: remap(item) for key, item in value.items()}
        if isinstance(value, list): return [remap(item) for item in value]
        return value

    # Immutable publish and hash comparison make repeated copy safe after a crash.
    from .object_store import LocalObjectStore
    from .workspace_note_service import WorkspaceNoteService, parse_frontmatter, write_frontmatter
    from .lecture_storage import LectureObjectStore
    from .material_service import MaterialService
    from .class_recording_service import ClassRecordingService
    note_hashes = {}
    for source in object_manifest(rows, profile):
        data = package_files[(source['kind'],source['object_key'])] if package_files is not None else object_operation(store, source, delete=False)
        target = remap(source)
        if source['kind'] == 'note':
            frontmatter, body = parse_frontmatter(data.decode('utf-8'))
            data = write_frontmatter(remap(frontmatter), body).encode()
            note_hashes[target['object_key']] = hashlib.sha256(data).hexdigest()
            path = WorkspaceNoteService(store).note_path(owner, target['object_key'])
            objects = LocalObjectStore(path.parent)
            objects.put(path.name, data)
        elif source['kind'] == 'lecture':
            objects = LectureObjectStore().objects
            objects.put(f"{owner}/{target['recording_id']}/{target['object_key']}", data)
        else:
            path = MaterialService(store).object_path(target['object_key']) if source['kind'] == 'material' else ClassRecordingService(store)._path(owner, target['recording_id'])
            LocalObjectStore(path.parent).put(path.name, data)

    with store.transaction() as conn:
        assert_owner_active(conn, owner)
        current_checksum = checksum if package_snapshot is not None else source_snapshot(conn, profile)[2]
        if current_checksum != checksum:
            fail('profile_changed', 'Local history changed during import. Its existing data is intact.', 409)
        state = conn.execute(text('SELECT status FROM identity_imports WHERE id=:id'), {'id': import_id}).scalar_one()
        if state == 'completed':
            return {'id': import_id, 'status': state}
        for table in metadata.sorted_tables:
            for row in rows.get(table.name, []):
                values = remap(dict(row))
                if package_snapshot is not None:
                    from datetime import datetime,date
                    from sqlalchemy import DateTime,Date
                    for column in table.c:
                        value=values.get(column.name)
                        if isinstance(value,str) and isinstance(column.type,DateTime): values[column.name]=datetime.fromisoformat(value.replace('Z','+00:00'))
                        elif isinstance(value,str) and isinstance(column.type,Date): values[column.name]=date.fromisoformat(value)
                if table.name == 'workspace_notes':
                    values['relative_path'] = values['id'] + '.md'
                    values['content_hash'] = note_hashes[values['id']]
                if table.name == 'learners':
                    if conn.execute(select(table).where(table.c.id == owner)).first():
                        continue
                    values['identity_kind'] = 'verified_account'
                conn.execute(table.insert().values(**values))
        from .identity import grant_resource
        for name in ('graph_versions', 'graph_jobs', 'topic_scopes'):
            for row in rows.get(name, []):
                grant_resource(conn, name, mapping[row['id']], owner)
        conn.execute(text("UPDATE identity_imports SET status='completed' WHERE id=:id"), {'id': import_id})
    return {'id': import_id, 'status': 'completed', 'sourcePreserved': True, 'mappingCount': len(mapping)}


def import_package(store, owner, package, expected_checksum):
    """Explicit portable copy. Only declared data tables and source-owned rows qualify.

    Never import auth grants, account tombstones, executable jobs, or SQL. IDs
    are remapped by the same durable checkpoint as same-installation copying.
    """
    import base64
    from sqlalchemy import MetaData
    raw=json.dumps(package,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    checksum=hashlib.sha256(raw).hexdigest()
    if checksum!=expected_checksum: fail('package_changed','The reviewed package checksum does not match.',409)
    if len(raw)>100_000_000: fail('package_too_large','Portable packages are limited to 100 MB.',413)
    if package.get('format')!='openlearn-account-export' or package.get('version')!=1: fail('invalid_package','Unsupported account package.',422)
    profile=package.get('ownerId')
    if not isinstance(profile,str) or not profile: fail('invalid_package','The source profile is missing.',422)
    metadata=MetaData(); metadata.reflect(bind=store.engine)
    rows={name:[] for name in metadata.tables}
    supplied=package.get('tables',{})
    forbidden=OMIT|{'schema_migrations','alembic_version','context_manifests','canvas_connections'}
    for name,values in supplied.items():
        if name.startswith('identity_') or name in forbidden: continue
        table=metadata.tables.get(name)
        if table is None: fail('invalid_package_table','Package contains an unknown data table.',422)
        if not isinstance(values,list): fail('invalid_package','Table records must be arrays.',422)
        for row in values:
            if not isinstance(row,dict) or set(row)-set(table.c.keys()): fail('invalid_package','Invalid record columns.',422)
            for key in ('owner_id','learner_id','owner_learner_id'):
                if key in table.c and row.get(key)!=profile: fail('package_owner_mismatch','Package contains foreign account data.',403)
            if name=='learners' and row.get('id')!=profile: fail('package_owner_mismatch','Foreign learner record.',403)
        rows[name]=values
    # Ownerless child rows must connect to an imported parent. This also blocks
    # submitting unrelated global records that would otherwise be trusted.
    for name,values in rows.items():
        table=metadata.tables[name]
        if not values or any(k in table.c for k in ('owner_id','learner_id','owner_learner_id')) or name=='learners': continue
        for row in values:
            linked=False
            for constraint in table.foreign_key_constraints:
                if constraint.elements:
                    parent=constraint.elements[0].column.table.name
                    linked |= any(all(row.get(e.parent.name)==p.get(e.column.name) for e in constraint.elements) for p in rows.get(parent,[]))
            # Legacy graph roots are accepted only when explicitly referenced
            # by imported account-owned rows, never from the name alone.
            for child_name,child_rows in rows.items():
                for constraint in metadata.tables[child_name].foreign_key_constraints:
                    if constraint.elements and constraint.elements[0].column.table.name==name:
                        linked |= any(all(c.get(e.parent.name)==row.get(e.column.name) for e in constraint.elements) for c in child_rows)
            if not linked: fail('unowned_package_record','An imported record has no account-owned relationship.',422)
    files={}
    for item in package.get('files',[]):
        if item.get('status')=='missing': fail('missing_package_file','The package is missing an original source file.',422)
        try: data=base64.b64decode(item['content'],validate=True)
        except (KeyError,ValueError): fail('invalid_package_file','Invalid source file encoding.',422)
        if hashlib.sha256(data).hexdigest()!=item.get('sha256'): fail('package_file_corrupt','Source file checksum mismatch.',422)
        files[(item['kind'],item['object_key'])]=data
    for item in object_manifest(rows,profile):
        if (item['kind'],item['object_key']) not in files: fail('missing_package_file','A required source file is absent.',422)
    with _profile_locks[owner]:
        return _import_profile(store,owner,checksum,profile,package_snapshot=(metadata,rows,checksum),package_files=files)


def reset_import(store, owner):
    with _profile_locks[owner]:
        return _reset_import(store, owner)


def _reset_import(store, owner):
    with store.transaction() as conn:
        row = conn.execute(text("SELECT * FROM identity_imports WHERE owner_id=:owner AND status='copying'"), {'owner': owner}).mappings().first()
        if row:
            for item in json.loads(row['objects']):
                conn.execute(text('INSERT INTO identity_object_cleanup(id,owner_id,kind,recording_id,object_key) VALUES(:id,:owner_id,:kind,:recording_id,:object_key)'), {'id': uuid4().hex, **item})
            conn.execute(text('DELETE FROM identity_imports WHERE id=:id'), {'id': row['id']})
    return {'status': 'reset', 'sourcePreserved': True}
