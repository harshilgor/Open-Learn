import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import {BrowserTaskCard} from '@/components/browser-task-card';
import {BrowserControlPanel} from '@/components/browser-control-panel';
import {ACCOUNT_CHANGED} from '@/lib/account-session';
import {type BrowserTask} from '@/lib/browser-assistant';
const {request}=vi.hoisted(()=>({request:vi.fn(async()=>({connections:[]}))}));
vi.mock('@/lib/api',()=>({request,apiBaseUrl:()=>''}));
vi.mock('@/components/rich-content',()=>({RichContent:({body}:{body:string})=><p>{body}</p>}));
vi.mock('@/components/site-connections',()=>({SiteConnections:()=> <p>Connect a website</p>}));
let root:Root,container:HTMLDivElement;
beforeEach(()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);vi.clearAllMocks();});
afterEach(()=>{act(()=>root.unmount());container.remove();});
const task:BrowserTask={id:'task',revision:3,message:'Save my midterm dates',status:'completed_partial',facts:[{title:'Biology midterm',kind:'assessment',date:{kind:'date_only',value:'2027-02-10'},source:{locator:'https://school.example/syllabus',quote:'Midterm February 10, 2027'}}],coverage:[{key:'syllabus',complete:false,status:'partial',url:'https://school.example'}],actionsUsed:2,createdAt:0};
describe('browser assistant task',()=>{
  it('shows source evidence and incomplete coverage without claiming a precise time',()=>{act(()=>root.render(<BrowserTaskCard task={task} onCommand={vi.fn()}/>));expect(container.textContent).toContain('time not specified');expect(container.textContent).toContain('incomplete coverage');expect(container.querySelector('a')?.href).toBe('https://school.example/syllabus');expect(container.textContent).toContain('Midterm February 10, 2027');});
  it('sends pause and cancel using the visible revision',async()=>{const command=vi.fn(async()=>undefined);act(()=>root.render(<BrowserTaskCard task={{...task,status:'running'}} onCommand={command}/>));const pause=[...container.querySelectorAll('button')].find(b=>b.textContent==='Pause')!;await act(async()=>pause.click());expect(command).toHaveBeenCalledWith(expect.objectContaining({revision:3}),'pause',undefined,undefined,undefined);});
  it('offers a connection and continuation after login or device loss',async()=>{const command=vi.fn(async()=>undefined);await act(async()=>root.render(<BrowserTaskCard task={{...task,status:'waiting_for_device',error:'device_offline',question:'Pair the companion'}} onCommand={command}/>));expect(container.textContent).toContain('Connect a website');expect(container.textContent).toContain('Pair the companion');const resume=[...container.querySelectorAll('button')].find(b=>b.textContent==='Continue')!;await act(async()=>resume.click());expect(command).toHaveBeenCalledWith(expect.objectContaining({id:'task'}),'resume',undefined,undefined,undefined);});
});

describe('exclusive browser handoff',()=>{
  const human:BrowserTask={...task,status:'paused',connectionId:'site',browserControl:{owner:'human',generation:'control-1',executor:'cloud'}};
  it('keeps browser input unavailable until automation has acknowledged stopping',()=>{
    act(()=>root.render(<BrowserControlPanel task={{...human,browserControl:{...human.browserControl!,owner:'requesting'}}}/>));
    expect(container.textContent).toContain('Waiting for automation to stop');
    expect(container.querySelector('iframe')).toBeNull();
    expect([...container.querySelectorAll('button')].some(b=>b.textContent==='Open browser')).toBe(false);
  });
  it('opens a generation-bound human view and clears it on account change',async()=>{
    request.mockResolvedValueOnce({kind:'cloud',generation:'control-1',url:'https://debug.browserbase.com/view',expiresAt:Date.now()/1000+60} as never);
    act(()=>root.render(<BrowserControlPanel task={human}/>));
    await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Open browser')!.click());
    expect(container.querySelector('iframe')?.src).toBe('https://debug.browserbase.com/view');
    act(()=>window.dispatchEvent(new Event(ACCOUNT_CHANGED)));
    expect(container.querySelector('iframe')).toBeNull();
  });
  it('returns control with the visible revision and closes the local view first',async()=>{
    request.mockResolvedValueOnce({kind:'local',generation:'control-1',message:'Use the desktop'} as never);
    act(()=>root.render(<BrowserControlPanel task={human}/>));
    await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Open browser')!.click());
    request.mockResolvedValueOnce({} as never);
    await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Return control')!.click());
    expect(request).toHaveBeenLastCalledWith('/v1/assistant/tasks/task/commands',expect.objectContaining({body:JSON.stringify({action:'return_control',expectedRevision:3})}));
    expect(container.textContent).not.toContain('Use the desktop');
  });
  it('shows revoked or expired view errors without embedding a browser',async()=>{
    request.mockRejectedValueOnce(new Error('Browser session expired'));
    act(()=>root.render(<BrowserControlPanel task={human}/>));
    await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Open browser')!.click());
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('expired');
    expect(container.querySelector('iframe')).toBeNull();
  });
});
