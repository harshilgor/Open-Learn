import pytest
from pydantic import ValidationError
from backend.tests.test_in_class import env, audio, drain
from backend.app.class_document import ClassDocumentService
from backend.app.class_visuals import ClassVisualService, VisualSpec, VisualRequest, VisualChange


@pytest.mark.parametrize('content',[
    {'kind':'plot','points':[{'x':float('nan'),'y':1},{'x':2,'y':3}]},
    {'kind':'table','columns':['A'],'rows':[['A','B']]},
    {'kind':'concept_map','nodes':[{'id':'one','label':'One'}],'edges':[{'source':'one','target':'absent'}]},
    {'kind':'equation_steps','steps':[]},
    {'kind':'illustration','nodes':[{'id':'one','label':'One'}],'script':'alert(1)'},
])
def test_unsafe_or_malformed_visuals_are_rejected(content):
    with pytest.raises(ValidationError):VisualSpec.model_validate({'title':'Test','description':'Description',**content})


def test_visual_runs_in_worker_and_is_idempotent(env):
    store,svc,_,snapshot=env
    audio(env);drain(svc)
    item=snapshot['session'];block=ClassDocumentService(store).page('alice',item['id'])['items'][0]
    class Provider:
        def complete_json(self,prompt,tokens):
            assert prompt.startswith('CLASS_VISUAL_V1')
            return {'kind':'concept_map','title':'Cell','description':'Lecture cell structure','nodes':[{'id':'membrane','label':'Cell membrane'}]}
    svc.provider=Provider();visuals=ClassVisualService(svc)
    body=VisualRequest(commandId='first',blockId=block['id'],expectedRevision=block['revision'],kind='concept_map')
    created=visuals.request('alice',item['id'],body)
    assert visuals.request('alice',item['id'],body)==created
    svc.tick(1)
    saved=visuals.listing('alice',item['id'])['items'][0]
    assert saved['state']=='ready' and saved['spec']['nodes'][0]['label']=='Cell membrane'
    edited_spec=VisualSpec.model_validate({**saved['spec'],'title':'My cell diagram'})
    edit=VisualChange(commandId='edit',expectedRevision=saved['revision'],action='edit',spec=edited_spec)
    edited=visuals.change('alice',item['id'],saved['id'],edit)
    assert visuals.change('alice',item['id'],saved['id'],edit)==edited
    updating=visuals.change('alice',item['id'],saved['id'],VisualChange(commandId='regen',expectedRevision=edited['revision'],action='regenerate'))
    assert updating['state']=='updating' and updating['spec']['title']=='My cell diagram'
    svc.tick(1)
    regenerated=visuals.listing('alice',item['id'])['items'][0]
    assert regenerated['spec']['title']=='My cell diagram' and regenerated['suggestion']['title']=='Cell'
    accepted=visuals.change('alice',item['id'],saved['id'],VisualChange(commandId='accept',expectedRevision=regenerated['revision'],action='accept_suggestion'))
    assert accepted['spec']['title']=='Cell' and not accepted['studentEdited']
    removed=visuals.change('alice',item['id'],saved['id'],VisualChange(commandId='remove',expectedRevision=accepted['revision'],action='remove'))
    assert removed['state']=='removed'


def test_removing_queued_visual_fences_worker_publication(env):
    store,svc,_,snapshot=env;audio(env);drain(svc)
    item=snapshot['session'];block=ClassDocumentService(store).page('alice',item['id'])['items'][0]
    visuals=ClassVisualService(svc)
    created=visuals.request('alice',item['id'],VisualRequest(commandId='first',blockId=block['id'],expectedRevision=block['revision'],kind='concept_map'))
    visuals.change('alice',item['id'],created['id'],VisualChange(commandId='remove',expectedRevision=created['revision'],action='remove'))
    class Provider:
        def complete_json(self,*args):raise AssertionError('Removed visual must not call provider')
    svc.provider=Provider();svc.tick(1)
    assert visuals.listing('alice',item['id'])['items'][0]['state']=='removed'


def test_automatic_visual_is_deduplicated_per_topic_and_budgeted(env,monkeypatch):
    from sqlalchemy import text
    store,svc,_,snapshot=env;audio(env);drain(svc)
    monkeypatch.setenv('OPENLEARN_CLASS_AUTO_VISUALS_ENABLED','true')
    with store.transaction() as conn:
        item=svc.row(conn,'alice',snapshot['session']['id'],True)
        item['policy'].update(autoVisuals=True,autoVisualBudget=1);svc.save(conn,item)
        output={'id':'continuation','kind':'notes','status':'ready','result':{'blocks':[{'title':'Cell structure','body':'More evidence about the cell.','segmentIds':['new-source']}]}}
        svc.publish(conn,item,output)
        ClassVisualService(svc).auto(conn,item,output)
        assert conn.execute(text('SELECT COUNT(*) FROM class_visual_artifacts WHERE class_id=:class'),{'class':item['id']}).scalar_one()==1
