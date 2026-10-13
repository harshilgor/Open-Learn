import json

import httpx
import pytest

import backend.app.model_provider as model_provider
from backend.app.model_provider import ImageInput, ModelProviderError, OpenRouterLessonProvider, configured_lesson_provider
from backend.app.json_context_prompt import bounded_json_prompt
from backend.app.context_engine import GenerationContext
from backend.app.context_engine import ContextBlock, ContextEngine


def lesson_context():
    from types import SimpleNamespace
    from backend.app.learning_policy import resolve_teaching_profile
    from backend.app.session_models import TeachingGear, TeachingIntent
    from backend.app.policy_models import LearnerEvidenceProjection
    return SimpleNamespace(teaching_profile=resolve_teaching_profile(TeachingGear.quick,TeachingIntent.teach),
                           branch_id=None,request_message='Volcanoes',
                           learner_evidence=LearnerEvidenceProjection(learner_id='alice',state_version=0))


def test_stream_stops_at_completion_and_voice_requests_fast_free_response(monkeypatch):
    import asyncio
    sent = {}
    class Response:
        def raise_for_status(self): pass
        async def aiter_lines(self):
            yield 'data: '+json.dumps({'choices':[{'delta':{'content':'A short explanation.'}}]})
            yield 'data: '+json.dumps({'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':4}})
            yield 'data: [DONE]'
            raise AssertionError('Read beyond the terminal provider event')
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        def stream(self,*args,**kwargs): sent.update(kwargs['json']);return Response()
    monkeypatch.setattr(httpx,'AsyncClient',Client)
    provider=OpenRouterLessonProvider('test-key','openrouter/free',None,None)
    async def collect():
        return ''.join([value async for value in provider.stream_text('Teach briefly.',max_tokens=100,prefer_fast_response=True)])
    assert asyncio.run(collect()) == 'A short explanation.'
    assert sent['model'] == 'openrouter/free'
    assert sent['reasoning'] == {'enabled':False}
    assert provider.last_usage is not None


def test_openrouter_provider_parses_structured_lesson(monkeypatch):
    provider = OpenRouterLessonProvider("test-key", "openai/gpt-4o", None, None)
    response = httpx.Response(200, request=httpx.Request("POST", "https://example.test"), json={"choices": [{"message": {"content": json.dumps({"blocks": [
        {"kind": "lesson", "heading": "Core idea", "body": "A careful explanation."},
        {"kind": "check", "heading": "Try it", "body": "What would change?"},
    ]})}}]})
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)
    blocks = provider.generate(graph=None, concept=type("Concept", (), {"title": "Volcanoes"})(), context=lesson_context(), plan=type("Plan", (), {"strategy": type("S", (), {"value": "direct_explanation"})(), "representation_sequence": ["intuition"]})(), intent=type("I", (), {"value": "teach"})())
    assert [block.kind for block in blocks] == ["explanation", "check"]


@pytest.mark.parametrize("openai", [False, True])
def test_json_context_uses_provider_native_roles(monkeypatch, openai):
    provider = OpenRouterLessonProvider.openai("key", "model") if openai else OpenRouterLessonProvider("key", "model", None, None)
    request = bounded_json_prompt(provider, "Follow schema.", {"schema": {"type": "object"}, "source": "untrusted data"},
                                  required={"schema", "source"})
    assert isinstance(request, GenerationContext)
    sent = {}
    def post(*args, **kwargs):
        sent.update(kwargs["json"])
        if openai:
            return httpx.Response(200, request=httpx.Request("POST", "https://example.test"), json={"output_text": '{"ok":true}'})
        return httpx.Response(200, request=httpx.Request("POST", "https://example.test"), json={"choices": [{"message": {"content": '{"ok":true}'}}]})
    monkeypatch.setattr(httpx, "post", post)
    assert provider.complete_json(request) == {"ok": True}
    if openai:
        assert "Follow schema." in sent["instructions"]
        messages = sent["input"]
    else:
        assert "Follow schema." in sent["messages"][0]["content"]
        messages = sent["messages"][1:]
    assert "untrusted data" in messages[0]["content"]
    assert messages[-1]["content"] == "Generate the requested JSON response."


def test_openrouter_provider_rejects_invalid_blocks(monkeypatch):
    provider = OpenRouterLessonProvider("test-key", "openai/gpt-4o", None, None)
    response = httpx.Response(200, request=httpx.Request("POST", "https://example.test"), json={"choices": [{"message": {"content": '{"blocks": []}'}}]})
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)
    with pytest.raises(ModelProviderError):
        provider.generate(graph=None, concept=type("Concept", (), {"title": "Volcanoes"})(), context=lesson_context(), plan=type("Plan", (), {"strategy": type("S", (), {"value": "direct_explanation"})(), "representation_sequence": ["intuition"]})(), intent=type("I", (), {"value": "teach"})())


def test_openrouter_provider_uses_explanation_for_unknown_presentation_kind(monkeypatch):
    provider = OpenRouterLessonProvider("test-key", "openai/gpt-4o", None, None)
    response = httpx.Response(200, request=httpx.Request("POST", "https://example.test"), json={"choices": [{"message": {"content": json.dumps({"blocks": [
        {"kind": "concept", "heading": "Core idea", "body": "A careful explanation."},
        {"kind": "check", "heading": "Try it", "body": "What would change?"},
    ]})}}]})
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)
    blocks = provider.generate(graph=None, concept=type("Concept", (), {"title": "Volcanoes"})(), context=lesson_context(), plan=type("Plan", (), {"strategy": type("S", (), {"value": "direct_explanation"})(), "representation_sequence": ["intuition"]})(), intent=type("I", (), {"value": "teach"})())
    assert blocks[0].kind == "explanation"


