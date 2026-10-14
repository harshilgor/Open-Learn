"""Canonical evidence references without inventing unavailable legacy run IDs."""
from sqlalchemy import text,bindparam


def enrich_manifest(conn,owner,recording,manifest):
    if not manifest:return manifest
    refs=manifest.get('segments',[])+manifest.get('contextSegments',[])
    ids=list(dict.fromkeys(ref['segmentId'] for ref in refs))
    provenance={}
    for offset in range(0,len(ids),200):
        rows=conn.execute(text('SELECT s.id,p.run_id,p.epoch FROM lecture_transcript_segments s LEFT JOIN class_audio_sources p ON p.chunk_id=s.chunk_id AND p.owner_id=:owner WHERE s.recording_id=:recording AND s.id IN :ids').bindparams(bindparam('ids',expanding=True)),{'owner':owner,'recording':recording,'ids':ids[offset:offset+200]}).mappings()
        provenance.update({row['id']:dict(row) for row in rows})
    def reference(ref):
        source=provenance.get(ref['segmentId'],{})
        return {**ref,'runId':source.get('run_id'),'captureEpoch':source.get('epoch'),'sourceKind':'recorded_audio'}
    return {**manifest,'segments':[reference(ref) for ref in manifest.get('segments',[])],'contextSegments':[reference(ref) for ref in manifest.get('contextSegments',[])]}
