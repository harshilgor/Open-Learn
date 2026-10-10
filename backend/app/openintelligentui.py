"""OpenIntelligentUI adapter. Open Learn owns identity, persistence and billing.

The sidecar carries upstream CopilotKit/AG-UI events; it never receives provider
credentials. All provider requests pass through the authenticated internal proxy.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import json
import os
import time
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import math
import re
from typing import Any, Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import Field, model_validator

from .identity import fail
from .material_routes import material_owner
from .session_models import ApiModel

UPSTREAM_COMMIT = "f6e4388b26a64b9a0714943b08a1ce622b924eec"
MAX_CONTENT_BYTES = 512_000
CONTENT_KEYS = {"initialHeight", "generating", "css", "cssComplete", "html", "htmlComplete",
                "jsFunctions", "jsFunctionsComplete", "jsExpressions", "jsExpressionsComplete"}
JEV_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"


def jev_model() -> str:
    model = os.getenv("OPENLEARN_VISUAL_JEV_MODEL", "typesafe/jev-1.13").strip()
    # Normalize the original TypeSafe model names from existing local configs.
    return {"jev-latest": "~typesafe/jev-latest", "jev-1.13": "typesafe/jev-1.13"}.get(model, model)


def jev_payload(payload: dict) -> dict:
    questions = payload.get("questions")
    if (jev_model() not in {"typesafe/jev-1.13", "~typesafe/jev-latest"}
        or payload.get("model") != jev_model() or not isinstance(questions, dict)
        or set(questions) != {"visualization"} or not isinstance(questions["visualization"], dict)
        or questions["visualization"].get("type") != "choice" or "state" not in payload):
        fail("visual_router_denied", "That visual routing request is unavailable.", 403)
    return {key: payload[key] for key in ("model", "state", "questions")}


def jev_receipt(result: dict) -> tuple[int | None, dict | None]:
    from .usage.pricing import dollars_to_nano
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return None, None
    quantities = {name: usage[key] for name, key in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"))
                  if isinstance(usage.get(key), int) and not isinstance(usage[key], bool) and usage[key] >= 0}
    try:
        if isinstance(usage.get("cost"), bool) or usage.get("cost") is None:
            raise ValueError()
        cost = Decimal(str(usage["cost"]))
        if not cost.is_finite() or cost < 0:
            raise ValueError()
        return dollars_to_nano(str(cost)), quantities or None
    except (InvalidOperation, ValueError, TypeError):
        return None, quantities or None


def enabled() -> bool:
    return os.getenv("OPENLEARN_VISUAL_ENGINE", "legacy") == "openintelligentui"


def capability() -> dict:
    missing = [name for name in ("OPENROUTER_API_KEY", "OPENLEARN_VISUAL_INTERNAL_SECRET")
               if not os.getenv(name, "").strip()]
    if jev_model() not in {"typesafe/jev-1.13", "~typesafe/jev-latest"}:
        missing.append("OPENLEARN_VISUAL_JEV_MODEL")
    # First integration is intentionally local until the migration acceptance gates pass.
    local = os.getenv("AI_TUTOR_ENV", "development") in {"development", "local", "test"}
    hosted = os.getenv('OPENLEARN_VISUAL_HOSTED_ENABLED','false') == 'true'
    selected_model=os.getenv('OPENLEARN_VISUAL_MODEL') or os.getenv('OPENROUTER_MODEL','openrouter/free')
    if selected_model!='openrouter/free' and not selected_model.endswith(':free'):
        try:
            from .visual_pricing import approved_visual_tariff
            from .usage.policy import Policy
            approved_visual_tariff(selected_model)
            if not Policy.load().paid:missing.append('OPENLEARN_USAGE_PAID_ROUTES_ENABLED')
        except (ValueError,KeyError,TypeError,RuntimeError):
            missing.append('OPENLEARN_VISUAL_MODEL_TARIFFS')
    return {"engine": "openintelligentui", "enabled": enabled(), "configured": not missing and (local or hosted),
            "missingFields": missing, "localOnly": not hosted, "upstreamCommit": UPSTREAM_COMMIT,
            "jevProvider": "openrouter", "jevModel": jev_model(),
            "model": selected_model}


def issue_ticket(owner: str, generation_id: str, lease: str | None = None) -> str:
    secret = os.getenv("OPENLEARN_VISUAL_INTERNAL_SECRET", "")
    if len(secret) < 32:
        raise ValueError("visual_internal_auth_unavailable")
    payload = json.dumps({"owner": owner, "generationId": generation_id, "lease": lease,
                          "exp": int(time.time()) + 240}, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + signature


def verify_ticket(value: str) -> dict:
    try:
        secret = os.getenv("OPENLEARN_VISUAL_INTERNAL_SECRET", "")
        encoded, signature = value.split(".", 1)
        if len(secret) < 32 or len(value) > 2000:
            raise ValueError()
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError()
        result = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if result["exp"] <= time.time() or not all(isinstance(result[k], str) and result[k] for k in ("owner", "generationId")):
            raise ValueError()
        return result
    except (ValueError, KeyError, TypeError):
        fail("visual_unauthorized", "This visual request is not authorized.", 401)


class VisualControl(ApiModel):
    id: str = Field(max_length=64, pattern=r'^[A-Za-z][A-Za-z0-9_-]*$')
    label: str = Field(min_length=1, max_length=120)
    minimum: float = Field(allow_inf_nan=False, ge=-10000, le=10000)
    maximum: float = Field(allow_inf_nan=False, ge=-10000, le=10000)
    initial: float = Field(allow_inf_nan=False, ge=-10000, le=10000)

    @model_validator(mode='after')
    def bounds(self):
        if not self.minimum < self.maximum or not self.minimum <= self.initial <= self.maximum:
            raise ValueError('visual_control_bounds')
        return self


def extract_controls(html: str) -> list[VisualControl]:
    controls = []
    ids = set()
    class Inputs(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag != 'input' or len(controls) >= 8:
                return
            values = dict(attrs)
            identifier = values.get('id', '')
            if values.get('type') not in {'range', 'number'} or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', identifier) or identifier in ids:
                return
            try:
                control = VisualControl(id=identifier, label=values.get('aria-label') or identifier,
                    minimum=float(values['min']), maximum=float(values['max']), initial=float(values.get('value', values['min'])))
                controls.append(control); ids.add(identifier)
            except (ValueError, KeyError, TypeError):
                return
    Inputs().feed(html)
    return controls


class GeneratedVisual(ApiModel):
    version: Literal[2] = 2
    type: Literal["generated_ui"] = "generated_ui"
    renderer: Literal["open_generative_ui", "a2ui"]
    id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    revision: int = Field(default=1, ge=1)
    title: str = Field(min_length=1, max_length=160)
    source_lesson_id: str | None = None
    block_index: int = Field(default=0, ge=0, le=20)
    after_paragraph: int = Field(default=0, ge=0, le=20)
    content: dict[str, Any]
    upstream_commit: str = UPSTREAM_COMMIT
    controls: list[VisualControl] = Field(default_factory=list, max_length=8)
    control_values: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded(self):
        if len(json.dumps(self.content).encode()) > MAX_CONTENT_BYTES:
            raise ValueError("visual_payload_limit")
        if self.renderer == "open_generative_ui":
            if set(self.content) - CONTENT_KEYS:
                raise ValueError("visual_unknown_field")
            for key in ("generating", "cssComplete", "htmlComplete", "jsFunctionsComplete", "jsExpressionsComplete"):
                if key in self.content and not isinstance(self.content[key], bool):
                    raise ValueError("visual_invalid_progress")
            height = self.content.get("initialHeight")
            if height is not None and (isinstance(height, bool) or not isinstance(height, (int, float)) or not 50 <= height <= 4000):
                raise ValueError("visual_invalid_height")
            for key in ("html", "jsExpressions"):
                if key in self.content and (not isinstance(self.content[key], list) or
                                           len(self.content[key]) > 5000 or not all(isinstance(v, str) for v in self.content[key])):
                    raise ValueError("visual_invalid_chunks")
            for key in ("css", "jsFunctions"):
                if key in self.content and not isinstance(self.content[key], str):
                    raise ValueError("visual_invalid_code")
        for identifier, value in self.control_values.items():
            control = next((control for control in self.controls if control.id == identifier), None)
            if control is None or not math.isfinite(value) or not control.minimum <= value <= control.maximum:
                raise ValueError('visual_control_value')
        return self


class ActivityCollector:
    """Reduce the pinned runtime's activity snapshots and JSON-Patch deltas.

    Do not evaluate model code. Final code remains data until the isolated renderer.
    """
    def __init__(self, title: str):
        self.title = title[:160] or "Interactive explanation"
        self.values: dict[str, GeneratedVisual] = {}
        self.finished = False
        self.render_calls: set[str] = set()
        self.decision: dict = {}
        self.event_counts: dict[str, int] = {}
        self.snapshot_seen: set[str] = set()
        self.plan = None
        self.plan_arguments = {}

    def accept(self, event: dict) -> GeneratedVisual | None:
        event_type = event.get("type")
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1
        if event_type == 'TOOL_CALL_START':
            self.render_calls.add(str(event.get('toolCallName', '')))
            if event.get('toolCallName')=='plan_visualization' and len(self.plan_arguments)<8:
                self.plan_arguments[str(event.get('toolCallId',''))]=''
        tool_id=str(event.get('toolCallId',''))
        if event_type=='TOOL_CALL_ARGS' and tool_id in self.plan_arguments:
            self.plan_arguments[tool_id]+=str(event.get('delta',''))
            if len(self.plan_arguments[tool_id])>4096:self.plan_arguments.pop(tool_id)
        if event_type=='TOOL_CALL_END' and tool_id in self.plan_arguments:
            try:
                plan=json.loads(self.plan_arguments.pop(tool_id))
                if isinstance(plan.get('approach'),str) and isinstance(plan.get('technology'),str) and isinstance(plan.get('key_elements'),list):
                    self.plan={'approach':plan['approach'][:500],'technology':plan['technology'][:80],
                               'keyElements':[item[:120] for item in plan['key_elements'][:4] if isinstance(item,str)]}
            except (ValueError,TypeError,AttributeError):pass
        if event_type == 'STATE_SNAPSHOT':
            self.decision = event.get('snapshot', {}).get('visualization_decision') or self.decision
        if event_type == "RUN_ERROR":
            # Preserve only fixed transport policy codes, never provider text,
            # request contents or exception details in learner-facing records.
            message=str(event.get('message',''))[:12000]
            for code in ('usage_window_exhausted','usage_input_limit','usage_platform_budget_exhausted'):
                if re.search(r"['\"]code['\"]\s*:\s*['\"]"+code+r"['\"]",message):
                    raise ValueError('visual_'+code)
            raise ValueError("visual_generation_failed")
        if event_type == "RUN_FINISHED":
            self.finished = True
        if event.get("activityType") not in {"open-generative-ui", "a2ui-surface"}:
            return None
        identity = str(event.get("messageId", ""))
        if not identity or len(identity) > 200:
            raise ValueError("visual_invalid_activity")
        identifier = "ogui_" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        if event.get("activityType") == "a2ui-surface":
            operations = event.get("content", {}).get("a2ui_operations", [])
            for operation in operations:
                surface = operation.get("createSurface")
                if surface and surface.get("catalogId") != "copilotkit://open-generative-ui-tables":
                    raise ValueError("visual_catalog_denied")
                for component in operation.get("updateComponents", {}).get("components", []):
                    if component.get("id") == "root" and component.get("component") == "Table":
                        table = {key: component.get(key) for key in ("title", "columns", "rows", "source")}
                        columns, rows = table["columns"], table["rows"]
                        if (not isinstance(columns, list) or not 1 <= len(columns) <= 12 or
                            not all(isinstance(v, str) and len(v) <= 200 for v in columns) or
                            not isinstance(rows, list) or len(rows) > 200 or
                            not all(isinstance(row, list) and len(row) == len(columns) and
                                    all(isinstance(v, str) and len(v) <= 2000 for v in row) for row in rows) or
                            not isinstance(table["source"], str) or not table["source"].strip() or
                            not isinstance(table["title"], str)):
                            raise ValueError("visual_invalid_table")
                        visual = GeneratedVisual(id=identifier, renderer="a2ui", title=self.title, content=table)
                        if len(self.values) >= 2 and identifier not in self.values:
                            raise ValueError("visual_artifact_limit")
                        self.values[identifier] = visual
                        return visual
            return None
        if event_type == "ACTIVITY_SNAPSHOT":
            content = copy.deepcopy(event.get("content", {}))
            # The host supplies truthful progress copy; upstream model-authored
            # placeholder narration is not part of the executable artifact.
            content.pop('placeholderMessages', None)
            if identifier in self.values and identifier not in self.snapshot_seen:
                content = {**self.values[identifier].content, **content}
            self.snapshot_seen.add(identifier)
        elif event_type == "ACTIVITY_DELTA":
            prior = self.values.get(identifier)
            if not prior:
                # Upstream's optional initialHeight is what triggers its first
                # snapshot. A model can omit it and stream css/html deltas first.
                prior = GeneratedVisual(id=identifier, renderer='open_generative_ui', title=self.title, content={'generating':True})
            content = copy.deepcopy(prior.content)
            patches = event.get("patch", [])
            if not isinstance(patches, list) or len(patches) > 20:
                raise ValueError("visual_invalid_patch")
            for patch in patches:
                path = patch.get("path", "")
                if patch.get('op') in {'add', 'replace'} and path in {'/placeholderMessages', '/placeholderMessages/-'}:
                    continue
                pieces = path.split("/")[1:]
                if patch.get("op") not in {"add", "replace"} or not pieces or pieces[0] not in CONTENT_KEYS:
                    raise ValueError("visual_invalid_patch")
                if len(pieces) == 1:
                    content[pieces[0]] = patch.get("value")
                elif len(pieces) == 2 and pieces[0] in {"html", "jsExpressions"} and pieces[1] == "-":
                    content.setdefault(pieces[0], []).append(patch.get("value"))
                else:
                    raise ValueError("visual_invalid_patch")
        else:
            return None
        result = GeneratedVisual(id=identifier, renderer="open_generative_ui", title=self.title, content=content)
        if len(self.values) >= 2 and identifier not in self.values:
            raise ValueError("visual_artifact_limit")
        self.values[identifier] = result
        return result

    def final(self) -> list[GeneratedVisual]:
        import logging
        logging.getLogger(__name__).warning('Visual stream summary: events=%s renderTools=%s presentation=%s',
            self.event_counts, sorted(self.render_calls), self.decision.get('renderer'))
        if not self.finished:
            raise ValueError("visual_stream_interrupted")
        if not self.values and (self.render_calls.intersection({'generateSandboxedUi', 'render_a2ui', 'send_a2ui_json_to_client'}) or self.decision.get('renderer') in {'a2ui', 'open_generative_ui'}):
            raise ValueError('visual_missing_artifact')
        valid_values=[]
        validation_error=None
        for value in self.values.values():
            if value.renderer == "open_generative_ui" and (value.content.get("generating") is not False or not value.content.get("htmlComplete")):
                raise ValueError("visual_incomplete_artifact")
            if value.renderer == 'open_generative_ui':
                from .visual_code import validate_visual_code
                try:
                    value.content = validate_visual_code(value.content)
                except ValueError as error:
                    validation_error=error
                    continue
                code = value.content.get('jsFunctions','')+'\n'+'\n'.join(value.content.get('jsExpressions',[]))
                if re.search(r'\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\s*\(',code):
                    validation_error=ValueError('visual_network_request_unsupported')
                    continue
                if re.search(r'https://\.\.\.|\.\.\. rest of|TODO:|IMPLEMENT_ME',code,re.I):
                    validation_error=ValueError('visual_incomplete_code')
                    continue
                value.controls = extract_controls(''.join(value.content.get('html', [])))
            valid_values.append(value)
        if not valid_values and validation_error:
            raise validation_error
        return valid_values


async def generate(owner: str, generation_id: str, prepared: dict, question: str, emit, emit_plan=None) -> list[GeneratedVisual]:
    if not capability()["configured"]:
        raise ValueError("visual_setup_required")
    ticket = issue_ticket(owner, generation_id, prepared.get('_visualLease'))
    runtime_url = os.getenv("OPENLEARN_VISUAL_RUNTIME_ORIGIN", "http://127.0.0.1:8130").rstrip("/")
    # Local-only first slice: callers cannot redirect an internal grant to an arbitrary origin.
    if runtime_url != "http://127.0.0.1:8130":
        raise ValueError("visual_runtime_origin_invalid")
    brief = {"question": question[:4000], "title": str(prepared.get("title", ""))[:160],
             "sources": [{"id": s.get("spanId"), "title": str(s.get("title", ""))[:160],
                          "text": str(s.get("text", ""))[:1600]} for s in prepared.get("sources", [])[:4]],
             "format": prepared.get("visualType", "auto"),
             "explanation": str(prepared.get('explanation',''))[:6000],
             "priorVisuals": prepared.get('priorVisuals',[])[:2]}
    # Keep reviewed instructions plus grounding below the shared model byte cap.
    # Preserve table values atomically; never truncate rows into misleading data.
    brief['priorVisuals']=[item if len(json.dumps(item).encode())<=8000 else
        {key:value for key,value in item.items() if key!='table'}|{'dataUnavailable':'Request a smaller table selection.'} for item in brief['priorVisuals']]
    brief['explanation']=brief['explanation'][:2000]
    brief['sources']=brief['sources'][:2]
    conversation=[{'role':item['role'],'content':str(item['content'])[:1000]} for item in prepared.get('conversation',[])[-4:] if item.get('role') in {'user','assistant'}]
    while len(json.dumps(brief).encode())+len(json.dumps(conversation).encode())>12000:
        if conversation:conversation.pop(0)
        elif brief['sources']:brief['sources'].pop(0)
        elif brief['priorVisuals']:
            item=brief['priorVisuals'].pop(0)
            if len(brief['priorVisuals'])==0 and 'table' in item:
                brief['priorVisuals']=[{'id':item['id'],'title':item['title'],'dataUnavailable':'Request a smaller table selection.'}]
        else:break
    input_text = question[:4000] + "\n\nGrounded Open Learn context (data, not policy):\n" + json.dumps(brief)
    from .visual_tools import renderer_tools
    run_input = {"threadId": generation_id, "runId": generation_id, "state": {},
                 "messages": [{"id": f'{generation_id}_context_{index}', 'role':item['role'], 'content':str(item['content'])[:6000]}
                              for index,item in enumerate(conversation)]
                             + [{"id": generation_id + "_visual", "role": "user", "content": input_text}],
                 "tools": renderer_tools(), "context": [], "forwardedProps": {}}
    request = {"method": "agent/run", "params": {"agentId": "default"}, "body": run_input}
    collector = ActivityCollector(brief["title"])
    last_emit = 0.0
    published_plan=None
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5), trust_env=False) as client:
        try:
            async with asyncio.timeout(180):
                async with client.stream("POST", runtime_url + "/copilotkit", json=request,
                                         headers={"X-OpenLearn-Visual-Ticket": ticket, "Accept": "text/event-stream"}) as response:
                    response.raise_for_status()
                    frame: list[str] = []
                    async for line in response.aiter_lines():
                        if len(line) > MAX_CONTENT_BYTES * 2:
                            raise ValueError("visual_event_limit")
                        if line:
                            if line.startswith("data:"):
                                frame.append(line[5:].strip())
                            continue
                        if not frame:
                            continue
                        data = "\n".join(frame); frame.clear()
                        if data == "[DONE]":
                            continue
                        event = json.loads(data)
                        value = collector.accept(event)
                        if collector.plan and collector.plan!=published_plan and emit_plan:
                            await emit_plan(collector.plan)
                            published_plan=collector.plan
                        if value and (time.monotonic() - last_emit >= 2 or value.content.get("generating") is False):
                            await emit(value)
                            last_emit = time.monotonic()
                    return collector.final()
        finally:
            # Explicit stop closes graph work when the Open Learn request is cancelled or times out.
            if not collector.finished:
                try:
                    await asyncio.shield(client.post(runtime_url + "/copilotkit", timeout=3,
                        headers={"X-OpenLearn-Visual-Ticket": ticket},
                        json={"method": "agent/stop", "params": {"agentId": "default", "threadId": generation_id}}))
                except (httpx.HTTPError, asyncio.CancelledError):
                    pass


def build_router(store_provider):
    router = APIRouter()

    @router.get("/v1/visual-pipeline/capability")
    def capabilities(owner=Depends(material_owner)):
        return capability()

    @router.get('/v1/lessons/{lesson_id}/visual-runs')
    def visual_runs(lesson_id: str, owner=Depends(material_owner)):
        from .visual_runs import VisualRuns
        return {'runs': VisualRuns(store_provider()).listing(owner, lesson_id)}

    @router.post('/v1/lessons/{lesson_id}/visual-runs', status_code=202)
    async def create_visual_run(lesson_id: str, request: Request,
        key: str = Header(alias='Idempotency-Key', min_length=1, max_length=200), owner=Depends(material_owner)):
        if not enabled() or not capability()['configured']:
            fail('visual_setup_required', 'Interactive visuals are unavailable.', 503)
        payload = await bounded_payload(request)
        question = payload.get('question')
        if not isinstance(question, str) or not question.strip() or len(question) > 4000:
            fail('visual_invalid_input', 'Describe the visual in at most 4000 characters.', 422)
        store = store_provider()
        artifact = store.get_artifact(lesson_id)
        if artifact is None:
            fail('not_found', 'This lesson is unavailable.', 404)
        from .material_service import MaterialService
        MaterialService(store).session(owner, artifact.session_id)
        from .visual_runs import VisualRuns
        with store.transaction() as conn:
            run = VisualRuns(store).admit(conn, owner, artifact.session_id, lesson_id,
                {'title': artifact.title, 'sources': []}, question.strip(), key)
        return {'id': run['id'], 'phase':run['phase']}

    @router.get('/v1/generated-visuals/{visual_id}')
    def generated_visual(visual_id: str, owner=Depends(material_owner)):
        from .workflow_store import WorkflowStore
        store = store_provider()
        value = WorkflowStore(store).read(owner, visual_id, 'generated_visual')
        from .material_service import MaterialService
        MaterialService(store).session(owner, value['sessionId'])
        return value['spec']

    @router.get('/v1/generated-visuals/{visual_id}/revisions')
    def visual_revisions(visual_id: str, owner=Depends(material_owner)):
        from .workflow_store import WorkflowStore
        records = WorkflowStore(store_provider())
        records.read(owner, visual_id, 'generated_visual')
        return {'revisions': [{'id': value['id'], 'revision': value['spec']['revision'], 'title': value['spec']['title']}
                for value in records.listing_by_parent(owner, 'visual_revision', visual_id)]}

    @router.post('/v1/visual-runs/{run_id}/retry', status_code=202)
    def retry_visual(run_id: str, key: str = Header(alias='Idempotency-Key', min_length=1, max_length=200), owner=Depends(material_owner)):
        from .visual_runs import VisualRuns
        value = VisualRuns(store_provider()).retry(owner, run_id, key)
        return {'id': value['id'], 'phase': value['phase']}

    @router.post('/v1/visual-runs/{run_id}/cancel', status_code=202)
    def cancel_visual(run_id: str, owner=Depends(material_owner)):
        from .visual_runs import VisualRuns
        return VisualRuns(store_provider()).cancel(owner, run_id)

    def authorize(authorization: str | None):
        from .generation_store import GenerationStore
        from .material_service import MaterialService
        if not enabled() or not capability()["configured"]:
            fail("visual_setup_required", "Interactive visuals are not configured.", 503)
        claim = verify_ticket((authorization or "").removeprefix("Bearer "))
        store = store_provider()
        if claim['generationId'].startswith('job_'):
            from sqlalchemy import text
            with store.engine.connect() as conn:
                row = conn.execute(text("SELECT * FROM learning_jobs WHERE id=:id AND owner_id=:owner"),
                                   {'id': claim['generationId'], 'owner': claim['owner']}).mappings().first()
            if (not row or row['kind'] != 'visual_generate' or row['status'] != 'running'
                or row['lease'] != claim.get('lease') or row['expires'] <= time.time()
                or row['cancellation_requested'] or row['cancel_requested']):
                fail('visual_run_closed', 'This visual attempt has ended.', 409)
            from .visual_runs import VisualRuns
            VisualRuns(store).read(claim['owner'], row['target_id'])
            return store, claim
        record = GenerationStore(store).get(claim["owner"], claim["generationId"])
        if record["status"] not in {"preparing", "streaming", "finalizing"}:
            fail("visual_run_closed", "This visual run has ended.", 409)
        MaterialService(store).session(claim["owner"], record["session"])
        return store, claim

    async def bounded_payload(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 128_000:
                fail("visual_input_limit", "Narrow the visual request.", 422)
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, TypeError):
            fail("visual_invalid_input", "The visual request is invalid.", 422)

    @router.post("/internal/visuals/model/v1/chat/completions")
    async def model_proxy(request: Request, authorization: str | None = Header(default=None)):
        from .usage.context import usage_scope
        from .usage.transport import begin_model, finish_model
        store, claim = authorize(authorization)
        payload = await bounded_payload(request)
        expected_model = capability()["model"]
        if payload.get("model") != expected_model:
            fail("visual_model_denied", "That visual model is unavailable.", 403)
        if payload.get("stream") is not True:
            fail("visual_stream_required", "Visual models must stream.", 422)
        maximum = payload.get("max_tokens", payload.get("max_completion_tokens", 8192))
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 8192:
            fail("visual_output_limit", "The visual response limit is unsupported.", 422)
        payload.pop("max_completion_tokens", None)
        payload["max_tokens"] = maximum
        # Do not permit LangChain/client options to bypass the reviewed provider transport.
        payload = {k: v for k, v in payload.items() if k in {
            "model", "messages", "tools", "tool_choice", "parallel_tool_calls", "temperature", "max_tokens", "stream"}}
        if payload.get("stream"):
            payload["stream_options"] = {"include_usage": True}
        # Visual production depends on advertised tool parameters. Do not let
        # provider fallback silently discard tool_choice and return code prose.
        payload['provider']={'require_parameters':True}
        import logging
        choice=payload.get('tool_choice')
        choice_label=choice if isinstance(choice,str) else ((choice or {}).get('function',{}).get('name') if isinstance(choice,dict) else 'auto')
        input_bytes=len(json.dumps({key:value for key,value in payload.items() if key not in {'model','stream','stream_options'}},ensure_ascii=False).encode('utf-8'))
        logging.getLogger(__name__).warning('Visual provider model=%s tool_choice=%s tool_count=%d input_bytes=%d',expected_model,choice_label,len(payload.get('tools',[])),input_bytes)
        with usage_scope(store, claim["owner"], "ogui:" + claim["generationId"]):
            ticket = begin_model(payload, store=store, visual_profile=True)

        async def stream():
            receipt = None
            try:
                async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
                    async with client.stream("POST", "https://openrouter.ai/api/v1/chat/completions", json=payload,
                        headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]}) as response:
                        if not response.is_success:
                            import logging
                            logging.getLogger(__name__).warning('Visual model provider HTTP status: %s', response.status_code)
                            yield 'data: {"error":{"message":"Visual model request failed."}}\n\n'
                            return
                        async for line in response.aiter_lines():
                            if line.startswith("data:") and line[5:].strip() != "[DONE]":
                                try:
                                    parsed = json.loads(line[5:])
                                    if isinstance(parsed.get("usage"), dict):
                                        receipt = parsed["usage"]
                                except (ValueError, TypeError):
                                    pass
                            yield line + "\n"
            finally:
                finish_model(ticket, receipt)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    @router.post("/internal/visuals/jev")
    async def jev_proxy(request: Request, authorization: str | None = Header(default=None)):
        from .usage.context import usage_scope
        from .usage.operations import begin_external, finish_external, configured_rate
        store, claim = authorize(authorization)
        payload = jev_payload(await bounded_payload(request))
        # Share the existing JEV tariff snapshot; a competing snapshot for the
        # same model/rate version would be rejected by the usage ledger.
        liability = configured_rate("OPENLEARN_JEV_USD_PER_REQUEST")
        with usage_scope(store, claim["owner"], "ogui:" + claim["generationId"]):
            ticket = begin_external("tool", {"requests": 1}, liability, seconds=20,
                                    provider="openrouter", model=payload["model"],
                                    provider_rates={"usd_nano_per_request": liability, "billing_unit": "request"})
        cost, quantities, receipt_id = None, None, None
        try:
            async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                response = await client.post(JEV_DECISIONS_URL, json=payload,
                    headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]})
            if not response.is_success:
                fail("visual_router_unavailable", "Presentation selection is unavailable. Please retry.", 503)
            result = response.json()
            if not isinstance(result, dict):
                fail("visual_router_unavailable", "Presentation selection returned an invalid response.", 503)
            cost, quantities = jev_receipt(result)
            receipt_id = result.get("id") if isinstance(result.get("id"), str) else None
            return result
        finally:
            finish_external(ticket, quantities=quantities, cost_nano=cost,
                            source="exact" if cost is not None else "estimated",
                            provider="openrouter", model=payload["model"], receipt_id=receipt_id)
    return router
