import json
import pytest
from fastapi import HTTPException
from backend.app.openintelligentui import ActivityCollector, GeneratedVisual, issue_ticket, verify_ticket
from backend.app.openintelligentui import capability, jev_model, jev_payload, jev_receipt


def test_visual_plan_stream_is_bounded_and_does_not_include_extra_fields():
    collector = ActivityCollector('Visual')
    collector.accept({'type': 'TOOL_CALL_START', 'toolCallId': 'plan', 'toolCallName': 'plan_visualization'})
    payload = json.dumps({'approach': 'a' * 600, 'technology': 'SVG',
                          'key_elements': ['x' * 200] * 6, 'untrusted': 'discard'})
    for chunk in (payload[:50], payload[50:]):
        collector.accept({'type': 'TOOL_CALL_ARGS', 'toolCallId': 'plan', 'delta': chunk})
    collector.accept({'type': 'TOOL_CALL_END', 'toolCallId': 'plan'})
    assert collector.plan == {'approach': 'a' * 500, 'technology': 'SVG',
                              'keyElements': ['x' * 120] * 4}


def test_stream_policy_error_exposes_only_fixed_code():
    collector = ActivityCollector('Visual')
    with pytest.raises(ValueError, match='^visual_usage_window_exhausted$'):
        collector.accept({'type': 'RUN_ERROR', 'message': "Error: {'code': 'usage_window_exhausted', 'message': 'private detail'}"})
    with pytest.raises(ValueError, match='^visual_generation_failed$'):
        collector.accept({'type': 'RUN_ERROR', 'message': 'private detail'})


def test_ticket_tamper_and_expiry(monkeypatch):
    monkeypatch.setenv('OPENLEARN_VISUAL_INTERNAL_SECRET', 'x' * 48)
    value = issue_ticket('learner-a', 'generation-a')
    assert verify_ticket(value)['owner'] == 'learner-a'
    with pytest.raises(HTTPException):
        verify_ticket(value[:-1] + ('0' if value[-1] != '0' else '1'))
    monkeypatch.setattr('backend.app.openintelligentui.time.time', lambda: 10**12)
    with pytest.raises(HTTPException):
        verify_ticket(value)


def test_pinned_activity_stream_reduces_and_requires_terminal():
    collector = ActivityCollector('Circuit')
    collector.accept({'type':'ACTIVITY_SNAPSHOT','activityType':'open-generative-ui','messageId':'one','content':{'generating':True}})
    for path,value in [('/css','body{}'),('/cssComplete',True),('/html/-','<p>Circuit</p>'),('/htmlComplete',True),('/generating',False)]:
        collector.accept({'type':'ACTIVITY_DELTA','activityType':'open-generative-ui','messageId':'one','patch':[{'op':'add','path':path,'value':value}]})
    with pytest.raises(ValueError,match='interrupted'): collector.final()
    collector.accept({'type':'RUN_FINISHED'})
    assert collector.final()[0].content['html'] == ['<p>Circuit</p>']
    assert json.loads(collector.final()[0].model_dump_json(by_alias=True))['version'] == 2


def test_rejects_unknown_patch_and_partial_success():
    collector=ActivityCollector('Visual')
    collector.accept({'type':'ACTIVITY_SNAPSHOT','activityType':'open-generative-ui','messageId':'one','content':{'generating':True}})
    with pytest.raises(ValueError,match='patch'):
        collector.accept({'type':'ACTIVITY_DELTA','activityType':'open-generative-ui','messageId':'one','patch':[{'op':'add','path':'/unexpected','value':'x'}]})
    collector.accept({'type':'RUN_FINISHED'})
    with pytest.raises(ValueError,match='incomplete'): collector.final()


def test_optional_height_allows_deltas_before_snapshot():
    collector=ActivityCollector('Visual')
    collector.accept({'type':'ACTIVITY_DELTA','activityType':'open-generative-ui','messageId':'one','patch':[{'op':'add','path':'/css','value':'body{}'}]})
    collector.accept({'type':'ACTIVITY_SNAPSHOT','activityType':'open-generative-ui','messageId':'one','content':{'initialHeight':200,'generating':True}})
    assert next(iter(collector.values.values())).content['css']=='body{}'
    collector.accept({'type':'ACTIVITY_DELTA','activityType':'open-generative-ui','messageId':'one','patch':[{'op':'add','path':'/placeholderMessages','value':[]},{'op':'add','path':'/placeholderMessages/-','value':'Preparing visual'}]})
    assert 'placeholderMessages' not in next(iter(collector.values.values())).content


def test_a2ui_table_catalog_and_shape():
    collector=ActivityCollector('Compare')
    operations=[{'createSurface':{'catalogId':'copilotkit://open-generative-ui-tables'}},
                {'updateComponents':{'components':[{'id':'root','component':'Table','title':'Table','columns':['A'],'rows':[['1']],'source':'Illustrative'}]}}]
    visual=collector.accept({'type':'ACTIVITY_SNAPSHOT','activityType':'a2ui-surface','messageId':'table','content':{'a2ui_operations':operations}})
    assert visual.renderer == 'a2ui'
    operations[1]['updateComponents']['components'][0]['rows']=[['1','2']]
    with pytest.raises(ValueError,match='table'):
        collector.accept({'type':'ACTIVITY_SNAPSHOT','activityType':'a2ui-surface','messageId':'table','content':{'a2ui_operations':operations}})


