"""Durable asynchronous verification of contiguous class-audio windows.

Every external submission is fenced by a committed `submitting` state. A crash
in that state requires reconciliation, never another blind paid submission.
"""
import hashlib
import json
import time

from sqlalchemy import text

from .assemblyai_transcription import AssemblyAITranscriptionAdapter
from .class_audio_windows import assemble_window
from .lecture_provider import TranscriptionFailure
from .lecture_service import LectureService
from .workflow_store import WorkflowStore, encoded


class ClassVerificationService:
    def __init__(self, store, adapter_factory=AssemblyAITranscriptionAdapter, assembler=assemble_window):
        self.store, self.factory, self.assembler = store, adapter_factory, assembler
        self.jobs = WorkflowStore(store)

    def configured(self, owner, recording_id):
        with self.store.engine.connect() as conn:
            payload = conn.execute(text('SELECT payload FROM class_sessions WHERE owner_id=:owner AND recording_id=:recording'), {'owner': owner, 'recording': recording_id}).scalar_one_or_none()
        return json.loads(payload).get('speech', {}).get('verificationProvider') == 'assemblyai' if payload else False

    def plan(self, owner, recording_id):
        with self.store.transaction() as conn:
            raw = conn.execute(text('SELECT id,payload FROM class_sessions WHERE owner_id=:owner AND recording_id=:recording'), {'owner': owner, 'recording': recording_id}).mappings().one()
            item = json.loads(raw['payload'])
            target_ms=90000 if item.get('policy',{}).get('speechQuality')=='economical' else 30000
            recording = LectureService(self.store)._row(owner, recording_id, conn)
            last = conn.execute(text('SELECT payload FROM class_verification_requests WHERE owner_id=:owner AND class_id=:class ORDER BY created_at DESC,id DESC LIMIT 1'), {'owner': owner, 'class': raw['id']}).scalar_one_or_none()
            after = json.loads(last)['endSequence'] if last else -1
            rows = conn.execute(text('SELECT * FROM lecture_audio_chunks WHERE recording_id=:recording AND sequence_number>:after ORDER BY sequence_number LIMIT 30'), {'recording': recording_id, 'after': after}).mappings().all()
            values = []
            sequence = after + 1
            for row in rows:
                if row['sequence_number'] != sequence or row['transcription_status'] == 'completed':
                    break
                if values and (row['start_ms'] - values[-1]['end_ms'] > 1200 or row['end_ms'] - values[0]['start_ms'] > 90000):
                    break
                values.append(dict(row)); sequence += 1
                if row['end_ms'] - values[0]['start_ms'] >= target_ms:
                    break
            if not values:
                return {'scheduled': False}
            complete_capture = recording['expected_chunk_count'] is not None
            duration = values[-1]['end_ms'] - values[0]['start_ms']
            next_row = next((row for row in rows if row['sequence_number'] == sequence), None)
            silence_boundary = bool(next_row and next_row['start_ms'] - values[-1]['end_ms'] > 1200)
            if duration < target_ms and not complete_capture and not silence_boundary:
                return {'scheduled': False, 'buffering': True}
            digest = hashlib.sha256(encoded([raw['id'], [(c['id'], c['sha256']) for c in values]]).encode()).hexdigest()[:32]
            identifier = 'verify_' + digest
            payload = {'id': identifier, 'chunks': [{key: row[key] for key in ('id', 'sequence_number', 'start_ms', 'end_ms', 'storage_key', 'sha256')} for row in values],
                       'startMs': values[0]['start_ms'], 'endMs': values[-1]['end_ms'], 'endSequence': values[-1]['sequence_number'],
                       'model': item['speech']['verificationModel'], 'region': item['speech'].get('region', 'us'), 'pollCount': 0,
                       'speakerLabels': item['speech'].get('speakerLabels', False)}
            from .lecture_pipeline import _course_vocabulary
            payload['keyterms'] = [term.strip()[:50] for term in _course_vocabulary(self.store, owner, item.get('courseId')).split(',') if term.strip()][:100]
            now = time.time()
            conn.execute(text('INSERT INTO class_verification_requests(id,owner_id,class_id,recording_id,state,created_at,updated_at,payload) VALUES(:id,:owner,:class,:recording,\'ready_upload\',:now,:now,:payload) ON CONFLICT(id) DO NOTHING'), {'id': identifier, 'owner': owner, 'class': raw['id'], 'recording': recording_id, 'now': now, 'payload': encoded(payload)})
            self._schedule(conn, owner, recording_id, identifier, 1)
            return {'scheduled': True, 'requestId': identifier}

    def _schedule(self, conn, owner, recording_id, identifier, revision, delay=0):
        job = self.jobs.enqueue(owner, recording_id, 'lecture_class_verify', {'requestId': identifier}, 'class-verify:' + identifier + ':' + str(revision), connection=conn, queue='batch', priority=30)
        if delay:
            conn.execute(text('UPDATE learning_jobs SET next_retry_at=:next WHERE id=:id AND status=\'queued\''), {'id': job['id'], 'next': time.time() + delay})

    def read(self, owner, identifier, conn=None):
        if conn is None:
            with self.store.engine.connect() as connection:
                return self.read(owner, identifier, connection)
        row = conn.execute(text('SELECT * FROM class_verification_requests WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).mappings().first()
        if row is None:
            raise TranscriptionFailure('Verification request unavailable.', code='verification_not_found', status_code=404)
        return {**row, 'payload': json.loads(row['payload'])}

    def transition(self, row, state, changes=None, delay=0, schedule=True):
        payload = {**row['payload'], **(changes or {})}
        with self.store.transaction() as conn:
            changed = conn.execute(text('UPDATE class_verification_requests SET state=:state,payload=:payload,revision=revision+1,updated_at=:now,next_poll_at=:next WHERE id=:id AND owner_id=:owner AND revision=:revision'), {'id': row['id'], 'owner': row['owner_id'], 'revision': row['revision'], 'state': state, 'payload': encoded(payload), 'now': time.time(), 'next': time.time() + delay})
            if changed.rowcount != 1:
                raise TranscriptionFailure('Verification state changed; reload the durable request.', code='verification_conflict', status_code=409)
            if schedule:
                self._schedule(conn, row['owner_id'], row['recording_id'], row['id'], row['revision'] + 1, delay)

    def step(self, owner, identifier):
        row = self.read(owner, identifier)
        data = row['payload']
        if row['state'] in {'complete', 'failed', 'submission_unknown', 'deleted'}:
            return {'state': row['state']}
        provider = self.factory(model=data['model'], region=data['region'])
        if row['state'] == 'ready_upload':
            objects = LectureService(self.store).objects
            content = self.assembler(data['chunks'], lambda chunk: objects.read(owner, row['recording_id'], chunk['storage_key']))
            url = provider.upload(content)
            self.transition(row, 'uploaded', {'uploadUrl': url})
        elif row['state'] == 'uploaded':
            # Crash after this commit is a potentially paid ambiguous request.
            self.transition(row, 'submitting', schedule=False)
            submitting = self.read(owner, identifier)
            try:
                external = provider.submit(data['uploadUrl'], data['endMs'] - data['startMs'], keyterms=data.get('keyterms', ()), speaker_labels=data.get('speakerLabels', False))
            except TranscriptionFailure as error:
                unknown = error.code == 'provider_submission_unknown'
                self.transition(submitting, 'submission_unknown' if unknown else 'failed', {'error': str(error), 'errorCode': error.code}, schedule=False)
                raise
            # Save the external ID independently from the worker lease so that
            # a response arriving after lease loss can still be reconciled.
            with self.store.engine.begin() as conn:
                result = conn.execute(text('UPDATE class_verification_requests SET state=\'submitted\',payload=:payload,revision=revision+1,updated_at=:now WHERE id=:id AND owner_id=:owner AND state IN (\'submitting\',\'submission_unknown\')'), {'id': identifier, 'owner': owner, 'payload': encoded({**submitting['payload'], 'externalId': external}), 'now': time.time()})
                if result.rowcount == 1:
                    current = self.read(owner, identifier, conn)
                    self._schedule(conn, owner, row['recording_id'], identifier, current['revision'], 2)
        elif row['state'] == 'submitting':
            self.transition(row, 'submission_unknown', {'error': 'Submission was interrupted. Reconcile the provider request before retrying.', 'errorCode': 'provider_submission_unknown'}, schedule=False)
        elif row['state'] == 'submitted':
            transcript = provider.get(data['externalId'], data['endMs'] - data['startMs'])
            if transcript.status != 'completed':
                count = data['pollCount'] + 1
                if time.time() - row['created_at'] > 1800 or count > 120:
                    self.transition(row, 'failed', {'error': 'Verification exceeded its bounded processing deadline.'}, schedule=False)
                else:
                    self.transition(row, 'submitted', {'pollCount': count}, min(15, 2 + count))
            else:
                self.publish(row, transcript)
        elif row['state'] == 'cleanup':
            provider.delete(data['externalId'])
            self.transition(row, 'deleted', {'uploadUrl': None}, schedule=False)
        return {'state': self.read(owner, identifier)['state']}

    def publish(self, row, transcript):
        data, owner, recording_id = row['payload'], row['owner_id'], row['recording_id']
        if transcript.text and not transcript.words:
            raise TranscriptionFailure('Verification returned text without timed evidence.', code='timed_evidence_unavailable')
        chunks = data['chunks']
        grouped = {chunk['id']: [] for chunk in chunks}
        for word in transcript.words:
            start = data['startMs'] + word.start_ms
            chunk = next((chunk for chunk in chunks if chunk['start_ms'] <= start < chunk['end_ms']), None)
            if chunk is None:
                raise TranscriptionFailure('Speech was attributed to an uncovered audio gap.', code='audio_coverage_mismatch')
            grouped[chunk['id']].append(word)
        with self.store.transaction() as conn:
            current = self.read(owner, row['id'], conn)
            if current['state'] != 'submitted' or current['revision'] != row['revision']:
                return
            # Immutable first publication; human corrections always remain.
            for chunk in chunks:
                source = conn.execute(text('SELECT sha256,transcription_status FROM lecture_audio_chunks WHERE id=:id AND recording_id=:recording'), {'id': chunk['id'], 'recording': recording_id}).mappings().one()
                if source['sha256'] != chunk['sha256'] or source['transcription_status'] == 'completed':
                    raise TranscriptionFailure('The verification source changed.', code='verification_source_changed')
                batches, pending = [], []
                for word in grouped[chunk['id']]:
                    pending.append(word)
                    if len(pending) >= 40 or (len(pending) >= 12 and word.text.endswith(('.', '?', '!'))):
                        batches.append(pending); pending = []
                if pending:
                    batches.append(pending)
                for ordinal, words in enumerate(batches):
                    segment = 'seg_' + hashlib.sha256(encoded([row['id'], chunk['id'], ordinal]).encode()).hexdigest()[:32]
                    start = data['startMs'] + words[0].start_ms
                    end = min(chunk['end_ms'], data['startMs'] + words[-1].end_ms)
                    body = ' '.join(word.text for word in words)
                    if len(body) > 4000:
                        raise TranscriptionFailure('Verified text exceeds its bounded evidence segment.')
                    confidence_values = [word.confidence for word in words if word.confidence is not None]
                    confidence = min(confidence_values) if confidence_values else None
                    conn.execute(text('INSERT INTO lecture_transcript_segments(id,recording_id,chunk_id,ordinal,start_ms,end_ms,speaker,raw_text,normalized_text,confidence,provider,model,transcription_version,normalization_version,created_at) VALUES(:id,:recording,:chunk,:ordinal,:start,:end,\'unknown\',:body,:body,:confidence,\'assemblyai\',:model,1,1,:now)'), {'id': segment, 'recording': recording_id, 'chunk': chunk['id'], 'ordinal': ordinal, 'start': start, 'end': end, 'body': body, 'confidence': confidence, 'model': transcript.model or data['model'], 'now': time.time()})
                    manifest = {'requestId': row['id'], 'providerRequestId': data['externalId'], 'settlement': 'verified', 'speakerRole': 'unknown', 'words': [{'text': w.text, 'startMs': data['startMs'] + w.start_ms, 'endMs': min(chunk['end_ms'], data['startMs'] + w.end_ms), 'confidence': w.confidence, 'speakerId': w.speaker_id} for w in words]}
                    conn.execute(text('INSERT INTO class_evidence_words(owner_id,segment_id,payload) VALUES(:owner,:id,:payload)'), {'owner': owner, 'id': segment, 'payload': encoded(manifest)})
                conn.execute(text('UPDATE lecture_audio_chunks SET transcription_status=\'completed\',transcription_error=NULL,updated_at=:now WHERE id=:id'), {'id': chunk['id'], 'now': time.time()})
            conn.execute(text('UPDATE class_sessions SET completed_chunk_count=completed_chunk_count+:count,chunk_coverage_revision=chunk_coverage_revision+1 WHERE id=:class AND owner_id=:owner'), {'count': len(chunks), 'class': row['class_id'], 'owner': owner})
            from .in_class_service import handoff
            from .class_live_notes import ClassLiveNoteService
            handoff(conn, owner, recording_id, 'verification:' + row['id'])
            ClassLiveNoteService.emit_reconcile(conn, owner, recording_id, data['startMs'], data['endMs'], 'verification:' + row['id'])
            conn.execute(text('UPDATE class_verification_requests SET state=\'cleanup\',revision=revision+1,updated_at=:now WHERE id=:id AND revision=:revision'), {'id': row['id'], 'revision': row['revision'], 'now': time.time()})
            self._schedule(conn, owner, recording_id, row['id'], row['revision'] + 1)
        LectureService(self.store).maybe_enqueue_finalize(owner, recording_id)

    def reconcile(self):
        with self.store.engine.connect() as conn:
            rows = conn.execute(text('SELECT id,owner_id,recording_id,revision FROM class_verification_requests WHERE state NOT IN (\'complete\',\'deleted\',\'failed\',\'submission_unknown\') AND next_poll_at<=:now ORDER BY updated_at LIMIT 100'), {'now': time.time()}).mappings().all()
        for row in rows:
            with self.store.transaction() as conn:
                self._schedule(conn, row['owner_id'], row['recording_id'], row['id'], row['revision'])

    def listing(self, owner, class_id):
        from .in_class_service import InClassService
        with self.store.engine.connect() as conn:
            InClassService(self.store).row(conn, owner, class_id)
            rows = conn.execute(text('SELECT id,state,revision,payload FROM class_verification_requests WHERE owner_id=:owner AND class_id=:class ORDER BY created_at DESC LIMIT 50'), {'owner': owner, 'class': class_id}).mappings().all()
        return {'items': [{'id': row['id'], 'state': row['state'], 'revision': row['revision'], **{key: json.loads(row['payload']).get(key) for key in ('startMs', 'endMs', 'model', 'error', 'errorCode')}} for row in rows]}

    def retry(self, owner, class_id, identifier, revision):
        from fastapi import HTTPException
        row = self.read(owner, identifier)
        if row['class_id'] != class_id:
            raise HTTPException(404, {'code': 'request_not_found', 'message': 'Verification request unavailable.'})
        if row['revision'] != revision:
            raise HTTPException(409, {'code': 'revision_conflict', 'message': 'Verification changed. Refresh before retrying.'})
        if row['state'] in {'submitting', 'submission_unknown'}:
            raise HTTPException(409, {'code': 'provider_submission_unknown', 'message': 'Reconcile this request with the provider before resubmitting; it may already be billed.'})
        if row['state'] in {'complete', 'deleted'}:
            return self.listing(owner, class_id)
        state = 'submitted' if row['payload'].get('externalId') else 'uploaded' if row['payload'].get('uploadUrl') else 'ready_upload'
        self.transition(row, 'cleanup' if row['state'] == 'cleanup' else state, {'error': None, 'errorCode': None, 'pollCount': 0})
        return self.listing(owner, class_id)

    def associate_receipt(self,owner,class_id,identifier,revision,external_id):
        from fastapi import HTTPException
        row=self.read(owner,identifier)
        if row['class_id']!=class_id:raise HTTPException(404,{'code':'request_not_found','message':'Verification request unavailable.'})
        data=row['payload']
        if data.get('externalId')==external_id:return self.listing(owner,class_id)
        if row['revision']!=revision:raise HTTPException(409,{'code':'revision_conflict','message':'Verification changed. Reload it.'})
        if row['state'] not in {'submitting','submission_unknown'} or not data.get('uploadUrl'):
            raise HTTPException(409,{'code':'reconciliation_unavailable','message':'This request does not need provider receipt reconciliation.'})
        provider=self.factory(model=data['model'],region=data['region'])
        # Read-only provider lookup; attach only the exact persisted upload URL.
        # A receipt belonging to another recording can never publish its text here.
        provider.verify_request_source(external_id,data['uploadUrl'])
        self.transition(row,'submitted',{'externalId':external_id,'error':None,'errorCode':None,'pollCount':0,'receiptReconciled':True},delay=2)
        return self.listing(owner,class_id)
