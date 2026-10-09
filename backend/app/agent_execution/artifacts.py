"""Tracked prepare -> object write -> fenced publish; immutable retries."""
import hashlib
import json
import re
import time
from sqlalchemy import text
from ..browser_assistant.evidence import evidence_objects
from ..identity import assert_owner_active, fail
from ..workflow_store import uid, encoded
from .tools import validate_output


class Artifacts:
    def __init__(self, store): self.store=store;self.objects=evidence_objects(store)

    @staticmethod
    def validate_connection(conn, owner, lineage, *, lock=False):
        connection_id=lineage.get('connectionId') if isinstance(lineage,dict) else None
        if not connection_id:return
        capability=lineage.get('connectionCapability') or 'calendar_read'
        suffix=' FOR UPDATE' if lock and conn.dialect.name=='postgresql' else ''
        row=conn.execute(text('SELECT status,payload FROM agent_app_connections WHERE id=:id AND owner_id=:owner'+suffix),
                         {'id':connection_id,'owner':owner}).first()
        if not row or row[0]!='connected':
            raise ValueError('The connected account was revoked before this result could be used.')
        try:capabilities=json.loads(row[1]).get('capabilities',[])
        except (TypeError,ValueError):capabilities=[]
        if capability not in capabilities:
            raise ValueError('The connected account no longer grants this result’s required permission.')

    def prepare(self, conn, run, operation, outputs):
        manifests=[]
        if not 1<=len(outputs)<=10: raise ValueError('One to ten outputs required.')
        for output in outputs:
            validate_output(output)
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',output['name']): raise ValueError('Invalid output filename.')
            sha=hashlib.sha256(output['content']).hexdigest()
            existing=conn.execute(text('SELECT * FROM agent_artifacts WHERE operation_id=:op AND name=:name'),{'op':operation['id'],'name':output['name']}).mappings().first()
            if existing:
                if existing['sha256']!=sha: raise ValueError('Immutable output changed on retry.')
                manifests.append({**json.loads(existing['payload']),**dict(existing)});continue
            identifier=uid('artifact');key=identifier
            payload={'id':identifier,'taskId':run['id'],'name':output['name'],'mediaType':output['mediaType'],'size':len(output['content']),'lineage':output.get('lineage',{}),'inputRevision':run['desired_input_revision']}
            conn.execute(text('INSERT INTO agent_artifacts(id,owner_id,run_id,operation_id,name,object_key,sha256,status,payload,created_at) VALUES(:id,:owner,:run,:op,:name,:key,:sha,\'prepared\',:payload,:now)'),{'id':identifier,'owner':run['owner_id'],'run':run['id'],'op':operation['id'],'name':output['name'],'key':key,'sha':sha,'payload':encoded(payload),'now':time.time()})
            manifests.append({**payload,'owner_id':run['owner_id'],'object_key':key,'sha256':sha})
        return manifests

    def store_outputs(self, manifests, outputs):
        by_name={output['name']:output for output in outputs}
        for manifest in manifests:
            content=by_name[manifest['name']]['content']
            digest=self.objects.put(manifest['owner_id'],manifest['object_key'],content)
            if digest!=manifest['sha256']: raise ValueError('Stored output hash mismatch.')
            if hashlib.sha256(self.objects.read(manifest['owner_id'],manifest['object_key'])).hexdigest()!=digest: raise ValueError('Object read-back failed.')

    def publish(self, conn, run, operation, manifests):
        result=[]
        for manifest in manifests:
            self.validate_connection(conn,run['owner_id'],manifest.get('lineage',{}),lock=True)
            from .sandbox_inputs import validate_material
            validate_material(self.store,run['owner_id'],manifest.get('lineage',{}),conn)
            source_ids=manifest.get('lineage',{}).get('sourceIds',[])
            if source_ids:
                from sqlalchemy import bindparam
                suffix=' FOR UPDATE' if conn.dialect.name=='postgresql' else ''
                query=text('SELECT id,deleted_at,content_expires_at FROM agent_research_sources WHERE owner_id=:owner AND id IN :ids'+suffix).bindparams(bindparam('ids',expanding=True))
                sources=conn.execute(query,{'owner':run['owner_id'],'ids':source_ids}).mappings().all()
                if len(sources)!=len(set(source_ids)) or any(s['deleted_at'] is not None or s['content_expires_at']<=time.time() for s in sources):
                    raise ValueError('Output source expired or was deleted before publication.')
            changed=conn.execute(text("UPDATE agent_artifacts SET status='published' WHERE id=:id AND owner_id=:owner AND operation_id=:op AND status IN ('prepared','published')"),{'id':manifest['id'],'owner':run['owner_id'],'op':operation['id']})
            if changed.rowcount!=1:raise ValueError('Output source or artifact was invalidated before publication.')
            result.append({k:manifest[k] for k in ('id','taskId','name','mediaType','size','lineage','inputRevision')})
        return result

    def read(self, owner, identifier):
        with self.store.engine.connect() as conn:
            assert_owner_active(conn,owner)
            row=conn.execute(text("SELECT * FROM agent_artifacts WHERE id=:id AND owner_id=:owner AND status='published'"),{'id':identifier,'owner':owner}).mappings().first()
            if not row: fail('not_found','Artifact unavailable.',404)
            return {**json.loads(row['payload']),**dict(row)}

    def download(self, owner, identifier):
        record=self.read(owner,identifier)
        with self.store.engine.connect() as conn:
            self.validate_connection(conn,owner,record.get('lineage',{}))
        from .sandbox_inputs import validate_material
        validate_material(self.store,owner,record.get('lineage',{}))
        if record.get('lineage',{}).get('sourceIds'):
            from .research import validate_artifact_sources
            from .research_contracts import ResearchUnavailable
            try: validate_artifact_sources(self.store,owner,record)
            except ResearchUnavailable as exc: fail(exc.code,'Research source content is no longer available.',410)
        content=self.objects.read(owner,record['object_key'])
        if hashlib.sha256(content).hexdigest()!=record['sha256']: fail('artifact_invalid','Stored output integrity failed.',503)
        return record,content

    def cleanup(self, conn, owner, run_id):
        # Tombstone unreferenced prepared objects; actual deletion is retried by
        # the worker, never inside this database transaction.
        conn.execute(text("UPDATE agent_artifacts SET status='cleanup_pending' WHERE owner_id=:owner AND run_id=:run AND status IN ('prepared','cleanup_pending','deleted')"),{'owner':owner,'run':run_id})
