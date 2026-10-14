import pytest
import json
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


def test_semantic_grouping_reuses_topic_across_different_headings(env):
    store,classes,_,snapshot=env;audio(env);drain(classes)
    item={'id':snapshot['session']['id'],'owner':'alice'}
    topic=ClassTopicService(classes).listing('alice',item['id'])['items'][0]
    with store.transaction() as conn:
        context=ClassTopicService.context(conn,item)
        ClassDocumentService.publish(conn,item,{'kind':'notes','status':'ready','id':'semantic','topicContext':context,'result':{'blocks':[{'title':'Cell boundary','body':'The membrane surrounds the cell.','segmentIds':['boundary-source'],'topicId':topic['id']}]}})
    current=ClassTopicService(classes).listing('alice',item['id'])['items']
    assert len(current)==1 and current[0]['blockCount']==2
    assert any(block['title']=='Cell boundary' for block in ClassDocumentService(store).page('alice',item['id'])['items'])


@pytest.mark.parametrize('protection',['edit','move','rename','stale','source_update'])
def test_automatic_consolidation_preserves_student_organization_and_revision_fences(env,protection):
    store,classes,_,snapshot=env;audio(env);drain(classes)
    item={'id':snapshot['session']['id'],'owner':'alice'};document=ClassDocumentService(store);topics=ClassTopicService(classes)
    first=document.page('alice',item['id'])['items'][0]
    with store.transaction() as conn:
        ClassDocumentService.publish(conn,item,{'kind':'notes','status':'ready','id':'second','result':{'blocks':[{'title':'Cell boundary','body':'Membrane structure.','segmentIds':['boundary-source']}]}})
        context=ClassTopicService.context(conn,item)
    source=next(topic for topic in topics.listing('alice',item['id'])['items'] if topic['id']!=first['topicId'])
    if protection=='edit':document.edit('alice',item['id'],first['id'],DocumentEdit(expectedRevision=first['revision'],title='My cell',body='My protected explanation'))
    elif protection=='move':document.edit('alice',item['id'],first['id'],DocumentEdit(expectedRevision=first['revision'],action='move',topicId=first['topicId'],position=-10))
    elif protection=='rename':topics.change('alice',item['id'],source['id'],TopicChange(expectedRevision=source['revision'],action='rename',title='My boundary topic'))
    elif protection=='source_update':
        with store.transaction() as conn:
            conn.execute(text('UPDATE class_document_blocks SET revision=revision+1 WHERE id=:id'),{'id':first['id']})
    else:
        with store.transaction() as conn:conn.execute(text('UPDATE class_document_topics SET revision=revision+1 WHERE id=:id'),{'id':source['id']})
    with store.transaction() as conn:ClassTopicService.semantic_merges(conn,item,[{'sourceTopicId':source['id'],'targetTopicId':first['topicId']}],context)
    assert len(topics.listing('alice',item['id'])['items'])==2
    after=next(block for block in document.page('alice',item['id'])['items'] if block['id']==first['id'])
    assert after['topicId']==first['topicId']
    if protection=='edit':assert after['body']=='My protected explanation'
    if protection=='move':assert after['position']==-10


def test_semantic_merge_preserves_text_and_redirects_later_mentions(env):
    store,classes,_,snapshot=env;audio(env);drain(classes)
    item={'id':snapshot['session']['id'],'owner':'alice'};document=ClassDocumentService(store);topics=ClassTopicService(classes)
    first=document.page('alice',item['id'])['items'][0]
    with store.transaction() as conn:
        ClassDocumentService.publish(conn,item,{'kind':'notes','status':'ready','id':'second','result':{'blocks':[{'title':'Cell boundary','body':'Membrane structure.','segmentIds':['boundary-source']}]}})
        context=ClassTopicService.context(conn,item)
    before=document.page('alice',item['id'])['items'];source=next(topic for topic in topics.listing('alice',item['id'])['items'] if topic['id']!=first['topicId'])
    with store.transaction() as conn:
        ClassTopicService.semantic_merges(conn,item,[{'sourceTopicId':source['id'],'targetTopicId':first['topicId']}],context)
        ClassDocumentService.publish(conn,item,{'kind':'notes','status':'ready','id':'third','result':{'blocks':[{'title':'Cell boundary','body':'Further details.','segmentIds':['third-source']}]}})
    assert len(topics.listing('alice',item['id'])['items'])==1
    after={block['id']:block for block in document.page('alice',item['id'])['items']}
    assert all(after[block['id']]['body']==block['body'] for block in before)
    assert all(block['topicId']==first['topicId'] for block in after.values())


def test_notes_pipeline_supplies_semantic_outline_to_provider(env,monkeypatch):
    store,classes,_,snapshot=env;audio(env);drain(classes)
    monkeypatch.setenv('OPENLEARN_CLASS_TOPIC_NOTES_ENABLED','true')
    with store.transaction() as conn:
        item=classes.row(conn,'alice',snapshot['session']['id'],True);item['features']={**item.get('features',{}),'topicNotes':True};classes.save(conn,item)
    topic=ClassTopicService(classes).listing('alice',snapshot['session']['id'])['items'][0]
    original=classes.provider.complete_json;seen=[]
    def complete(prompt,*args,**kwargs):
        if 'Existing outline:' in prompt and topic['id'] in prompt:
            seen.append(prompt)
            evidence=json.loads(prompt.split('\n')[-1]);ids=[entry['id'] for entry in evidence]
            return {'blocks':[{'title':'Cell boundary','body':'The membrane surrounds cells.','segmentIds':ids,'topicId':topic['id']}]}
        return original(prompt,*args,**kwargs)
    classes.provider.complete_json=complete
    audio(env,1,30000,60000);drain(classes)
    assert seen
    assert len(ClassTopicService(classes).listing('alice',snapshot['session']['id'])['items'])==1
