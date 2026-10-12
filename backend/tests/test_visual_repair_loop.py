"""Verified repair loop against a scripted CopilotKit runtime stream.

Runtime verification is stubbed here (real Chromium is covered by
test_visual_verification.py); the runtime transport is a mock SSE server.
"""
import asyncio
import json

import pytest

from backend.app.openintelligentui import GeneratedVisual, generate, static_candidate


def sse(events):
    return ''.join('data: ' + json.dumps(event) + '\n\n' for event in events)


def candidate_events(name, html, js='', expressions=()):
    args = {'initialHeight': 200, 'css': '', 'html': html, 'jsFunctions': js, 'jsExpressions': list(expressions)}
    content = {'initialHeight': 200, 'generating': False, 'css': '', 'cssComplete': True, 'html': [html], 'htmlComplete': True,
               'jsFunctions': js, 'jsFunctionsComplete': True, 'jsExpressions': list(expressions), 'jsExpressionsComplete': True}
    return [{'type': 'RUN_STARTED'},
            {'type': 'TOOL_CALL_START', 'toolCallId': f'call_{name}', 'toolCallName': 'generateSandboxedUi', 'parentMessageId': f'ai_{name}'},
            {'type': 'TOOL_CALL_ARGS', 'toolCallId': f'call_{name}', 'delta': json.dumps(args)},
            {'type': 'ACTIVITY_SNAPSHOT', 'activityType': 'open-generative-ui', 'messageId': f'activity_{name}', 'content': content},
            {'type': 'TOOL_CALL_END', 'toolCallId': f'call_{name}'},
            {'type': 'RUN_FINISHED'}]


@pytest.fixture
def runtime(monkeypatch):
    """Serve one scripted SSE run per agent/run request and record requests."""
    import httpx
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setenv('OPENLEARN_VISUAL_INTERNAL_SECRET', 'x' * 48)
    monkeypatch.setenv('AI_TUTOR_ENV', 'test')
    monkeypatch.delenv('OPENLEARN_VISUAL_MODEL', raising=False)
    monkeypatch.delenv('OPENLEARN_VISUAL_JEV_MODEL', raising=False)
    monkeypatch.delenv('OPENLEARN_VISUAL_MAX_ATTEMPTS', raising=False)
    monkeypatch.setenv('OPENROUTER_MODEL', 'openrouter/free')
    runs, requests = [], []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if body['method'] == 'agent/stop':
            return httpx.Response(200, json={})
        return httpx.Response(200, text=runs.pop(0), headers={'content-type': 'text/event-stream'})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)))
    return runs, requests


def run_generate():
    progress = []

    async def emit(value):
        pass

    async def emit_progress(value):
        progress.append(value)
    result = asyncio.run(generate('owner-a', 'job_test', {'title': 'Pendulum'}, 'Show a pendulum', emit, None, emit_progress))
    return result, progress


def verdicts(monkeypatch, outcomes):
    """Runtime verification stub returning the scripted report per call."""
    calls = []

    def fake(content, controls=(), values=None, **kwargs):
        calls.append(content)
        status, findings = outcomes[len(calls) - 1]
        return {'status': status, 'findings': findings, 'digest': f'd{len(calls)}', 'durationMs': 1}
    monkeypatch.setattr('backend.app.visual_verification.verify_blocking', fake)
    monkeypatch.setattr('backend.app.visual_verification.unavailable_reason', lambda: None)
    return calls


def agent_runs(requests):
    return [request for request in requests if request['method'] == 'agent/run']


ERROR = [{'severity': 'error', 'code': 'runtime_exception', 'message': 'desktop: ReferenceError: colr is not defined'}]
WARN = [{'severity': 'warning', 'code': 'unresponsive_control', 'message': 'Changing these controls did not change any visible output: gravity'}]


def test_invalid_javascript_is_repaired_on_the_same_thread(runtime, monkeypatch):
    runs, requests = runtime
    verdicts(monkeypatch, [('passed', [])])
    runs += [sse(candidate_events('one', '<p id="out">Period</p>', 'function f( {', ['f()'])),
             sse(candidate_events('two', '<p id="out">Period 2.0 s</p>', 'function f(){}', ['f()']))]
    result, progress = run_generate()
    assert [value.content['html'] for value in result] == [['<p id="out">Period 2.0 s</p>']]
    first, second = agent_runs(requests)
    assert first['body']['threadId'] == second['body']['threadId'] == 'job_test'
    assistant, tool = second['body']['messages'][-2:]
    assert assistant['id'] == 'ai_one' and assistant['role'] == 'assistant'
    assert assistant['toolCalls'][0]['id'] == 'call_one'
    assert json.loads(assistant['toolCalls'][0]['function']['arguments'])['jsFunctions'] == 'function f( {'
    assert tool['role'] == 'tool' and tool['toolCallId'] == 'call_one'
    assert tool['content'].startswith('Open Learn tested this visual')
    assert 'SyntaxError' in tool['content']
    assert [item['stage'] for item in progress] == ['generating', 'verifying', 'repairing', 'generating', 'verifying']
    assert result[0].verification['status'] == 'passed'


def test_runtime_failure_feedback_reaches_the_model_and_failures_never_publish(runtime, monkeypatch):
    runs, requests = runtime
    verdicts(monkeypatch, [('failed', ERROR), ('passed', [])])
    runs += [sse(candidate_events('one', '<canvas id="c"></canvas>', 'function f(){}', ['f()'])),
             sse(candidate_events('two', '<canvas id="c"></canvas><p>fixed</p>', 'function f(){}', ['f()']))]
    result, _ = run_generate()
    assert len(result) == 1 and 'fixed' in result[0].content['html'][0]
    assert 'ReferenceError: colr is not defined' in agent_runs(requests)[1]['body']['messages'][-1]['content']


