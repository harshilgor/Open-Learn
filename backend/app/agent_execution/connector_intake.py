"""Drive reads enter the existing immutable material intake once per request."""
import hashlib
import json
import time
from sqlalchemy import text
from ..identity import assert_owner_active,fail
from ..workflow_store import encoded
from ..material_service import MaterialService
from ..material_models import UploadRequest
from .google_connector import GoogleConnections,GoogleAdapter
from .repository import Repository,digest

class ConnectorIntake:
    def __init__(self,store,adapter=None):self.store=store;self.repo=Repository(store);self.adapter=adapter or GoogleAdapter(GoogleConnections(store))
    def drive(self,owner,connection,source,key):
        if not key or len(key)>160:fail('invalid_input','Provide a stable intake key.',422)
        identity='intake_'+digest([owner,key])[:32];request_hash=digest([connection,source])
        metadata,content=self.adapter.download(owner,connection,source)
        content_hash=hashlib.sha256(content).hexdigest();service=MaterialService(self.store)
        with self.repo.transaction() as conn:
            assert_owner_active(conn,owner)
            saved=conn.execute(text('SELECT * FROM agent_connector_intakes WHERE id=:id AND owner_id=:owner'),{'id':identity,'owner':owner}).mappings().first()
            if saved:
                payload=json.loads(saved['payload'])
                if saved['request_hash']!=request_hash or payload['sha256']!=content_hash:fail('intake_changed','Source changed; use a new import identity.',409)
                created=payload['material']
            else:
                created=service.create(owner,UploadRequest(title=metadata['name'][:300],media_type=metadata['mimeType'],byte_count=len(content)),connection=conn)
                provenance={'provider':'google_drive','connectionId':connection,'fileId':source,'name':metadata['name'],'retrievedAt':time.time(),'sha256':content_hash,'classification':'untrusted_source','material':created}
                conn.execute(text('INSERT INTO agent_connector_intakes(id,owner_id,created_at,request_hash,payload) VALUES(:id,:owner,:now,:hash,:payload)'),{'id':identity,'owner':owner,'now':time.time(),'hash':request_hash,'payload':encoded(provenance)})
        result=service.upload(owner,created['materialId'],created['versionId'],content)
        return {'materialId':created['materialId'],'versionId':created['versionId'],'material':result,'provenance':{'connectionId':connection,'fileId':source,'sha256':content_hash,'classification':'untrusted_source'}}
