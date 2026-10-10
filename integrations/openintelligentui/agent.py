"""Pinned upstream visual graph with Open Learn's provider/auth boundary."""
import os
import sys
from contextvars import ContextVar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = Path(os.getenv('OPENLEARN_OPENINTELLIGENTUI_ROOT', Path(__file__).parent / 'upstream'))
sys.path.insert(0, str(UPSTREAM / 'apps/agent'))
sys.path.insert(0, str(ROOT))

os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'

from fastapi import FastAPI
from starlette.responses import JSONResponse
from langsmith import tracing_context
from langchain_openai import ChatOpenAI
from langchain.agents.middleware import AgentMiddleware
from copilotkit import CopilotKitMiddleware, LangGraphAGUIAgent
from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from deepagents import create_deep_agent
from src import model as upstream_model
from src import visualization_router as upstream_router
from src.anthropic_compat import ConsecutiveSystemMessagesMiddleware
from src.bounded_memory_saver import BoundedMemorySaver
from src.skill_backend import SKILL_SOURCES, build_agent_backend, _SKILL_TEXT
from src.prompt import SYSTEM_PROMPT
from src.trip_images import get_trip_stop_images
from src.plan import plan_visualization
import base64
import hashlib
import hmac
import json
import time
import re
ADAPTER_REVISION=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]

API_ORIGIN = os.getenv('OPENLEARN_VISUAL_API_ORIGIN', 'http://127.0.0.1:8000')
if not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{2,5}', API_ORIGIN):
    raise ValueError('Visual provider proxy must stay on loopback')


def verify_ticket(value):
    secret = os.getenv('OPENLEARN_VISUAL_INTERNAL_SECRET', '')
    encoded, signature = value.split('.', 1)
    expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if len(secret) < 32 or len(value) > 2000 or not hmac.compare_digest(signature, expected):
        raise ValueError('visual_unauthorized')
    claim = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    if claim['exp'] <= time.time():
        raise ValueError('visual_unauthorized')
    return claim


def capability():
    missing = [key for key in ('OPENLEARN_VISUAL_INTERNAL_SECRET',) if not os.getenv(key)]
    return {'configured': not missing, 'missingFields': missing,
            'model': os.getenv('OPENLEARN_VISUAL_MODEL') or os.getenv('OPENROUTER_MODEL', 'openrouter/free')}

current_ticket = ContextVar('openlearn_visual_ticket', default=None)
original_options = upstream_router.request_options


def request_model(_fallback):
    ticket = current_ticket.get()
    if not ticket:
        raise ValueError('visual_unauthorized')
    return ChatOpenAI(model=capability()['model'], api_key=ticket,
        base_url=API_ORIGIN+'/internal/visuals/model/v1',
        max_tokens=8192, max_retries=0, streaming=True, stream_usage=True,
        timeout=90, openai_proxy='',
        http_client=__import__('httpx').Client(trust_env=False),
        http_async_client=__import__('httpx').AsyncClient(trust_env=False))


def routing_options(context):
    # Preserve upstream criteria and instructions while moving auth/billing to the host.
    # The placeholder is never sent to the provider; its header is replaced below.
    from src.credentials import current_credentials, Credentials
    token = current_credentials.set(Credentials('internal', 'internal'))
    try:
        options = original_options(context)
    finally:
        current_credentials.reset(token)
    options['headers'] = {'Authorization': 'Bearer ' + current_ticket.get()}
    model = os.getenv('OPENLEARN_VISUAL_JEV_MODEL', 'typesafe/jev-1.13').strip()
    options['json']['model'] = {'jev-latest': '~typesafe/jev-latest', 'jev-1.13': 'typesafe/jev-1.13'}.get(model, model)
    return options


upstream_model.request_model = request_model
upstream_router.request_options = routing_options
upstream_router.JEV_URL = API_ORIGIN+'/internal/visuals/jev'
upstream_router.provider_trust_env = lambda: False

# Preserve the bundled geographic skill while replacing CDN fetching with the
# reviewed local module and stylesheet supplied by the host renderer.
skill = _SKILL_TEXT['/advanced-visualization/SKILL.md']
start = skill.index('Load Leaflet 1.9.4 from')
end = skill.index('Use L.circleMarker', start)
_SKILL_TEXT['/advanced-visualization/SKILL.md'] = skill[:start] + 'Load the locally bundled Leaflet 1.9.4 with `const {default:L}=await import("leaflet")`. Its CSS is already present in the frame. Do not fetch CSS or load CDN scripts.\n' + skill[end:]


