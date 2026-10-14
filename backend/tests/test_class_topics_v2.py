import pytest
from fastapi import HTTPException
from sqlalchemy import text
from backend.tests.test_in_class import env,audio,drain
from backend.app.class_document import ClassDocumentService
from backend.app.class_topics import ClassTopicService
from backend.app.class_study_routes import TopicChange,DocumentEdit


def test_topic_grouping_and_student_moves_are_preserved(env):
    store,classes,_,snapshot=env;audio(env);drain(classes)
    item={'id':snapshot['session']['id'],'owner':'alice'}
    document=ClassDocumentService(store);topics=ClassTopicService(classes)
    first=document.page('alice',item['id'])['items'][0]
    with store.transaction() as conn:
        ClassDocumentService.publish(conn,item,{'kind':'notes','status':'ready','id':'second','result':{'blocks':[{'title':'Transport','body':'Membrane transport.','segmentIds':['transport-source']}]}})
    sections=topics.listing('alice',item['id'])['items'];assert len(sections)==2
    source=next(topic for topic in sections if topic['id']==first['topicId']);target=next(topic for topic in sections if topic['id']!=source['id'])
    topics.change('alice',item['id'],source['id'],TopicChange(expectedRevision=source['revision'],action='rename',title='My cell topic'))
    with pytest.raises(HTTPException):topics.change('alice',item['id'],source['id'],TopicChange(expectedRevision=source['revision'],action='rename',title='Stale edit'))
    moved=document.edit('alice',item['id'],first['id'],DocumentEdit(expectedRevision=first['revision'],action='move',topicId=target['id'],position=-1))
    with store.transaction() as conn:
        ClassDocumentService.publish(conn,item,{'kind':'notes','status':'ready','id':'update','result':{'blocks':[{'title':'Cell structure','body':'Updated generated note.','segmentIds':first['generated']['segmentIds']}]}})
    after=next(block for block in document.page('alice',item['id'])['items'] if block['id']==first['id'])
    assert after['topicId']==target['id'] and after['position']==-1 and not after['studentEdited']
    with pytest.raises(HTTPException):topics.listing('bob',item['id'])


def test_repeated_generated_heading_uses_one_stable_topic(env):
    store,classes,_,snapshot=env;audio(env);drain(classes)
    item={'id':snapshot['session']['id'],'owner':'alice'}
    before=ClassTopicService(classes).listing('alice',item['id'])['items'][0]
    with store.transaction() as conn:
        ClassDocumentService.publish(conn,item,{'kind':'notes','status':'ready','id':'second','result':{'blocks':[{'title':'CELL STRUCTURE!','body':'Continuation.','segmentIds':['another-source']}]}})
    after=ClassTopicService(classes).listing('alice',item['id'])['items']
    assert len(after)==1 and after[0]['id']==before['id'] and after[0]['blockCount']==2


def test_topic_merge_preserves_block_ids_and_text(env):
    store,classes,_,snapshot=env;audio(env);drain(classes)
    item={'id':snapshot['session']['id'],'owner':'alice'}
    first=ClassDocumentService(store).page('alice',item['id'])['items'][0]
    with store.transaction() as conn:
        ClassDocumentService.publish(conn,item,{'kind':'notes','status':'ready','id':'other','result':{'blocks':[{'title':'Nucleus','body':'Genetic information.','segmentIds':['nucleus-source']}]}})
    topics=ClassTopicService(classes);sections=topics.listing('alice',item['id'])['items']
    source=next(section for section in sections if section['id']==first['topicId']);target=next(section for section in sections if section['id']!=first['topicId'])
    topics.change('alice',item['id'],source['id'],TopicChange(expectedRevision=source['revision'],action='merge',targetTopicId=target['id'],targetRevision=target['revision']))
    current=next(block for block in ClassDocumentService(store).page('alice',item['id'])['items'] if block['id']==first['id'])
    assert current['topicId']==target['id'] and current['body']==first['body']