def test_openrouter_requires_a_key(monkeypatch):
    monkeypatch.setenv("AI_TUTOR_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(model_provider, "load_dotenv", lambda *args, **kwargs: False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        configured_lesson_provider()


def test_free_nemotron_accepts_long_fenced_json_without_response_format(monkeypatch):
    provider = OpenRouterLessonProvider("test-key", "nvidia/nemotron-3-ultra-550b-a55b:free", None, None)
    content = json.dumps({"blocks": [{"kind": "explanation", "heading": f"Section {i}", "body": "A detailed paragraph."} for i in range(10)]})
    def post(*args, **kwargs):
        assert "response_format" not in kwargs["json"]
        assert kwargs["json"]["reasoning"] == {"enabled": False}
        return httpx.Response(200, request=httpx.Request("POST", "https://example.test"), json={"choices": [{"finish_reason": "stop", "message": {"content": f"```json\n{content}\n```"}}]})
    monkeypatch.setattr(httpx, "post", post)
    assert len(provider._complete("Write a full lesson", 3600)) == 10


@pytest.mark.parametrize("kind", [[], {}, None])
def test_provider_rejects_non_string_kinds(monkeypatch, kind):
    content = json.dumps({"blocks": [{"kind": kind, "heading": "Heading", "body": "Body"}] * 2})
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(200, request=httpx.Request("POST", "https://example.test"), json={"choices": [{"message": {"content": content}}]}))
    with pytest.raises(ModelProviderError, match="invalid lesson block"):
        OpenRouterLessonProvider("key", "model", None, None)._complete("prompt", 1000)


def test_provider_rejects_truncated_output(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(200, request=httpx.Request("POST", "https://example.test"), json={"choices": [{"finish_reason": "length", "message": {"content": '{"blocks":'}}]}))
    with pytest.raises(ModelProviderError, match="response limit"):
        OpenRouterLessonProvider("key", "model", None, None)._complete("prompt", 1000)


def test_provider_never_uses_reasoning_as_final_answer(monkeypatch):
    hidden = json.dumps({"blocks": [{"kind": "explanation", "heading": "Private", "body": "Internal reasoning must never become an answer."}]})
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(200, request=httpx.Request("POST", "https://example.test"), json={"choices": [{"message": {"content": None, "reasoning_content": hidden}}]}))
    with pytest.raises(ModelProviderError):
        OpenRouterLessonProvider("key", "model", None, None)._complete("prompt", 1000)


def test_responses_incomplete_is_not_presented_as_a_complete_explanation(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(200, request=httpx.Request("POST", "https://example.test"), json={"status": "incomplete", "output_text": '{"blocks":[]}'}))
    with pytest.raises(ModelProviderError, match="response limit"):
        OpenRouterLessonProvider.openai("key", "model")._complete("prompt", 1000)


@pytest.mark.parametrize("status, message", [(402, "credits"), (429, "free request limit"), (404, "available endpoint")])
def test_provider_reports_actionable_errors(monkeypatch, status, message):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(status, request=httpx.Request("POST", "https://example.test")))
    with pytest.raises(ModelProviderError, match=message):
        OpenRouterLessonProvider("key", "model", None, None)._complete("prompt", 1000)


def test_openai_streaming_payload_contains_real_image_input():
    provider = OpenRouterLessonProvider.openai("key", "gpt-4.1-mini")
    payload = provider.streaming_payload("Explain the diagram", 500, [ImageInput("image/png", b"png", "diagram")])
    content = payload["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "Explain the diagram"}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")


def test_openrouter_streaming_payload_contains_real_image_input():
    provider = OpenRouterLessonProvider("key", "vision-model", None, None)
    payload = provider.streaming_payload("Explain the photo", 500, [ImageInput("image/jpeg", b"jpeg", "photo")])
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.parametrize("openai", [False, True])
def test_structured_streaming_payload_preserves_context_role_order_and_current_turn(openai):
    provider = OpenRouterLessonProvider.openai("key", "model") if openai else OpenRouterLessonProvider("key", "model", None, None)
    turns = [{"question": f"Question {index}", "lesson": {"blocks": [{"body": f"Answer {index}"}]}} for index in range(3)]
    context = ContextEngine(input_budget_tokens=3000).build_generation_context(
        instructions="Tutor instructions", current_user_message="My latest correction",
        candidates=[ContextBlock("course", {"courseId": "course-1", "goal": "Algebra"}, "course", 1)],
        turns=turns,
    )
    payload = provider.streaming_payload(context, 500)
    messages = payload["input"] if openai else payload["messages"]
    if not openai:
        assert messages[0] == {"role": "system", "content": "Tutor instructions"}
        messages = messages[1:]
    else:
        assert payload["instructions"] == "Tutor instructions"
    assert messages[0]["role"] == "user" and '"courseId": "course-1"' in messages[0]["content"]
    assert [(item["role"], item["content"]) for item in messages[1:-1]] == [
        ("user", "Question 0"), ("assistant", "Answer 0"),
        ("user", "Question 1"), ("assistant", "Answer 1"),
        ("user", "Question 2"), ("assistant", "Answer 2"),
    ]
    assert messages[-1] == {"role": "user", "content": "My latest correction"}