class VisualToolsOnly(AgentMiddleware):
    async def awrap_tool_call(self, request, handler):
        if request.tool_call.get('name') == 'generateSandboxedUi':
            from backend.app.visual_code import validate_visual_code
            from langchain.messages import ToolMessage
            args=request.tool_call.get('args',{})
            content={key:args[key] for key in ('css','html','jsFunctions','jsExpressions') if key in args}
            if isinstance(content.get('html'),str):content['html']=[content['html']]
            try:
                validate_visual_code(content)
                code=args.get('jsFunctions','')+'\n'+'\n'.join(args.get('jsExpressions',[]))
                if re.search(r'\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\s*\(',code):raise ValueError('visual_network_request_unsupported')
            except ValueError as error:
                attempts=sum(1 for message in request.state.get('messages',[]) for call in getattr(message,'tool_calls',[]) if call.get('name')=='generateSandboxedUi')
                if attempts>=3:raise ValueError('visual_validation_attempt_limit')
                return ToolMessage(content='Visual validation failed: '+str(error)+'. Correct the JavaScript and exact HTML element IDs, remove unsupported network calls, then call generateSandboxedUi with the complete corrected artifact. Do not claim success.',tool_call_id=request.tool_call['id'],status='error')
        return await handler(request)

    def wrap_model_call(self, request, handler):
        return handler(self.limit(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self.limit(request))

    @staticmethod
    def limit(request):
        allowed = {'read_file', 'ls', 'glob', 'grep', 'generateSandboxedUi',
                   'render_a2ui', 'send_a2ui_json_to_client', 'generate_a2ui', 'get_trip_stop_images','plan_visualization'}
        tools = [tool for tool in request.tools if (tool.get('name') if isinstance(tool, dict) else tool.name) in allowed]
        import logging
        logging.getLogger(__name__).warning('Visual model tools: %s; presentation: %s',
            [tool.get('name') if isinstance(tool, dict) else tool.name for tool in tools],
            (request.state.get('visualization_decision') or {}).get('renderer'))
        render_names={'generateSandboxedUi','render_a2ui','send_a2ui_json_to_client','generate_a2ui'}
        calls={call['id'] for message in request.state.get('messages',[]) for call in getattr(message,'tool_calls',[]) if call.get('name') in render_names}
        published=any(getattr(message,'tool_call_id',None) in calls and getattr(message,'status','success')!='error' for message in request.state.get('messages',[]))
        decision=request.state.get('visualization_decision') or {}
        needs_visual=decision.get('renderer') in {'a2ui','open_generative_ui'}
        # A visual producer must actually call a render tool before finishing;
        # prose containing code is not a rendered artifact. Data/skill tools
        # remain available while gathering context. The graph limit bounds it.
        choice=request.tool_choice
        system=request.system_message
        messages=[]
        for message in request.messages:
            original_calls=getattr(message,'tool_calls',[])
            if original_calls:
                compact=[]
                for call in original_calls:
                    if call.get('name')=='generateSandboxedUi':
                        # Tool arguments are output code, not fresh evidence.
                        # Rebuild from the original grounded brief and the typed
                        # validation error instead of echoing unbounded failed code.
                        args=call.get('args',{})
                        compact.append(call|{'args':{'html':str(args.get('html',''))[:1000],
                            'css':str(args.get('css',''))[:500],
                            'jsFunctions':'/* Prior code omitted; rebuild using grounded data and validation feedback. */'}})
                    else:compact.append(call)
                message=message.model_copy(update={'tool_calls':compact,'additional_kwargs':{key:value for key,value in message.additional_kwargs.items() if key!='tool_calls'}})
            messages.append(message)
        if needs_visual and not published:
            names={tool.get('name') if isinstance(tool,dict) else tool.name for tool in tools}
            chosen='generateSandboxedUi' if decision['renderer']=='open_generative_ui' else 'render_a2ui'
            photo_calls={call['id'] for message in request.state.get('messages',[]) for call in getattr(message,'tool_calls',[]) if call.get('name')=='get_trip_stop_images'}
            if decision.get('visualization')=='animated_route' and not photo_calls:chosen='get_trip_stop_images'
            if chosen in names:choice={'type':'function','function':{'name':chosen}}
            # Some OpenRouter endpoints accept "required" but still emit prose;
            # a specific named tool is tested and enforced instead. Supply the
            # focused skill directly so forced rendering does not skip its guidance.
            if decision['renderer']=='open_generative_ui':
                from langchain.messages import SystemMessage
                skill_name='svg-diagrams' if decision.get('visualization') in {'flowchart','static_diagram'} else 'advanced-visualization'
                guidance=_SKILL_TEXT[f'/{skill_name}/SKILL.md']
                if skill_name=='advanced-visualization':
                    # Do not repeat every unrelated visualization recipe in a
                    # forced tool request. Full skills remain in the read backend.
                    sections=re.split(r'(?=^## )',guidance,flags=re.M)
                    geographic=decision.get('visualization') in {'animated_route','map','geographic_map'}
                    guidance='\n'.join(section for section in sections if
                        not section.startswith(('## Live geographic maps','## Trip itineraries')) or geographic)
                    if geographic:
                        guidance='\n'.join(section for section in sections if
                            section.startswith(('## Streaming','## Live geographic maps','## Trip itineraries')))
                original=system.content if system else ''
                system=SystemMessage(content=original+'\n'+guidance if isinstance(original,str) else [*original,{'type':'text','text':guidance}])
        return request.override(tools=tools,tool_choice=choice,system_message=system,messages=messages)


graph = create_deep_agent(
    model=upstream_model.CredentialScopedModel(fallback=upstream_model.UnconfiguredModel()),
    tools=[get_trip_stop_images,plan_visualization], middleware=[upstream_model.RequestModelMiddleware(), CopilotKitMiddleware(),
        upstream_router.JevVisualizationMiddleware(), ConsecutiveSystemMessagesMiddleware(), VisualToolsOnly()],
    skills=SKILL_SOURCES, backend=build_agent_backend,
    checkpointer=BoundedMemorySaver(max_threads=40),
    system_prompt=SYSTEM_PROMPT + '\n' + (Path(__file__).parent/'design-skill.md').read_text(encoding='utf-8') + '\nYou are Open Learn\'s visual producer. Produce the selected useful visual from the supplied grounded context. '
        'The primary tutor already supplies the explanation: avoid repeating it outside the visual. '
        'No external actions, saved-account claims, credential forms, or fabricated sources. Include units and an accessible text explanation inside the artifact.'
        ' The host import map supports only three, three/addons/controls/OrbitControls.js, gsap, d3, chart.js and leaflet. '
        'Use bare module imports for those libraries or inline SVG and native DOM. Remote scripts and network requests are blocked. Images may use only the USGS tile path and sourced Wikimedia hosts described in the map skill. '
        'Libraries are ES modules, not globals: await import("three") or await import("chart.js") inside an async initialization function; assign the returned exports before using them. Do not assume THREE, Chart, d3, gsap or L are already globals. Call and await initialization from jsExpressions. '
        'Follow-ups use Websandbox.connection.remote.sendPrompt({text}) and links use Websandbox.connection.remote.openLink({url}). '
        'The host asks the learner to review these actions; never claim a follow-up was automatically sent.'
        ' For adjustable numeric inputs, use a unique safe id, aria-label, type range or number, explicit min/max/value, and an input event listener. '
        'Initialize the simulation from await Websandbox.connection.remote.getState().controls when available, otherwise the input value. '
        'Always recompute from input values; never hardcode the original values into the event handler. This lets verified voice updates replay saved numeric state.'
        ' If the rendering tool returns a validation error, fix the named problem and submit the complete corrected visual. Never leave TODOs or placeholder code. Use every DOM ID exactly as declared in HTML.'
)

app = FastAPI(title='Open Learn visual graph')


class TicketMiddleware:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] == '/health':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        value = headers.get(b'x-openlearn-visual-ticket', b'').decode()
        try:
            verify_ticket(value)
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Visual request rejected (ticket present: %s)', bool(value))
            return await JSONResponse({'error': 'visual_unauthorized'}, status_code=401)(scope, receive, send)
        token = current_ticket.set(value)
        try:
            with tracing_context(enabled=False):
                await self.app(scope, receive, send)
        finally:
            current_ticket.reset(token)


app.add_middleware(TicketMiddleware)


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'openlearn-visual-agent', 'capability': capability(),
            'checkpointMode': 'local_bounded_memory','adapterRevision':ADAPTER_REVISION}


add_langgraph_fastapi_endpoint(app=app, agent=LangGraphAGUIAgent(name='openlearn_visuals', description='Open Learn interactive visual producer', graph=graph, config={'recursion_limit': 24}), path='/')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8123, log_level='warning')
