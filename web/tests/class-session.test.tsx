import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {InClassWorkspace} from '@/components/in-class-workspace';
import {classApi,CLASS_SETUP_REQUEST_EVENT,type ClassSnapshot} from '@/lib/in-class';
import {learningApi} from '@/lib/api';
import {START_CLASS_EVENT,clearPendingStartClass,startClass} from '@/lib/class-events';
import {resetClassMarkerCache} from '@/lib/class-markers';
import {WORKSPACE_NOTE_OPEN_EVENT,WORKSPACE_PASSAGE_MENTION_EVENT,WORKSPACE_QUIZ_OPEN_EVENT,WORKSPACE_QUIZ_REQUEST_EVENT} from '@/lib/workspace-events';

vi.mock('@/lib/in-class',async importOriginal=>{const actual=await importOriginal<typeof import('@/lib/in-class')>();return {...actual,classApi:{...actual.classApi,snapshot:vi.fn(),events:vi.fn(),stream:vi.fn(),command:vi.fn(),materials:vi.fn(),materialIntakes:vi.fn(),resourceConnectors:vi.fn(),resourcePreferences:vi.fn(),transcriptSegments:vi.fn(),metrics:vi.fn(),lookupReference:vi.fn(),needs:vi.fn()}};});
vi.mock('@/lib/api',async importOriginal=>{const actual=await importOriginal<typeof import('@/lib/api')>();return {...actual,learningApi:{...actual.learningApi,listCourses:vi.fn(),getWorkspaceNote:vi.fn()}};});
vi.mock('@/components/buddies',()=>({useBuddies:()=>({snapshot:null}),BuddyAvatar:()=>null}));
vi.mock('@/components/rich-content',()=>({RichContent:({body}:{body:string})=><p>{body}</p>}));

const transcript=[
 {id:'seg-a',chunkId:'c1',startMs:0,endMs:9000,speaker:'professor',rawText:'Welcome to cell biology.',normalizedText:'Welcome to cell biology.',confidence:null},
 {id:'seg-b',chunkId:'c1',startMs:24000,endMs:32000,speaker:'professor',rawText:'Osmosis moves water across a membrane.',normalizedText:'Osmosis moves water across a membrane.',confidence:null},
];
const fixture=(overrides:{captureComplete?:boolean;durationMs?:number;markersMs?:number[];outputs?:unknown[]}={})=>({session:{id:'class-one',sessionId:'chat-one',revision:1,recordingId:'recording-one',noteId:'note-one',buddyId:'buddy-one',courseId:'course-one',title:'Biology lecture',deviceId:'capture-one',processing:'live',cancelled:false,partial:false},recording:{captureComplete:overrides.captureComplete??false,recordingStatus:'completed',durationMs:overrides.durationMs??0,stages:{audioRetention:'kept'},preferences:{keepAudio:true},markersMs:overrides.markersMs??[],chunks:{missing:[],transcribed:2,serverConfirmed:2,failed:0}},outputs:overrides.outputs??[],transcript,liveTranscript:[],cursor:2,hasMore:false,events:[]} as unknown as ClassSnapshot);

