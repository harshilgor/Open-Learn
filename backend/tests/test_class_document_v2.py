import pytest
from fastapi import HTTPException
from backend.tests.test_in_class import env, audio, drain
from backend.app.class_document import ClassDocumentService
from backend.app.class_study_routes import DocumentEdit


def test_student_edit_survives_regeneration_and_accept_is_explicit(env):
    store, svc, _, snapshot = env
    audio(env);drain(svc)
    item = snapshot['session']; document = ClassDocumentService(store)
    block = document.page('alice', item['id'])['items'][0]
    saved = document.edit('alice', item['id'], block['id'], DocumentEdit(expectedRevision=block['revision'],title='My heading',body='My explanation'))
    with store.transaction() as conn:
        ClassDocumentService.publish(conn, {'id':item['id'],'owner':'alice'}, {'id':'regenerated','kind':'notes','status':'ready','result':{'blocks':[{'title':'Updated heading','body':'Updated explanation','segmentIds':block['generated']['segmentIds']}]}})
    updated = document.page('alice', item['id'])['items'][0]
    assert updated['body']=='My explanation' and updated['suggestion']['body']=='Updated explanation'
    with pytest.raises(HTTPException):
        document.edit('alice', item['id'], block['id'], DocumentEdit(expectedRevision=saved['revision'],action='accept_suggestion'))
    accepted = document.edit('alice', item['id'], block['id'], DocumentEdit(expectedRevision=updated['revision'],action='accept_suggestion'))
    assert accepted['body']=='Updated explanation' and not accepted['studentEdited']
    with pytest.raises(HTTPException):document.page('bob',item['id'])
