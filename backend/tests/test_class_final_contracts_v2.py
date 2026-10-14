import pytest
from fastapi import HTTPException
from sqlalchemy import text
from backend.tests.test_in_class import env,audio,drain
from backend.app.class_document import ClassDocumentService
from backend.app.class_visual_math import checked_numeric_equality
from backend.app.class_visuals import VisualSpec
from backend.app.lecture_observations import LectureObservationService
from backend.app.class_features import status,require,FLAGS
from backend.app.class_study_routes import DocumentEdit


def test_resegmented_evidence_keeps_student_block_and_rejects_stale_suggestion(env):
    store,classes,_,snapshot=env;audio(env);drain(classes)
    document=ClassDocumentService(store);class_id=snapshot['session']['id']
    original=document.page('alice',class_id)['items'][0]
    edited=document.edit('alice',class_id,original['id'],DocumentEdit(expectedRevision=original['revision'],title='My note',body='Preserve my explanation'))
    with store.transaction() as conn:
        conn.execute(text("UPDATE class_document_blocks SET state='stale',source_start_ms=0,source_end_ms=5000 WHERE id=:id"),{'id':original['id']})
        document.publish(conn,{'owner':'alice','id':class_id},{'kind':'notes','status':'ready','id':'corrected-output','result':{'blocks':[{'title':'Corrected topic','body':'Updated evidence','segmentIds':['new-split-id'],'sourceManifest':{'startMs':0,'endMs':5000,'segments':[{'segmentId':'new-split-id','revision':2}]}}]}})
    page=document.page('alice',class_id);assert len(page['items'])==1
    block=page['items'][0];assert block['id']==original['id'] and block['body']=='Preserve my explanation'
    assert block['suggestion']['body']=='Updated evidence'
    with pytest.raises(HTTPException) as failure:document.edit('alice',class_id,block['id'],DocumentEdit(expectedRevision=block['revision'],action='accept_suggestion'))
    assert failure.value.detail['code']=='source_stale'


def test_simple_numeric_equations_are_checked_without_execution():
    assert checked_numeric_equality('$2+2=4$') is True
    assert checked_numeric_equality(r'$\frac{1}{2}=0.5$') is True
    assert checked_numeric_equality('$2+2=5$') is False
    assert checked_numeric_equality('x + y = z') is None
    assert checked_numeric_equality("__import__('os').system('echo unsafe') = 1") is None
    with pytest.raises(ValueError):checked_numeric_equality('2^99999=0')
    with pytest.raises(ValueError):VisualSpec(kind='equation_steps',title='Bad equality',description='Invalid arithmetic',steps=['2+2=5'])


def test_rollout_flags_default_off_and_are_independent(monkeypatch):
    for name in FLAGS.values():monkeypatch.delenv(name,raising=False)
    assert not any(status().values())
    with pytest.raises(HTTPException):require('buddy')
    monkeypatch.setenv(FLAGS['buddy'],'true')
    require('buddy')
    assert status()['buddy'] and not status()['phonePairing']


def test_correction_and_undo_preserve_raw_text_and_append_revisions(env):
    store,classes,body,snapshot=env;audio(env);drain(classes)
    with store.engine.connect() as conn:
        segment=conn.execute(text('SELECT id,normalized_text,raw_text FROM lecture_transcript_segments WHERE recording_id=:recording LIMIT 1'),{'recording':body.recording.id}).mappings().one()
    observer=LectureObservationService(store)
    changed=observer.correct_transcript('alice',body.recording.id,segment['id'],'A cell has a membrane.',1,'professor')
    assert changed['speakerRole']=='professor' and changed['revision']==2
    reverted=observer.undo_transcript('alice',body.recording.id,segment['id'],2)
    assert reverted['revision']==3 and reverted['wording']==segment['normalized_text']
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT raw_text FROM lecture_transcript_segments WHERE id=:id'),{'id':segment['id']}).scalar_one()==segment['raw_text']
        assert conn.execute(text('SELECT COUNT(*) FROM lecture_transcript_revisions WHERE recording_id=:recording'),{'recording':body.recording.id}).scalar_one()==2


def test_multi_hour_document_pages_are_bounded_and_complete(env):
    store,classes,_,snapshot=env;item={'owner':'alice','id':snapshot['session']['id']}
    with store.transaction() as conn:
        for index in range(300):
            ClassDocumentService.publish(conn,item,{'kind':'notes','status':'ready','id':'window-'+str(index),'result':{'blocks':[{'title':'Topic '+str(index//50),'body':'Bounded class note '+str(index),'segmentIds':['source-'+str(index)],'sourceManifest':{'startMs':index*30000}}]}})
    document=ClassDocumentService(store);cursor='';seen=[]
    while True:
        page=document.page('alice',item['id'],cursor)
        assert len(page['items'])<=50 and page['totalCount']==300
        seen.extend(block['id'] for block in page['items'])
        cursor=page['nextCursor']
        if not cursor:break
    assert len(seen)==len(set(seen))==300


def test_class_setup_grants_scope_and_graph_to_explicit_owner(env):
    store,_,body,snapshot=env
    session=store.get_session(snapshot['session']['sessionId'])
    with store.engine.connect() as conn:
        owner=conn.execute(text("SELECT owner_id FROM identity_resources WHERE kind='graph_versions' AND id=:id"),{'id':session.graph_id}).scalar_one()
        scope_owner=conn.execute(text("SELECT owner_id FROM identity_resources WHERE kind='topic_scopes' AND id=:id"),{'id':'scope_class_'+body.recording.id}).scalar_one()
    assert owner==scope_owner=='alice'
