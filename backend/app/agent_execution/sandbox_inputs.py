"""Explicit, immutable owner-scoped CSV intake and source erasure fences."""
import hashlib
import json
from sqlalchemy import text,inspect
from ..material_service import MaterialService
from ..identity import fail
from ..workflow_store import encoded
from .tools import parse_csv


def material_csv(store,owner,session_id,version_id,conn=None):
    materials=MaterialService(store);session=materials.session(owner,session_id)
    version=materials.version(owner,version_id,conn)
    if version['role'] in {'answer_key','sample_paper'}:fail('source_scope_denied','Assessment sources cannot enter a sandbox.',403)
    if version['media_type'] not in {'text/plain','text/markdown','text/csv'}:fail('unsupported_file','Sandbox lab accepts UTF-8 CSV text only.',422)
    if version['byte_count']>50000 or not version['sha256']:fail('unsupported_file','Upload a CSV of at most 50000 bytes first.',422)
    if version.get('course_id') and session.course_id and version['course_id']!=session.course_id:fail('source_scope_denied','Select a source from this course.',403)
    content=materials.objects.read(version['object_key'])
    if len(content)>50000 or hashlib.sha256(content).hexdigest()!=version['sha256']:fail('source_changed','The material bytes changed.',409)
    value=content.decode('utf-8-sig');parse_csv(value)
    return value,{'versionId':version_id,'sha256':version['sha256'],'title':version['title'],'mediaType':version['media_type']}


def validate_material(store,owner,lineage,conn=None):
    source=lineage.get('inputMaterial')
    if not source:return
    version=MaterialService(store).version(owner,source['versionId'],conn)
    if version['sha256']!=source['sha256'] or version['role'] in {'answer_key','sample_paper'}:fail('source_changed','The sandbox source is no longer available.',409)


def erase_versions(conn,owner,version_ids):
    if not inspect(conn).has_table('agent_sandbox_leases'):return
    rows=conn.execute(text("SELECT id,payload FROM assistant_runs WHERE owner_id=:owner AND runtime_owner='agent_v2'"),{'owner':owner}).mappings().all()
    for row in rows:
        run=json.loads(row['payload'])
        if (run.get('inputMaterial') or {}).get('versionId') not in version_ids:continue
        run['csvText']=None;run['inputSourceDeleted']=True
        conn.execute(text('UPDATE assistant_runs SET payload=:payload WHERE id=:id AND owner_id=:owner'),{'id':row['id'],'owner':owner,'payload':encoded(run)})
        conn.execute(text("UPDATE agent_artifacts SET status='cleanup_pending' WHERE owner_id=:owner AND run_id=:run AND status<>'deleted'"),{'owner':owner,'run':row['id']})
        conn.execute(text('UPDATE agent_sandbox_leases SET expires_at=0 WHERE owner_id=:owner AND run_id=:run'),{'owner':owner,'run':row['id']})
