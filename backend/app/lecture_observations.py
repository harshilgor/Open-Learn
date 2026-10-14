"""Inspectible timestamped claims and append-only transcript edits."""
import json
import time
from uuid import uuid4
from sqlalchemy import text
from .lecture_service import LectureService, LectureError
from .identity import assert_owner_active

class LectureObservationService:
    def __init__(self, store): self.store = store; self.lectures = LectureService(store)

    def correct_transcript(self, owner, recording, segment_id, wording, revision, speaker_role=None):
        if not wording.strip() or len(wording) > 4000: raise LectureError('invalid_transcript_edit', 'Enter up to 4000 characters.')
        if speaker_role is not None and speaker_role not in {'professor','student','unknown'}:raise LectureError('invalid_speaker','Choose professor, student or unknown.')
        with self.store.transaction() as conn:
            assert_owner_active(conn, owner)
            self.lectures._row(owner, recording, conn)
            segment = conn.execute(text('SELECT * FROM lecture_transcript_segments WHERE recording_id=:recording AND id=:id'), {'recording': recording, 'id': segment_id}).mappings().first()
            if not segment: raise LectureError('segment_not_found', 'Transcript segment unavailable.', 404)
            if segment['normalization_version'] != revision: raise LectureError('transcript_revision_conflict', 'This transcript changed. Refresh before editing.', 409)
            historical = {'segmentId': segment_id, 'previousWording': segment['normalized_text'], 'rawText': segment['raw_text'], 'wording': wording.strip(), 'startMs': segment['start_ms'], 'endMs': segment['end_ms'], 'previousRevision': revision, 'source': 'student_correction'}
            historical.update(previousSpeakerRole=segment['speaker'],speakerRole=speaker_role or segment['speaker'])
            conn.execute(text('INSERT INTO lecture_transcript_revisions(owner_id,id,recording_id,revision,payload,created_at) VALUES(:owner,:id,:recording,:revision,:payload,:now)'), {'owner': owner, 'id': uuid4().hex, 'recording': recording, 'revision': revision+1, 'payload': json.dumps(historical), 'now': time.time()})
            conn.execute(text('UPDATE lecture_transcript_segments SET normalized_text=:wording,speaker=:speaker,normalization_version=normalization_version+1 WHERE id=:id AND normalization_version=:revision'), {'wording': wording.strip(),'speaker':speaker_role or segment['speaker'],'id': segment_id, 'revision': revision})
            from .flashcards.class_adapter import invalidate_source
            invalidate_source(self.store,conn,owner,segment_id)
            from .class_buddy import ClassBuddyService
            ClassBuddyService.invalidate_source(conn, owner, segment_id)
            from .class_document import ClassDocumentService
            ClassDocumentService.invalidate_source(conn, owner, recording, segment_id)
            from .in_class_service import handoff
            handoff(conn,owner,recording,'correction:'+segment_id+':'+str(revision+1))
            from .class_live_notes import ClassLiveNoteService
            ClassLiveNoteService.emit_reconcile(conn,owner,recording,segment['start_ms'],segment['end_ms'],
                'correction:'+segment_id+':'+str(revision+1))
            sections = conn.execute(text('SELECT id,evidence_json FROM lecture_sections WHERE recording_id=:recording'), {'recording': recording}).all()
            affected = [s[0] for s in sections if any(e['segmentId'] == segment_id for e in json.loads(s[1]))]
            for section in affected:
                conn.execute(text("UPDATE lecture_sections SET analysis_status='pending',analysis_version=analysis_version+1 WHERE id=:id"), {'id': section})
                entities = conn.execute(text('SELECT id,analysis_version FROM lecture_entities WHERE section_id=:id'), {'id': section}).all()
                from .evidence_ledger import EvidenceLedger, event_id
                from .decision_store import DecisionStore, Invalidation
                from .shared_contracts import RevisionRef
                from datetime import datetime, timezone
                for entity in entities:
                    original_event = event_id(owner, 'lecture-coverage:'+entity[0])
                    if conn.execute(text('SELECT 1 FROM learning_event_ledger WHERE owner_id=:owner AND id=:id'), {'owner':owner,'id':original_event}).first():
                        EvidenceLedger(self.store).emit(conn,owner,f'lecture-correction:{segment_id}:{revision+1}:{entity[0]}','SOURCE_CORRECTED',target_event_id=original_event,admission='excluded',exclusion_reasons=('transcript_corrected',),detail='Transcript support changed; reprocess the covered observation.')
                    DecisionStore.invalidate(conn,owner,Invalidation(owner_id=owner,id=f'lecture_invalidated_{uuid4().hex}',dependency=RevisionRef(kind='lecture_entity',id=entity[0],revision=entity[1]),reason='transcript_corrected',created_at=datetime.now(timezone.utc)))
                conn.execute(text("UPDATE lecture_entities SET verification_status='superseded' WHERE section_id=:id"), {'id': section})
                self.lectures.jobs.enqueue(owner, recording, 'lecture_section', {'recording_id': recording, 'section_id': section}, f'lecture:correction:{segment_id}:{revision+1}:{section}', connection=conn)
            return {'segmentId': segment_id, 'revision': revision+1, 'wording':wording.strip(),'speakerRole':speaker_role or segment['speaker'],'affectedSections': affected, 'rawTranscriptPreserved': True}

    def undo_transcript(self,owner,recording,segment_id,revision):
        with self.store.engine.connect() as conn:
            self.lectures._row(owner,recording,conn)
            predicate="json_extract(payload,'$.segmentId')=:segment" if conn.dialect.name=='sqlite' else "payload::jsonb->>'segmentId'=:segment"
            prior=conn.execute(text('SELECT payload FROM lecture_transcript_revisions WHERE owner_id=:owner AND recording_id=:recording AND revision=:revision AND '+predicate+' ORDER BY created_at DESC LIMIT 1'),{'owner':owner,'recording':recording,'revision':revision,'segment':segment_id}).scalar_one_or_none()
        if not prior:raise LectureError('transcript_undo_unavailable','No correction is available to undo.',409)
        data=json.loads(prior)
        return self.correct_transcript(owner,recording,segment_id,data['previousWording'],revision,data.get('previousSpeakerRole'))

    def observe(self, owner, recording, command):
        with self.store.transaction() as conn:
            assert_owner_active(conn, owner)
            self.lectures._row(owner, recording, conn)
            segments = conn.execute(text('SELECT id,start_ms,end_ms,normalized_text,raw_text,normalization_version FROM lecture_transcript_segments WHERE recording_id=:recording'), {'recording': recording}).mappings().all()
            selected = [s for s in segments if s['id'] in command['segmentIds']]
            if len(selected) != len(set(command['segmentIds'])): raise LectureError('invalid_evidence', 'Observation cites unavailable transcript.')
            quote = command['quote']
            if not any(quote.casefold() in (s['normalized_text'] or s['raw_text']).casefold() for s in selected): raise LectureError('unsupported_quote', 'The quoted support is not in the transcript.')
            payload = dict(command, coverageOnly=True, learnerMisconception=False, evidence=[{'segmentId': s['id'], 'revision': s['normalization_version'], 'startMs': s['start_ms'], 'endMs': s['end_ms']} for s in selected])
            identifier = command.get('id') or uuid4().hex
            old = conn.execute(text('SELECT payload FROM lecture_observations WHERE owner_id=:owner AND id=:id'), {'owner': owner, 'id': identifier}).scalar_one_or_none()
            if old:
                if json.loads(old) != payload: raise LectureError('observation_conflict', 'Observation ID already contains another claim.', 409)
                return dict(payload, id=identifier)
            conn.execute(text('INSERT INTO lecture_observations(owner_id,id,recording_id,revision,payload,created_at) VALUES(:owner,:id,:recording,1,:payload,:now)'), {'owner': owner, 'id': identifier, 'recording': recording, 'payload': json.dumps(payload), 'now': time.time()})
            return dict(payload, id=identifier)

    def listing(self, owner, recording):
        self.lectures._row(owner, recording)
        with self.store.engine.connect() as conn:
            rows = conn.execute(text('SELECT id,payload FROM lecture_observations WHERE owner_id=:owner AND recording_id=:recording ORDER BY created_at'), {'owner': owner, 'recording': recording}).all()
            return [dict(json.loads(row[1]), id=row[0]) for row in rows]
