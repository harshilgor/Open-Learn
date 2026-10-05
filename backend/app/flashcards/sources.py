"""Resolve authorized, revision-pinned sources. Browser references never supply text."""
import json
from sqlalchemy import text
from ..identity import fail
from ..workflow_store import WorkflowStore
from .repository import digest

def resolve(store,conn,owner,request):
    session=conn.execute(text('SELECT payload FROM learning_sessions WHERE id=:id AND learner_id=:owner'),{'id':request.session_id,'owner':owner}).scalar_one_or_none()
    if session is None:fail('not_found','Conversation unavailable.',404)
    session=json.loads(session)
    course=session.get('course_id') or session.get('courseId')
    if request.course_id and course!=request.course_id:fail('source_scope_mismatch','Choose sources in the current course.',422)
    sources=[];remaining=24000;partial=False
    for ref in request.source_refs:
        value=ref.model_dump(by_alias=True,exclude_none=True);title='Study source';content=''
        if ref.kind in {'note','lesson'}:
            from ..workspace_note_service import WorkspaceNoteService,WorkspaceNoteError
            try:note=WorkspaceNoteService(store)._read_file(owner,ref.id)
            except WorkspaceNoteError as exc:fail(exc.code,exc.message,exc.status_code)
            if note.revision!=ref.revision:fail('source_revision_conflict','The note changed. Select its current revision.',409)
            front=note.frontmatter
            note_course=front.get('course_id') or front.get('courseId')
            if request.course_id and note_course and note_course!=request.course_id:fail('source_scope_mismatch','Note belongs to another course.',422)
            if ref.kind=='lesson' and (not front.get('study_note') or request.session_id not in front.get('session_ids',[])):fail('source_scope_mismatch','Choose a delivered study note linked to this conversation.',422)
            start=ref.start_offset or 0;end=ref.end_offset if ref.end_offset is not None else len(note.body)
            if start>=end or end>len(note.body):fail('invalid_source_selection','Note selection is out of range.',422)
            content=note.body[start:end];title=note.title
        elif ref.kind=='material':
            from ..material_service import MaterialService
            version=MaterialService(store).version(owner,ref.id,conn)
            if version['version']!=ref.revision:fail('source_revision_conflict','Material version changed.',409)
            if version['status'] not in {'ready','partially_ready'} or version['role'] in {'answer_key','sample_paper'}:fail('unsupported_source','Choose available reference material.',422)
            if request.course_id and version.get('course_id') not in {None,request.course_id}:fail('source_scope_mismatch','Material belongs to another course.',422)
            if not conn.execute(text('SELECT 1 FROM material_attachments WHERE session_id=:sid AND version_id=:id'),{'sid':request.session_id,'id':ref.id}).first():fail('source_scope_mismatch','Attach this material to the conversation first.',422)
            blocks=conn.execute(text('SELECT id,text FROM material_blocks WHERE version_id=:id ORDER BY ordinal'),{'id':ref.id}).all()
            if ref.span_id:blocks=[b for b in blocks if b[0]==ref.span_id]
            content='\n'.join(b[1] for b in blocks);title=version['title']
        elif ref.kind=='quiz_attempt':
            records=WorkflowStore(store);attempt=records.read(owner,ref.id,'attempt',conn)
            if attempt['revision']!=ref.revision:fail('source_revision_conflict','Quiz feedback changed.',409)
            quiz=records.read(owner,attempt.get('quizId'),'quiz',conn)
            if quiz.get('sessionId')!=request.session_id or attempt.get('status') in {'contested','pending'}:fail('unsupported_source','Choose committed quiz feedback in this conversation.',422)
            presentation=records.read(owner,attempt['presentationId'],'presentation',conn)
            content='Question: '+presentation.get('stem','')+'\nSolution: '+attempt.get('solution','')+'\nFeedback: '+attempt.get('feedback','');title='Committed quiz feedback'
        elif ref.kind=='lecture':
            row=conn.execute(text('SELECT s.*,r.learner_id,r.title FROM lecture_transcript_segments s JOIN lecture_recordings r ON r.id=s.recording_id WHERE s.id=:id AND r.learner_id=:owner'),{'id':ref.id,'owner':owner}).mappings().first()
            if not row or not ref.recording_id or row['recording_id']!=ref.recording_id:fail('not_found','Lecture segment unavailable.',404)
            if row['normalization_version']!=ref.revision:fail('source_revision_conflict','Transcript changed.',409)
            linked=conn.execute(text('SELECT 1 FROM class_sessions WHERE recording_id=:rid AND session_id=:sid AND owner_id=:owner'),{'rid':ref.recording_id,'sid':request.session_id,'owner':owner}).first()
            if not linked:fail('source_scope_mismatch','Lecture belongs to another conversation.',422)
            content=row['normalized_text'] or row['raw_text'];title=row['title'];value.update(startMs=row['start_ms'],endMs=row['end_ms'])
        if not content.strip():fail('unsupported_source','The selected source has no available text.',422)
        full_hash=digest(content);excerpt=content[:min(8000,remaining)];remaining-=len(excerpt)
        partial=partial or len(excerpt)!=len(content)
        if excerpt:sources.append({'id':ref.id,'title':title,'ref':value,'text':excerpt,'hash':full_hash})
    return {'sources':sources,'partial':partial,'courseId':request.course_id or course,'buddyId':session.get('buddy_id') or session.get('buddyId'),'sessionId':request.session_id}


