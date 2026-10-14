import json
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from backend.tests.test_in_class import env, audio
from backend.app.class_buddy import ClassBuddyService
from backend.app.assessment_models import ClassContextInput
from backend.app.lecture_observations import LectureObservationService
from backend.app.class_study_routes import DoubtInput, DoubtUpdate


def test_frozen_question_excludes_future_and_preserves_corrections(env):
    store, _, body, snapshot = env
    audio(env)
    item = snapshot['session']
    service = ClassBuddyService(store)
    with store.transaction() as conn:
        service.freeze(conn, 'alice', item['sessionId'], 'early', ClassContextInput(classId=item['id'], anchorMs=10000), 'What is a cell?')
        service.freeze(conn, 'alice', item['sessionId'], 'now', ClassContextInput(classId=item['id'], anchorMs=30000), 'What is a cell?', {'messageId': 'corrected-message'})
    assert service.for_generation('alice', 'early')['evidence'] == []
    original = service.for_generation('alice', 'now')
    source = original['evidence'][0]
    LectureObservationService(store).correct_transcript('alice', body.recording.id, source['segmentId'], 'A cell has a membrane.', source['revision'])
    changed = service.for_generation('alice', 'now')
    assert changed['needsReview'] and changed['evidence'] == original['evidence']
    with store.transaction() as conn:
        service.freeze(conn, 'alice', item['sessionId'], 'corrected-retry', ClassContextInput(classId=item['id'], anchorMs=60000), 'What is a cell?', {'messageId': 'corrected-message', 'isRetry': True})
    retry = service.for_generation('alice', 'corrected-retry')
    assert retry['needsReview'] and retry['evidence'] == original['evidence'] and retry['anchorMs'] == 30000
    assert service.for_generation('bob', 'now') is None


def test_selection_revision_and_class_chat_are_validated(env):
    store, _, _, snapshot = env
    audio(env)
    item = snapshot['session']
    service = ClassBuddyService(store)
    with store.transaction() as conn:
        segment = conn.execute(text('SELECT id FROM lecture_transcript_segments LIMIT 1')).scalar_one()
        with pytest.raises(HTTPException):
            service.freeze(conn, 'alice', 'wrong-chat', 'one', ClassContextInput(classId=item['id'], anchorMs=30000), 'Question')
        with pytest.raises(HTTPException):
            service.freeze(conn, 'alice', item['sessionId'], 'two', ClassContextInput(classId=item['id'], anchorMs=30000, segmentRefs=[{'segmentId': segment, 'revision': 99}]), 'Question')


def test_retry_keeps_original_anchor_and_doubts_use_revisions(env):
    store, _, _, snapshot = env
    audio(env)
    item = snapshot['session']; service = ClassBuddyService(store)
    with store.transaction() as conn:
        service.freeze(conn, 'alice', item['sessionId'], 'first', ClassContextInput(classId=item['id'], anchorMs=30000), 'Question', {'messageId': 'message'})
        service.freeze(conn, 'alice', item['sessionId'], 'retry', ClassContextInput(classId=item['id'], anchorMs=60000), 'Question', {'messageId': 'message', 'isRetry': True})
    assert service.for_generation('alice', 'retry')['anchorMs'] == 30000
    doubt = service.doubt('alice', item['id'], DoubtInput(commandId='save', anchorMs=30000, question='Why?'))
    assert service.doubt('alice', item['id'], DoubtInput(commandId='save', anchorMs=30000, question='Why?')) == doubt
    service.resolve('alice', item['id'], doubt['id'], DoubtUpdate(expectedRevision=1, resolution='resolved'))
    with pytest.raises(HTTPException):
        service.resolve('alice', item['id'], doubt['id'], DoubtUpdate(expectedRevision=1, resolution='open'))


def test_history_reloads_owned_persisted_answer(env):
    from backend.app.generation_store import GenerationStore
    store, _, _, snapshot = env
    item = snapshot['session']; service = ClassBuddyService(store)
    generation = GenerationStore(store).create('alice', item['sessionId'], {'mode':'ask','message':'Why?'}, 'history', 'fake', 'test')
    with store.transaction() as conn:
        service.freeze(conn,'alice',item['sessionId'],generation['id'],ClassContextInput(classId=item['id'],anchorMs=12000),'Why?')
        conn.execute(text('UPDATE generation_records SET partial_output=:answer WHERE id=:id AND owner_id=:owner'),{'id':generation['id'],'owner':'alice','answer':'A bounded saved explanation.'})
    history=service.history('alice',item['id'])['items']
    assert len(history)==1 and history[0]['answer']=='A bounded saved explanation.'
    assert history[0]['evidence']['anchorMs']==12000
    with pytest.raises(HTTPException):service.history('bob',item['id'])


def test_selected_student_note_is_frozen_and_later_edits_flag_answer(env):
    from backend.tests.test_in_class import drain
    from backend.app.class_document import ClassDocumentService
    from backend.app.class_study_routes import DocumentEdit
    store,classes,_,snapshot=env;audio(env);drain(classes)
    item=snapshot['session'];document=ClassDocumentService(store)
    block=document.page('alice',item['id'])['items'][0]
    edited=document.edit('alice',item['id'],block['id'],DocumentEdit(expectedRevision=block['revision'],title=block['title'],body='My question about membrane transport.'))
    buddy=ClassBuddyService(store)
    with store.transaction() as conn:
        buddy.freeze(conn,'alice',item['sessionId'],'selected-note',ClassContextInput(classId=item['id'],anchorMs=30000,noteRefs=[{'blockId':block['id'],'revision':edited['revision']}]),'Explain my note.')
    original=buddy.for_generation('alice','selected-note')
    assert original['selectedNotes'][0]['studentEdited'] and original['selectedNotes'][0]['body']=='My question about membrane transport.'
    document.edit('alice',item['id'],block['id'],DocumentEdit(expectedRevision=edited['revision'],title=block['title'],body='Changed student note.'))
    after=buddy.for_generation('alice','selected-note')
    assert after['needsReview'] and after['selectedNotes']==original['selectedNotes']


def test_frozen_prior_doubts_are_time_fenced_and_use_current_resolution(env):
    store,_,_,snapshot=env;item=snapshot['session'];service=ClassBuddyService(store)
    first=service.doubt('alice',item['id'],DoubtInput(commandId='early-doubt',anchorMs=10000,question='Earlier question'))
    service.resolve('alice',item['id'],first['id'],DoubtUpdate(expectedRevision=1,resolution='resolved'))
    service.doubt('alice',item['id'],DoubtInput(commandId='future-doubt',anchorMs=60000,question='Future question'))
    with store.transaction() as conn:service.freeze(conn,'alice',item['sessionId'],'bounded-doubts',ClassContextInput(classId=item['id'],anchorMs=30000),'Explain this')
    assert service.for_generation('alice','bounded-doubts')['priorDoubts']==[{'anchorMs':10000,'question':'Earlier question','resolution':'resolved','source':'student'}]