let root:Root,container:HTMLDivElement;
const button=(text:string)=>[...container.querySelectorAll('button')].find(item=>item.textContent?.trim()===text)!;
beforeEach(()=>{
 (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;vi.useFakeTimers();
 localStorage.clear();resetClassMarkerCache();clearPendingStartClass();
 vi.mocked(learningApi.listCourses).mockResolvedValue([{id:'course-one',name:'Biology'},{id:'course-two',name:'Chemistry'}] as Awaited<ReturnType<typeof learningApi.listCourses>>);
 vi.mocked(learningApi.getWorkspaceNote).mockResolvedValue({id:'note-one',revision:3} as Awaited<ReturnType<typeof learningApi.getWorkspaceNote>>);
 vi.mocked(classApi.snapshot).mockResolvedValue(fixture());
 vi.mocked(classApi.events).mockResolvedValue({...fixture(),delta:true,outputs:[],transcript:[]});
 vi.mocked(classApi.stream).mockImplementation((_id,_cursor,_event,signal)=>new Promise(resolve=>signal.addEventListener('abort',()=>resolve(),{once:true})));
 vi.mocked(classApi.materials).mockResolvedValue({materials:[]});vi.mocked(classApi.materialIntakes).mockResolvedValue({intakes:[]});
 vi.mocked(classApi.resourceConnectors).mockResolvedValue({items:[],externalWritesEnabled:false});
 vi.mocked(classApi.resourcePreferences).mockRejectedValue(new Error('not needed'));
 container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
});
afterEach(()=>{act(()=>root.unmount());container.remove();vi.clearAllMocks();vi.useRealTimers();});

it('preselects the course from a start-class event and focuses the start action',async()=>{
 await act(async()=>root.render(<InClassWorkspace classId={null}/>));
 const select=(container.querySelector('#class-course-choice') as unknown as HTMLSelectElement);
 expect(select.value).toBe('');
 await act(async()=>startClass('course-two'));
 expect(select.value).toBe('course-two');
 const start=button('Continue to setup');
 expect(document.activeElement).toBe(start);
 const setup=vi.fn();window.addEventListener(CLASS_SETUP_REQUEST_EVENT,setup);
 act(()=>start.click());
 expect((setup.mock.calls[0][0] as CustomEvent).detail).toEqual({courseId:'course-two',title:''});
 window.removeEventListener(CLASS_SETUP_REQUEST_EVENT,setup);
 // A raw event without the helper is honoured too.
 await act(async()=>window.dispatchEvent(new CustomEvent(START_CLASS_EVENT,{detail:{courseId:'course-one'}})));
 expect(select.value).toBe('course-one');
});

it('accepts an initial course and a request made before the class tool mounted',async()=>{
 await act(async()=>root.render(<InClassWorkspace classId={null} initialCourseId="course-one"/>));
 expect((container.querySelector('#class-course-choice') as unknown as HTMLSelectElement).value).toBe('course-one');
 act(()=>root.unmount());root=createRoot(container);
 startClass('course-two');
 await act(async()=>root.render(<InClassWorkspace classId={null}/>));
 expect((container.querySelector('#class-course-choice') as unknown as HTMLSelectElement).value).toBe('course-two');
 expect(document.activeElement).toBe(button('Continue to setup'));
});

it('falls back to a general class when the requested course is unknown',async()=>{
 await act(async()=>root.render(<InClassWorkspace classId={null} initialCourseId="archived-course"/>));
 expect((container.querySelector('#class-course-choice') as unknown as HTMLSelectElement).value).toBe('');
});

it('shows the launch form over an open class when asked to start another',async()=>{
 await act(async()=>root.render(<InClassWorkspace classId="class-one"/>));
 expect(container.querySelector('[aria-label="Live class session"]')).not.toBeNull();
 await act(async()=>startClass('course-two'));
 expect((container.querySelector('#class-course-choice') as unknown as HTMLSelectElement).value).toBe('course-two');
 act(()=>button('Back to the open class').click());
 expect(container.querySelector('#class-course-choice')).toBeNull();
 expect(container.textContent).toContain('Biology lecture');
});

it('marks typed moments during class from the session bar',async()=>{
 await act(async()=>root.render(<InClassWorkspace classId="class-one"/>));
 const live=container.querySelector('[aria-label="Live class session"]')!;
 expect(live.textContent).toContain('Biology');
 expect(live.textContent).toContain('Osmosis moves water across a membrane.');
 act(()=>button('I’m confused').click());
 expect(live.textContent).toContain('Confusing moment at ≈0:32 saved');
 act(()=>button('Key point').click());
 const stored=JSON.parse(localStorage.getItem('openlearn.class-markers:recording-one')!) as {kind:string;atMs:number}[];
 expect(stored.map(marker=>marker.kind)).toEqual(['confused','key_point']);
 expect(stored[0].atMs).toBe(32000);
});

it('summarises a finished class and routes follow-up study actions',async()=>{
 localStorage.setItem('openlearn.class-markers:recording-one',JSON.stringify([{id:'m1',kind:'confused',atMs:30000,createdAt:1},{id:'m2',kind:'key_point',atMs:45000,createdAt:2}]));
 vi.mocked(classApi.snapshot).mockResolvedValue(fixture({captureComplete:true,durationMs:65000,markersMs:[12000,30200,45100]}));
 await act(async()=>root.render(<InClassWorkspace classId="class-one"/>));
 const summary=container.querySelector('[aria-labelledby="class-summary-title"]')!;
 expect(summary).not.toBeNull();
 expect(container.querySelector('[aria-label="Live class session"]')).toBeNull();
 expect(summary.textContent).toContain('1:05');
 const counts=[...summary.querySelectorAll('dl > div')].map(item=>item.textContent);
 expect(counts).toEqual(['Moments1','Confusing1','Key points1']);
 expect([...summary.querySelectorAll('ol li time')].map(item=>item.textContent)).toEqual(['0:12','0:30','0:45']);

 const quiz=vi.fn(),mention=vi.fn(),note=vi.fn();
 window.addEventListener(WORKSPACE_QUIZ_REQUEST_EVENT,quiz);window.addEventListener(WORKSPACE_PASSAGE_MENTION_EVENT,mention);window.addEventListener(WORKSPACE_NOTE_OPEN_EVENT,note);
 act(()=>button('Quiz me on this class').click());
 expect((quiz.mock.calls[0][0] as CustomEvent).detail).toEqual({requestedTopic:'Biology lecture',sessionId:'chat-one',origin:'ask'});
 act(()=>button('Review confusing moments').click());
 const detail=(mention.mock.calls[0][0] as CustomEvent).detail;
 expect(detail.submit).toBe(true);expect(detail.excerpt).toContain('At 0:30');expect(detail.excerpt).toContain('Osmosis moves water');
 act(()=>button('Open class note').click());
 expect((note.mock.calls[0][0] as CustomEvent).detail).toBe('note-one');
 expect(button('Make flashcards')).toBeTruthy();
 expect(learningApi.getWorkspaceNote).toHaveBeenCalledWith('note-one');
 window.removeEventListener(WORKSPACE_QUIZ_REQUEST_EVENT,quiz);window.removeEventListener(WORKSPACE_PASSAGE_MENTION_EVENT,mention);window.removeEventListener(WORKSPACE_NOTE_OPEN_EVENT,note);
});

it('opens the class revision quiz when one is ready and omits confusing review when none were marked',async()=>{
 vi.mocked(classApi.snapshot).mockResolvedValue(fixture({captureComplete:true,durationMs:5000,outputs:[{id:'quiz-out',windowId:'w',kind:'revision_quiz',revision:1,status:'ready',result:{quizId:'quiz-1'}}]}));
 await act(async()=>root.render(<InClassWorkspace classId="class-one"/>));
 expect(container.textContent).toContain('No moments were marked during this class.');
 expect(button('Review confusing moments')).toBeUndefined();
 const opened=vi.fn();window.addEventListener(WORKSPACE_QUIZ_OPEN_EVENT,opened);
 act(()=>button('Quiz me on this class').click());
 expect((opened.mock.calls[0][0] as CustomEvent).detail).toMatchObject({sessionId:'chat-one',quizId:'quiz-1'});
 window.removeEventListener(WORKSPACE_QUIZ_OPEN_EVENT,opened);
});
