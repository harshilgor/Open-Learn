"""Shared authorized context selection with immutable manifests and commit fences."""
from __future__ import annotations
import hashlib, json, re, time
from uuid import uuid4
from sqlalchemy import text
from .identity import assert_owner_active, fail
from .source_memory import SourceMemory

class ContextCompiler:
    def __init__(self,store): self.store=store

    @staticmethod
    def tokens(value):
        # Conservative UTF-8 bound, configurable provider tokenizer can replace it.
        return max(1,len(value.encode('utf-8')))

    def compile(self,owner,session_id,purpose,request,*,required_source_ids=(),token_budget=12000,quiz_scope=None,course_id=None,target_concept_ids=(),reserve_output_tokens=2000,expected_revisions=None):
        if purpose not in {'teaching','assessment','readiness','planning'}: fail('invalid_context_purpose','Unknown context purpose.',422)
        if token_budget<1 or reserve_output_tokens<0: fail('invalid_context_budget','Token budget must be positive.',422)
        if session_id:
            from .material_service import MaterialService
            session=MaterialService(self.store).session(owner,session_id)
            course_id=course_id or (session.get('course_id') if isinstance(session,dict) else getattr(session,'course_id',None))
        budget=max(0,token_budget-reserve_output_tokens-512)
        target_concept_ids=target_concept_ids or tuple((quiz_scope or {}).get('conceptIds',()))
        with self.store.transaction() as conn:
            assert_owner_active(conn,owner)
            if course_id and not conn.execute(text('SELECT 1 FROM courses WHERE owner_id=:owner AND id=:course AND archived_at IS NULL'),{'owner':owner,'course':course_id}).first(): fail('course_not_found','The selected course is unavailable.',404)
            from .unified_learner_state import UnifiedLearnerState
            state=UnifiedLearnerState(self.store).read(conn,owner)
            if target_concept_ids: state['states']=[s for s in state['states'] if s['conceptId'] in target_concept_ids]
            elif course_id:
                course_concepts=set(conn.execute(text('SELECT concept_id FROM course_concept_mappings WHERE owner_id=:owner AND course_id=:course'),{'owner':owner,'course':course_id}).scalars())
                state['states']=[s for s in state['states'] if s['conceptId'] in course_concepts]
            watermark=conn.execute(text('SELECT sequence FROM learning_event_sequences WHERE owner_id=:owner'),{'owner':owner}).scalar_one_or_none() or 0
            prefs=conn.execute(text('SELECT revision,payload FROM identity_preferences WHERE owner_id=:owner'),{'owner':owner}).mappings().first()
            academic=[]
            for row in conn.execute(text('SELECT id,revision,payload FROM academic_entities WHERE owner_id=:owner AND (:course IS NULL OR course_id=:course)'),{'owner':owner,'course':course_id}).mappings():
                academic.append({'id':row['id'],'revision':row['revision'],'value':json.loads(row['payload'])})
            structured={'task':request,'purpose':purpose,'scope':quiz_scope,'learner':state,'academic':academic,'preferences':json.loads(prefs['payload']) if prefs else {}}
            targets=set(target_concept_ids)
            prerequisites=[]
            relations=[dict(row) for row in conn.execute(text("SELECT from_id,to_id,payload FROM stable_concept_relations WHERE owner_id=:owner AND kind='prerequisite' AND review_state='reviewed'"),{'owner':owner}).mappings()]
            frontier=targets
            seen=set(targets)
            for _ in range(3):
                admitted=[edge for edge in relations if edge['to_id'] in frontier and edge['from_id'] not in seen]
                prerequisites.extend(json.loads(edge['payload']) for edge in admitted)
                frontier={edge['from_id'] for edge in admitted};seen|=frontier
                if not frontier or len(prerequisites)>=20: break
            structured['reviewedPrerequisites']=prerequisites[:20]
            remembered=[]
            for row in conn.execute(text('SELECT id,kind,payload FROM memory_derived WHERE owner_id=:owner AND valid=true'),{'owner':owner}).mappings():
                value=json.loads(row['payload']); scope=value.get('scope')
                if scope not in (None,course_id,{'courseId':course_id}): continue
                if row['kind']=='preference' and not value.get('explicit'): continue
                remembered.append({'id':row['id'],'kind':row['kind'],**value})
            structured['remembered']=remembered
            continuity=None
            if session_id and purpose!='teaching':
                continuity=conn.execute(text("SELECT id,sequence,payload FROM context_records WHERE owner_id=:owner AND session_id=:session AND kind='conversation_state'"),{'owner':owner,'session':session_id}).mappings().first()
                if continuity: structured['conversationContinuity']={'state':json.loads(continuity['payload']),'isExactEvidence':False}
            structured_text=json.dumps(structured,ensure_ascii=False)
            cost=self.tokens(structured_text)
            warnings=[]; omissions=[]; included=[]; dependencies=[{'kind':'learner_projection','record_id':owner,'revision':state['eventWatermark']}] if state['eventWatermark'] else []
            dependencies.extend({'kind':'academic_entity','record_id':a['id'],'revision':a['revision']} for a in academic)
            dependencies.extend({'kind':'derived_memory','record_id':a['id'],'revision':1} for a in remembered)
            graph_revision=conn.execute(text('SELECT revision FROM concept_graph_revisions WHERE owner_id=:owner'),{'owner':owner}).scalar_one_or_none()
            if graph_revision: dependencies.append({'kind':'concept_graph','record_id':owner,'revision':graph_revision})
            if continuity and continuity['sequence']>0: dependencies.append({'kind':'conversation_state','record_id':continuity['id'],'revision':continuity['sequence']})
            if state['eventWatermark']<watermark: warnings.append('learner_projection_lag')
            if session_id and purpose=='teaching': warnings.append('conversation_continuity_owned_by_journey_snapshot')
            if course_id is None: warnings.append('course_scope_unspecified')
            if expected_revisions and expected_revisions.get('eventWatermark',watermark)!=watermark: fail('context_revision_conflict','Learning evidence changed; refresh context.',409)
            candidates=SourceMemory(self.store).retrieve(conn,owner,request,course_id,required_source_ids)
            candidates+=self.legacy_sources(conn,owner,course_id,request,required_source_ids)
            required=set(required_source_ids); available={c['sourceId'] for c in candidates}
            status='ready'
            if required-available: status='insufficient_context'; omissions.extend({'id':s,'reason':'required_source_unavailable'} for s in sorted(required-available))
            if cost>budget: status='insufficient_context'; omissions.append({'id':'structured_state','reason':'required_context_exceeds_budget'})
            # Round robin across sources retains primary-source diversity.
            groups={}
            for c in candidates: groups.setdefault(c['sourceId'],[]).append(c)
            ordered=[]
            while groups:
                for sid in list(groups):
                    ordered.append(groups[sid].pop(0))
                    if not groups[sid]: del groups[sid]
            ordered.sort(key=lambda c:not c.get('required',False))
            seen=set()
            for candidate in ordered:
                origin=(candidate['sourceId'],candidate['originId'])
                if origin in seen: continue
                seen.add(origin)
                amount=self.tokens(candidate['text'])+48
                if cost+amount>budget:
                    omissions.append({'id':candidate['originId'],'reason':'input_budget'})
                    if candidate.get('required'): status='insufficient_context'
                    continue
                cost+=amount; included.append(candidate)
                dep=candidate.get('dependency') or {'kind':'source_revision','record_id':candidate['sourceId'],'revision':candidate['revision']}
                if dep not in dependencies: dependencies.append(dep)
            academic_digest=hashlib.sha256(json.dumps(sorted([(a['id'],a['revision']) for a in academic])).encode()).hexdigest()
            packet={'id':'context_'+uuid4().hex,'ownerId':owner,'purpose':purpose,'status':status,'text':structured_text+'\n\n'+'\n\n'.join(c['text'] for c in included),'manifest':included,'dependencies':dependencies,'omissions':omissions,'warnings':warnings,'canonicalJourneyOwnership':bool(session_id and purpose=='teaching'),'watermarks':{'eventWatermark':watermark,'projectionWatermark':state['eventWatermark']},'budget':{'total':token_budget,'outputReserved':reserve_output_tokens,'protocolReserved':512,'inputUsed':cost,'inputAvailable':budget},'scope':quiz_scope,'courseId':course_id,'academicDigest':academic_digest,'preferencesRevision':prefs['revision'] if prefs else 0}
            conn.execute(text('INSERT INTO context_manifests(owner_id,id,payload,created_at) VALUES(:owner,:id,:payload,:now)'),{'owner':owner,'id':packet['id'],'payload':json.dumps(packet),'now':time.time()})
            return packet

    @staticmethod
    def legacy_sources(conn,owner,course,query,required):
        terms=set(re.findall(r'\w+',query.lower())); candidates=[]
        def add(sid,revision,content,kind,dep,metadata=None):
            sha=hashlib.sha256(content.encode()).hexdigest()
            archive_id='snapshot_'+hashlib.sha256(json.dumps([sid,revision,sha,metadata],sort_keys=True).encode()).hexdigest()
            archival={'text':content,'blocks':SourceMemory.blocks(content),'metadata':{'originalSourceId':sid,'kind':kind,'dependency':dep,'locator':metadata or {}}}
            conn.execute(text('INSERT INTO memory_revisions(owner_id,source_id,revision,sha256,payload,created_at) VALUES(:owner,:id,:revision,:sha,:payload,:now) ON CONFLICT(owner_id,source_id,revision) DO NOTHING'),{'owner':owner,'id':archive_id,'revision':revision,'sha':sha,'payload':json.dumps(archival),'now':time.time()})
            for block in SourceMemory.blocks(content):
                locator=(metadata or {}).get('segmentId') or (metadata or {}).get('blockId')
                if locator: block['originId']=locator+':'+block['originId']
                score=len(terms & set(re.findall(r'\w+',block['text'].lower())))
                if score or sid in required or kind=='lecture' and 'lecture' in terms:
                    candidates.append({**block,'sourceId':sid,'revision':revision,'kind':kind,'score':score,'required':sid in required,'dependency':dep,'historicalSnapshotId':archive_id,'metadata':metadata or {}})
        params={'owner':owner,'course':course}
        for row in conn.execute(text('SELECT id,revision,search_text,content_hash FROM workspace_notes WHERE learner_id=:owner AND (:course IS NULL OR course_id=:course)'),params).mappings():
            add(row['id'],row['revision'],row['search_text'],'note',{'kind':'workspace_note','record_id':row['id'],'revision':row['revision']})
        for row in conn.execute(text('SELECT s.*,r.generation_version FROM lecture_transcript_segments s JOIN lecture_recordings r ON r.id=s.recording_id WHERE r.learner_id=:owner AND (:course IS NULL OR r.course_id=:course)'),params).mappings():
            add(row['recording_id'],row['generation_version']+1,row['normalized_text'],'lecture',{'kind':'lecture_segment','record_id':row['id'],'revision':max(row['normalization_version'],row['transcription_version']),'sha256':hashlib.sha256(row['normalized_text'].encode()).hexdigest()},{'segmentId':row['id'],'startMs':row['start_ms'],'endMs':row['end_ms']})
        for row in conn.execute(text('SELECT b.*,v.version FROM material_blocks b JOIN material_versions v ON v.id=b.version_id JOIN materials m ON m.id=v.material_id WHERE m.owner_id=:owner AND m.deleted=false AND (:course IS NULL OR m.course_id=:course) AND v.version=(SELECT MAX(v2.version) FROM material_versions v2 WHERE v2.material_id=m.id)'),params).mappings():
            add(row['version_id'],row['version'],row['text'],'material',{'kind':'material_version','record_id':row['version_id'],'revision':row['version'],'blockId':row['id'],'sha256':hashlib.sha256(row['text'].encode()).hexdigest()},{'blockId':row['id'],'pageIndex':row['page_index']})
        return sorted(candidates,key=lambda c:-c['score'])

    def validate_commit(self,conn,owner,packet):
        assert_owner_active(conn,owner)
        if packet['ownerId']!=owner: fail('context_owner_mismatch','Context belongs to another account.',403)
        current=conn.execute(text('SELECT sequence FROM learning_event_sequences WHERE owner_id=:owner'),{'owner':owner}).scalar_one_or_none() or 0
        if current!=packet['watermarks']['eventWatermark']: fail('context_evidence_changed','Learning evidence changed during generation.',409)
        preferences_revision=conn.execute(text('SELECT revision FROM identity_preferences WHERE owner_id=:owner'),{'owner':owner}).scalar_one_or_none() or 0
        if preferences_revision!=packet.get('preferencesRevision',0): fail('context_preferences_changed','Your preferences changed during generation.',409)
        academic_rows=conn.execute(text('SELECT id,revision FROM academic_entities WHERE owner_id=:owner AND (:course IS NULL OR course_id=:course)'),{'owner':owner,'course':packet.get('courseId')}).all()
        academic_digest=hashlib.sha256(json.dumps(sorted([tuple(row) for row in academic_rows])).encode()).hexdigest()
        if academic_digest!=packet.get('academicDigest'): fail('context_academic_changed','Academic scope changed during generation.',409)
        for dep in packet['dependencies']:
            if dep['kind']=='lecture_segment':
                row=conn.execute(text('SELECT s.normalized_text,s.normalization_version,s.transcription_version FROM lecture_transcript_segments s JOIN lecture_recordings r ON r.id=s.recording_id WHERE r.learner_id=:owner AND s.id=:id'),{'owner':owner,'id':dep['record_id']}).mappings().first()
                if row is None or max(row['normalization_version'],row['transcription_version'])!=dep['revision'] or hashlib.sha256(row['normalized_text'].encode()).hexdigest()!=dep['sha256']: fail('context_source_changed','A transcript interval changed or was removed during generation.',409)
                continue
            if dep['kind']=='learner_projection':
                from .unified_learner_state import UnifiedLearnerState
                if UnifiedLearnerState(self.store).read(conn,owner)['eventWatermark']!=dep['revision']: fail('context_projection_changed','Learner projection changed during generation.',409)
                continue
            if dep['kind']=='source_revision': sql='SELECT revision FROM memory_sources WHERE owner_id=:owner AND id=:id AND deleted=false'
            elif dep['kind']=='workspace_note': sql='SELECT revision FROM workspace_notes WHERE learner_id=:owner AND id=:id'
            elif dep['kind']=='lecture_recording': sql='SELECT generation_version+1 FROM lecture_recordings WHERE learner_id=:owner AND id=:id'
            elif dep['kind']=='material_version': sql='SELECT v.version FROM material_versions v JOIN materials m ON m.id=v.material_id WHERE m.owner_id=:owner AND m.deleted=false AND v.id=:id AND v.version=(SELECT MAX(v2.version) FROM material_versions v2 WHERE v2.material_id=m.id)'
            elif dep['kind']=='academic_entity': sql='SELECT revision FROM academic_entities WHERE owner_id=:owner AND id=:id'
            elif dep['kind']=='conversation_state': sql="SELECT sequence FROM context_records WHERE owner_id=:owner AND id=:id AND kind='conversation_state'"
            elif dep['kind']=='concept_graph': sql='SELECT revision FROM concept_graph_revisions WHERE owner_id=:owner'
            elif dep['kind']=='derived_memory': sql='SELECT 1 FROM memory_derived WHERE owner_id=:owner AND id=:id AND valid=true'
            else: fail('unknown_context_dependency','Cannot verify this context dependency.',409)
            revision=conn.execute(text(sql),{'owner':owner,'id':dep['record_id']}).scalar_one_or_none()
            if revision!=dep['revision']: fail('context_source_changed','A source changed or was removed during generation.',409)
            if dep['kind']=='material_version':
                block=conn.execute(text('SELECT text FROM material_blocks WHERE id=:block AND version_id=:version'),{'block':dep['blockId'],'version':dep['record_id']}).scalar_one_or_none()
                if block is None or hashlib.sha256(block.encode()).hexdigest()!=dep['sha256']: fail('context_source_changed','Source extraction changed during generation.',409)
