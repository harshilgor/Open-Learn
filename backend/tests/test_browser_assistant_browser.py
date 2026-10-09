"""Controlled real-browser verification; no university account or live provider."""
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4
import pytest
from backend.app.browser_assistant.contracts import BrowserAction
from backend.app.browser_assistant.executors.cloud import CloudExecutor
from backend.app.browser_assistant.service import AssistantService
from backend.app.browser_assistant.connections import Connections
from backend.app.browser_assistant.contracts import ConnectionCreate,TaskCreate
from backend.app.browser_assistant.policy import authorize_action
from backend.app.browser_assistant.adapters.canvas import platform_script
from test_browser_assistant import environment

@pytest.fixture
def browser_fixture(monkeypatch):
    pw=pytest.importorskip('playwright.sync_api')
    executable=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    if not executable.exists():executable=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')
    if not executable.exists():pytest.skip('Controlled fixture requires the installed Edge browser')
    profile=(Path('work')/('browser-profile-'+uuid4().hex)).resolve();profile.mkdir()
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    process=subprocess.Popen([str(executable),'--headless=new','--no-first-run','--no-default-browser-check','--disable-gpu',f'--remote-debugging-port={port}',f'--user-data-dir={profile}','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    endpoint=f'http://127.0.0.1:{port}'
    with pw.sync_playwright() as driver:
        browser=None
        for _ in range(40):
            try:browser=driver.chromium.connect_over_cdp(endpoint,timeout=500);break
            except Exception:time.sleep(.25)
        assert browser is not None,'Fixture browser did not start'
        page=browser.contexts[0].new_page()
        for extra in browser.contexts[0].pages:
            if extra!=page:extra.close()
        page.goto('about:blank')
        home='''<main><h1>Independent study site</h1><a href="https://unseen.fixture.example/syllabus">Course schedule</a><input type="search" aria-label="Search courses"><div aria-label="Calendar" style="height:120px;overflow:auto" id="lazy"><div style="height:800px">Scroll for more</div></div><script>document.querySelector('#lazy').onscroll=()=>{if(!document.querySelector('#exam'))document.querySelector('#lazy').insertAdjacentHTML('beforeend','<p id="exam">Midterm November 20, 2027</p>')};</script></main>'''
        syllabus='<main><h1>Course syllabus</h1><p>Midterm November 20, 2027</p><button>Submit exam</button></main>'
        def fixture(route):
            url=route.request.url
            if '/users/self/profile' in url:route.fulfill(json={'id':'student-1'})
            elif '/api/v1/courses' in url:route.fulfill(json=[{'id':1,'name':'Biology','enrollments':[{'type':'StudentEnrollment'}],'term':{'id':4},'workflow_state':'available'}])
            else:route.fulfill(status=200,content_type='text/html',body=syllabus if '/syllabus' in url else home)
        page.route('https://*.fixture.example/**',fixture)
        for key in ['OPENLEARN_CLOUD_BROWSER_ENABLED','OPENLEARN_BROWSER_EGRESS_VERIFIED','OPENLEARN_BROWSER_PRIVATE_VERIFIED']:monkeypatch.setenv(key,'true')
        monkeypatch.setenv('BROWSERBASE_API_KEY','fixture-only')
        monkeypatch.setattr('backend.app.url_ingestion.validate_public_url',lambda url:url)
        yield endpoint,page
        browser.close()
    process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
    # Only this test-created, resolved directory is eligible for cleanup.
    assert profile.is_relative_to(Path('work').resolve())
    shutil.rmtree(profile,ignore_errors=True)

def execute_fixture(page,executor,*args):
    # The provider client runs in its worker thread; pump the fixture's routing connection.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(executor.execute,*args)
        while not result.done():page.wait_for_timeout(25)
        return result.result()

class FixtureProvider:
    def __init__(self,endpoint):self.endpoint=endpoint;self.stopped=[]
    def create(self,connection):return {'id':'fixture-session','connectUrl':self.endpoint}
    def stop(self,identifier):self.stopped.append(identifier)


def test_browserbase_provider_uses_api_key_without_project_id(monkeypatch):
    from backend.app.browser_assistant.executors import cloud
    calls=[]
    monkeypatch.setenv('BROWSERBASE_API_KEY','fixture-only')
    monkeypatch.delenv('BROWSERBASE_PROJECT_ID',raising=False)
    monkeypatch.setenv('OPENLEARN_BROWSER_PRIVATE_VERIFIED','true')
    monkeypatch.setattr(cloud,'require_cloud_ready',lambda:{})
    provider=cloud.BrowserbaseProvider()
    def request(method,path,data=None):
        calls.append((method,path,data))
        if path=='contexts':return {'id':'context-1'}
        return {'id':'session-1','connectUrl':'wss://browser.fixture/session'}
    monkeypatch.setattr(provider,'request',request)
    context=provider.create_context('opaque-profile-name')
    session=provider.create({'origin':'https://study.example','approvedOrigins':['https://files.example']},
                            usage_ticket=(None,None,{'component':'browser','liability_nano':1}))
    provider.create({'origin':'https://study.example','approvedOrigins':[],'cloudLogin':True,'providerContextId':context['id']},
                    usage_ticket=(None,None,{'component':'browser','liability_nano':1}))
    provider.create({'origin':'https://study.example','approvedOrigins':[],'cloudLogin':True,'providerContextId':context['id']},
                    usage_ticket=(None,None,{'component':'browser','liability_nano':1}),persist_context=True)
    provider.stop(session['id'])
    assert session['id']=='session-1'
    assert calls[0]==('POST','contexts',{'name':'opaque-profile-name'})
    assert all('projectId' not in body for _,_,body in calls if isinstance(body,dict))
    assert calls[1][0:2]==('POST','sessions')
    assert calls[1][2]['keepAlive'] is False
    assert calls[1][2]['browserSettings']['allowedDomains']==['study.example','files.example']
    assert calls[2][2]['browserSettings']['context']=={'id':'context-1','persist':False}
    assert calls[3][2]['browserSettings']['context']=={'id':'context-1','persist':True}
    assert calls[3][2]['keepAlive'] is True
    assert calls[4]==('POST','sessions/session-1',{'status':'REQUEST_RELEASE'})


def test_cloud_request_guard_allows_public_navigation_but_blocks_private_and_mutating_requests(monkeypatch):
    from backend.app.browser_assistant.executors.cloud import guard_browser_request
    from backend.app import url_ingestion

    class Request:
        def __init__(self, url, method='GET', navigation=False):
            self.url=url;self.method=method;self.navigation=navigation
        def is_navigation_request(self):return self.navigation

    class Route:
        def __init__(self, request):self.request=request;self.action=None
        def continue_(self):self.action='continued'
        def abort(self):self.action='aborted'

    validate_public_url=url_ingestion.validate_public_url
    monkeypatch.setattr(url_ingestion,'validate_public_url',
                        lambda url: url if url=='https://example.com/article' else validate_public_url(url))
    connection={'origin':'https://example.com','approvedOrigins':[]}
    allowed=Route(Request('https://example.com/article',navigation=True))
    assert guard_browser_request(allowed,connection) is True
    assert allowed.action=='continued'

    private=Route(Request('http://127.0.0.1/admin'))
    blocked=[]
    assert guard_browser_request(private,connection,blocked) is False
    assert private.action=='aborted' and blocked==[]

    mutation=Route(Request('https://example.com/submit',method='POST'))
    # A configuration value alone cannot bypass the read-only executor; a
    # future write path must authorize the exact action before dispatch.
    monkeypatch.setenv('OPENLEARN_BROWSER_WRITES_ENABLED','true')
    assert guard_browser_request(mutation,connection) is False
    assert mutation.action=='aborted'


def test_real_cloud_adapter_navigation_scroll_screenshot_and_stale_refs(environment,browser_fixture):
    store,_=environment;endpoint,page=browser_fixture
    site=Connections(store).create('alice',ConnectionCreate(label='Unseen site',origin='https://unseen.fixture.example',executor='cloud'))
    run=AssistantService(store).create('alice',TaskCreate(message='Read the website',connection_id=site['id']))
    run={**run,'owner_id':'alice'};provider=FixtureProvider(endpoint);executor=CloudExecutor(store,provider)
    observation=execute_fixture(page,executor,BrowserAction(tool='navigate',url=site['origin']),site,run)
    snapshot={**observation.model_dump(by_alias=True),'id':'s1'}
    assert any('Independent study' in b.text for b in observation.blocks)
    calendar=next(c for c in observation.controls if c.role=='scroll_container')
    scrolled=execute_fixture(page,executor,BrowserAction(tool='scroll',element_ref=calendar.ref,snapshot_id='s1'),site,run,snapshot)
    assert any('Midterm November 20, 2027' in b.text for b in scrolled.blocks)
    found=execute_fixture(page,executor,BrowserAction(tool='find',query='Midterm'),site,run)
    assert any('Midterm November 20, 2027' in block.text for block in found.blocks)
    shot=execute_fixture(page,executor,BrowserAction(tool='capture_screenshot'),site,run)
    assert shot.screenshot and len(shot.screenshot)>100
    link=next(c for c in scrolled.controls if c.role=='link')
    current={**scrolled.model_dump(by_alias=True),'id':'s2'}
    clicked=execute_fixture(page,executor,BrowserAction(tool='click',element_ref=link.ref,snapshot_id='s2'),site,run,current)
    assert clicked.url.endswith('/syllabus')
    dangerous=next(c for c in clicked.controls if c.name=='Submit exam')
    from fastapi import HTTPException
    with pytest.raises(HTTPException):authorize_action(BrowserAction(tool='click',element_ref=dangerous.ref,snapshot_id='s3'),site,{**clicked.model_dump(by_alias=True),'id':'s3'})
    executor.close('alice',run['id']);assert provider.stopped==['fixture-session']


def test_real_canvas_packaged_script_discovers_authenticated_courses(browser_fixture):
    _,page=browser_fixture;page.goto('https://canvas.fixture.example')
    value=page.evaluate(platform_script(),{'origin':'https://canvas.fixture.example','url':'https://canvas.fixture.example/api/v1/courses'})
    assert value['accountId']=='student-1' and value['platformItems'][0]['name']=='Biology'
    assert value['complete'] is True
    assert Path('canvas-extension/canvas-read.js').read_text().replace('export async function','async function')==Path('backend/app/browser_assistant/adapters/canvas-read.js').read_text()
    assert Path('canvas-extension/observer.js').read_text()==Path('backend/app/browser_assistant/observer.js').read_text()


def test_login_observation_and_screenshot_are_withheld(environment,browser_fixture):
    store,_=environment;endpoint,page=browser_fixture
    site=Connections(store).create('alice',ConnectionCreate(label='Login',origin='https://unseen.fixture.example',executor='cloud'))
    run=AssistantService(store).create('alice',TaskCreate(message='Read the website',connection_id=site['id']))
    run={**run,'owner_id':'alice'};executor=CloudExecutor(store,FixtureProvider(endpoint))
    page.goto(site['origin'])
    page.set_content('<main><p>PRIVATE LOGIN TEXT</p><input type="password" value="secret"><input autocomplete="one-time-code" value="123456"></main>')
    observed=execute_fixture(page,executor,BrowserAction(tool='capture_screenshot'),site,run)
    assert observed.status=='login_required'
    assert not observed.blocks and not observed.controls and observed.screenshot is None
    executor.close('alice',run['id'])