def test_content_limit_and_invalid_code():
    with pytest.raises(ValueError):
        GeneratedVisual(id='one',renderer='open_generative_ui',title='Visual',content={'html':[123]})
    with pytest.raises(ValueError):
        GeneratedVisual(id='one',renderer='open_generative_ui',title='Visual',content={'css':'x'*512001})


def test_openrouter_jev_configuration_needs_no_typesafe_key(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setenv('OPENLEARN_VISUAL_INTERNAL_SECRET', 'x'*48)
    monkeypatch.setenv('AI_TUTOR_ENV', 'test')
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    monkeypatch.delenv('OPENLEARN_VISUAL_JEV_MODEL', raising=False)
    assert capability()['configured']
    assert capability()['jevProvider'] == 'openrouter'
    assert jev_model() == 'typesafe/jev-1.13'
    monkeypatch.setenv('OPENLEARN_VISUAL_JEV_MODEL', 'jev-latest')
    assert jev_model() == '~typesafe/jev-latest'
    monkeypatch.setenv('OPENLEARN_VISUAL_JEV_MODEL', 'typesafe/jev-router')
    assert not capability()['configured']


@pytest.mark.parametrize('cost', [None, True, -1, 'NaN', 'Infinity', 'bad'])
def test_jev_invalid_cost_retains_reserved_bound(cost):
    assert jev_receipt({'usage': {'cost': cost}})[0] is None


def test_jev_exact_receipt_and_fixed_payload(monkeypatch):
    monkeypatch.delenv('OPENLEARN_VISUAL_JEV_MODEL', raising=False)
    cost, quantities = jev_receipt({'usage': {'cost': 0.000014994, 'input_tokens': 357, 'output_tokens': 38}})
    assert cost == 14994
    assert quantities == {'input_tokens': 357, 'output_tokens': 38}
    payload = {'model': jev_model(), 'state': 'Explain force', 'questions': {'visualization': {'type':'choice'}}, 'provider': {'allow_fallbacks': True}}
    assert 'provider' not in jev_payload(payload)
    with pytest.raises(HTTPException):
        jev_payload({**payload, 'model': 'another/model'})
    with pytest.raises(HTTPException):
        jev_payload({**payload, 'questions': []})


@pytest.mark.parametrize('status', [200, 503])
def test_jev_proxy_uses_openrouter_and_settles_receipt(monkeypatch, status):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.openintelligentui import build_router, JEV_DECISIONS_URL
    monkeypatch.setenv('OPENROUTER_API_KEY', 'openrouter-test')
    monkeypatch.setenv('OPENLEARN_VISUAL_INTERNAL_SECRET', 'x'*48)
    monkeypatch.setenv('OPENLEARN_VISUAL_ENGINE', 'openintelligentui')
    monkeypatch.setenv('AI_TUTOR_ENV', 'test')
    monkeypatch.delenv('OPENLEARN_VISUAL_JEV_MODEL', raising=False)
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    monkeypatch.setattr('backend.app.generation_store.GenerationStore.get', lambda *args: {'status':'streaming', 'session':'session-a'})
    monkeypatch.setattr('backend.app.material_service.MaterialService.__init__', lambda *args: None)
    monkeypatch.setattr('backend.app.material_service.MaterialService.session', lambda *args: {})
    reservations, settlements, requests = [], [], []
    monkeypatch.setattr('backend.app.usage.operations.configured_rate', lambda name: 10000000)
    monkeypatch.setattr('backend.app.usage.operations.begin_external', lambda *args, **kwargs: reservations.append(kwargs) or 'ticket')
    monkeypatch.setattr('backend.app.usage.operations.finish_external', lambda *args, **kwargs: settlements.append(kwargs))
    answer = {'answers': {'visualization': {'type':'choice', 'choice':'text', 'confidence':1, 'probabilities':{'text':1}}},
              'usage': {'input_tokens':100, 'output_tokens':10, 'cost':0.0000042}, 'id':'receipt-a'}
    def response(request):
        requests.append(request)
        return httpx.Response(status, json=answer)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(response)))
    app = FastAPI(); app.include_router(build_router(lambda: object()))
    with TestClient(app) as client:
        result = client.post('/internal/visuals/jev', headers={'Authorization':'Bearer '+issue_ticket('owner-a','generation-a')},
            json={'model':jev_model(), 'state':'Hello', 'questions':{'visualization':{'type':'choice'}}})
    assert result.status_code == status
    assert str(requests[0].url) == JEV_DECISIONS_URL
    assert requests[0].headers['authorization'] == 'Bearer openrouter-test'
    assert reservations[0]['provider'] == 'openrouter'
    assert len(settlements) == 1
    assert settlements[0]['cost_nano'] == (4200 if status == 200 else None)
    assert settlements[0]['source'] == ('exact' if status == 200 else 'estimated')