def test_polish_attempt_that_regresses_falls_back_to_the_working_candidate(runtime, monkeypatch):
    runs, _ = runtime
    verdicts(monkeypatch, [('passed', WARN), ('failed', ERROR)])
    runs += [sse(candidate_events('one', '<p>working</p>', 'function f(){}', ['f()'])),
             sse(candidate_events('two', '<p>regressed</p>', 'function f(){}', ['f()']))]
    result, progress = run_generate()
    assert result[0].content['html'] == ['<p>working</p>']
    assert progress[2] == {'attempt': 1, 'maxAttempts': 3, 'stage': 'repairing', 'findings': ['unresponsive_control']}


def test_polish_can_be_disabled(runtime, monkeypatch):
    runs, requests = runtime
    monkeypatch.setenv('OPENLEARN_VISUAL_POLISH_WARNINGS', 'off')
    verdicts(monkeypatch, [('passed', WARN)])
    runs.append(sse(candidate_events('one', '<p>working</p>', 'function f(){}', ['f()'])))
    result, _ = run_generate()
    assert result[0].content['html'] == ['<p>working</p>'] and len(agent_runs(requests)) == 1


def test_attempt_budget_is_bounded_and_reports_a_fixed_code(runtime, monkeypatch):
    runs, requests = runtime
    monkeypatch.setenv('OPENLEARN_VISUAL_MAX_ATTEMPTS', '2')
    verdicts(monkeypatch, [('failed', ERROR), ('failed', ERROR)])
    runs += [sse(candidate_events(name, '<p>x</p>', 'function f(){}', ['f()'])) for name in ('one', 'two')]
    with pytest.raises(ValueError, match='^visual_runtime_failed$'):
        run_generate()
    assert len(agent_runs(requests)) == 2


def test_text_decision_ends_without_candidates(runtime, monkeypatch):
    runs, requests = runtime
    verdicts(monkeypatch, [])
    runs.append(sse([{'type': 'RUN_STARTED'}, {'type': 'STATE_SNAPSHOT', 'snapshot': {'visualization_decision': {'renderer': 'text'}}},
                     {'type': 'RUN_FINISHED'}]))
    result, _ = run_generate()
    assert result == [] and len(requests) == 1


def test_provider_stall_is_retried_within_the_attempt_budget(runtime, monkeypatch):
    runs, requests = runtime
    verdicts(monkeypatch, [('passed', [])])
    runs += [sse([{'type': 'RUN_STARTED'}, {'type': 'RUN_ERROR', 'message': 'StreamChunkTimeoutError'}]),
             sse(candidate_events('two', '<p>ok</p>', 'function f(){}', ['f()']))]
    result, _ = run_generate()
    assert result[0].content['html'] == ['<p>ok</p>']
    first, second = agent_runs(requests)
    # The retry replays the original input: no tool result for a call that never completed.
    assert second['body']['messages'] == first['body']['messages']


@pytest.mark.parametrize('error', ['StreamChunkTimeoutError', "{'code': 'usage_window_exhausted'}"])
def test_provider_failure_during_polish_publishes_the_verified_candidate(runtime, monkeypatch, error):
    runs, requests = runtime
    verdicts(monkeypatch, [('passed', WARN)])
    runs += [sse(candidate_events('one', '<p>working</p>', 'function f(){}', ['f()'])),
             sse([{'type': 'RUN_STARTED'}, {'type': 'RUN_ERROR', 'message': error}])]
    result, _ = run_generate()
    assert result[0].content['html'] == ['<p>working</p>']
    assert len(agent_runs(requests)) == 2


def test_empty_provider_response_is_retried(runtime, monkeypatch):
    runs, requests = runtime
    verdicts(monkeypatch, [('passed', [])])
    runs += [sse([{'type': 'RUN_STARTED'}, {'type': 'STATE_SNAPSHOT', 'snapshot': {'visualization_decision': {'renderer': 'open_generative_ui'}}},
                  {'type': 'RUN_FINISHED'}]),
             sse(candidate_events('two', '<p>ok</p>', 'function f(){}', ['f()']))]
    result, _ = run_generate()
    assert result[0].content['html'] == ['<p>ok</p>']
    first, second = agent_runs(requests)
    assert second['body']['messages'] == first['body']['messages']


def test_usage_exhaustion_is_final(runtime, monkeypatch):
    runs, requests = runtime
    verdicts(monkeypatch, [])
    runs.append(sse([{'type': 'RUN_ERROR', 'message': "{'code': 'usage_window_exhausted'}"}]))
    with pytest.raises(ValueError, match='^visual_usage_window_exhausted$'):
        run_generate()
    assert len(agent_runs(requests)) == 1


def test_dynamic_dom_is_left_to_runtime_verification_when_available(monkeypatch):
    monkeypatch.setattr('backend.app.visual_verification.unavailable_reason', lambda: None)
    value = GeneratedVisual(id='one', renderer='open_generative_ui', title='Visual', content={
        'generating': False, 'htmlComplete': True, 'html': ['<div id="app"></div>'],
        'jsFunctions': 'function f(){document.getElementById("later").textContent=1}', 'jsExpressions': ['f()']})
    assert static_candidate(value).content['html'] == ['<div id="app"></div>']
    monkeypatch.setattr('backend.app.visual_verification.unavailable_reason', lambda: 'assets_missing')
    with pytest.raises(ValueError, match='missing_dom_target'):
        static_candidate(value)
