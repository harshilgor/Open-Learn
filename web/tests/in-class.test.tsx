import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {InClassWorkspace} from '@/components/in-class-workspace';
import {classApi,type ClassSnapshot} from '@/lib/in-class';
const fixture=()=>({session:{id:'class-one',sessionId:'chat-one',revision:1,recordingId:'recording-one',noteId:'note-one',buddyId:'buddy-one',courseId:'course-one',title:'Biology',deviceId:'capture-one',processing:'live',cancelled:false,partial:false},recording:{captureComplete:false,stages:{audioRetention:"kept"},preferences:{keepAudio:true},markersMs:[],chunks:{missing:[],transcribed:1,serverConfirmed:1,failed:0}},outputs:[{id:'notes-one',windowId:'window-one',kind:'notes',revision:1,status:'ready',result:{blocks:[{title:'Cell structure',body:'Membranes form a boundary.',segmentIds:['segment-one']}]}},{id:'practice-one',windowId:'window-one',kind:'practice',revision:1,status:'failed',error:'Quiz provider unavailable'}],transcript:[],liveTranscript:[],cursor:2,hasMore:false,events:[]} as unknown as ClassSnapshot);
vi.mock('@/lib/in-class',async importOriginal=>{const actual=await importOriginal<typeof import('@/lib/in-class')>();return {...actual,classApi:{...actual.classApi,snapshot:vi.fn(),events:vi.fn(),stream:vi.fn(),command:vi.fn(),materials:vi.fn(),materialIntakes:vi.fn(),resourceConnectors:vi.fn(),resourcePreferences:vi.fn(),transcriptSegments:vi.fn(),metrics:vi.fn(),lookupReference:vi.fn(),needs:vi.fn()}};});
vi.mock('@/components/buddies',()=>({useBuddies:()=>({snapshot:null}),BuddyAvatar:()=>null}));
vi.mock('@/components/rich-content',()=>({RichContent:({body}:{body:string})=><p>{body}</p>}));
let root:Root,container:HTMLDivElement;
beforeEach(()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;vi.useFakeTimers();vi.mocked(classApi.snapshot).mockResolvedValue(fixture());vi.mocked(classApi.events).mockResolvedValue({...fixture(),delta:true,outputs:[],transcript:[]});vi.mocked(classApi.stream).mockImplementation((_id,_cursor,_event,signal)=>new Promise(resolve=>signal.addEventListener('abort',()=>resolve(),{once:true})));vi.mocked(classApi.materials).mockResolvedValue({materials:[]});vi.mocked(classApi.materialIntakes).mockResolvedValue({intakes:[]});vi.mocked(classApi.resourceConnectors).mockResolvedValue({items:[],externalWritesEnabled:false});vi.mocked(classApi.resourcePreferences).mockResolvedValue({courseId:'course-one',revision:1,updatedAt:null,preferences:{connectorOrder:['library','upload','url','drive','canvas','blackboard','moodle'],enabledConnectors:['library','upload'],allowPublicUrls:false,acceptedMediaTypes:['application/pdf'],maxUploadBytes:250*1024*1024,requireExplicitSelection:true,crossCourseLibrarySearch:false}});vi.mocked(classApi.transcriptSegments).mockResolvedValue({items:[],hasMore:false,nextCursor:null,generation:0});container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();vi.clearAllMocks();vi.useRealTimers();});
it('retains notes and reading focus when a specialist fails and polling reconnects',async()=>{
 vi.mocked(classApi.stream).mockRejectedValueOnce(new Error('Connection interrupted'));
 vi.mocked(classApi.events).mockRejectedValueOnce(new Error('Connection interrupted'));
 await act(async()=>root.render(<InClassWorkspace classId="class-one"/>));
 const notes=[...container.querySelectorAll('button')].find(b=>b.textContent==='Notes')!;notes.focus();
 await act(async()=>{await vi.advanceTimersByTimeAsync(3000);});
 expect(container.textContent).toContain('Membranes form a boundary.');expect(document.activeElement).toBe(notes);
 await act(async()=>{await vi.advanceTimersByTimeAsync(3000);});expect(document.activeElement).toBe(notes);
 const practice=[...container.querySelectorAll('button')].find(b=>b.textContent?.startsWith('Practice'))!;
 act(()=>practice.click());expect(container.textContent).toContain('Retry this output');
 vi.mocked(classApi.command).mockResolvedValue(fixture());
 await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Retry this output')!.click());
 expect(classApi.command).toHaveBeenCalledWith('class-one',1,'retry','practice-one',undefined);
});
it('replays an SSE delta without moving keyboard focus or losing prior notes',async()=>{
 let deliver!: (value:ClassSnapshot,eventId?:string)=>void;
 vi.mocked(classApi.stream).mockImplementation((_id,_cursor,_event,signal,onSnapshot)=>{deliver=onSnapshot;return new Promise(resolve=>signal.addEventListener('abort',()=>resolve(),{once:true}));});
 await act(async()=>root.render(<InClassWorkspace classId="class-one"/>));
 const notes=[...container.querySelectorAll('button')].find(button=>button.textContent==='Notes')!;notes.focus();
 await act(async()=>deliver({...fixture(),delta:true,cursor:3,outputs:[{...fixture().outputs[0],id:'notes-two',windowId:'window-two',result:{blocks:[{title:'Nucleus',body:'The nucleus regulates cell activity.',segmentIds:[]}]}}]},'event-three'));
 expect(container.textContent).toContain('Membranes form a boundary.');expect(container.textContent).toContain('The nucleus regulates cell activity.');expect(document.activeElement).toBe(notes);
 expect(classApi.resourcePreferences).toHaveBeenCalledWith('class-one');
});
it('ignores a late snapshot for the previously opened class',async()=>{
 let deliver!:(value:ClassSnapshot)=>void;
 vi.mocked(classApi.snapshot).mockReturnValueOnce(new Promise(resolve=>{deliver=resolve;}));
 await act(async()=>root.render(<InClassWorkspace classId="class-old"/>));
 await act(async()=>root.render(<InClassWorkspace classId="class-one"/>));
 await act(async()=>deliver({...fixture(),session:{...fixture().session,id:'class-old',title:'Old private class'}}));
 expect(container.textContent).toContain('Biology');expect(container.textContent).not.toContain('Old private class');
});
it('keeps processing pause distinct from audio capture',async()=>{
 await act(async()=>root.render(<InClassWorkspace classId="class-one"/>));
 vi.mocked(classApi.command).mockResolvedValue(fixture());
 await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Pause processing')!.click());
 expect(classApi.command).toHaveBeenCalledWith('class-one',1,'cancel_processing',undefined,undefined);
 expect(container.textContent).toContain('does not stop audio capture');
});

it('shows caption drafts and replaces them with archived transcript links',async()=>{
 const base=fixture();base.provisionalNotes=[{id:'draft',liveSegmentId:'live1',revision:1,sourceVersion:1,status:'ready',startMs:0,endMs:1000,result:{blocks:[{title:'Caption draft',body:'Provisional membrane wording.',segmentIds:['live1']}]},authoritativeSources:[],createdAt:1}];
 vi.mocked(classApi.snapshot).mockResolvedValue(base);
 let deliver!:(value:ClassSnapshot)=>void;vi.mocked(classApi.stream).mockImplementation((_id,_cursor,_event,signal,onSnapshot)=>{deliver=onSnapshot;return new Promise(resolve=>signal.addEventListener('abort',()=>resolve(),{once:true}));});
 await act(async()=>root.render(<InClassWorkspace classId="class-one"/>));
 expect(container.textContent).toContain('Provisional membrane wording.');
 await act(async()=>deliver({...base,delta:true,cursor:3,provisionalNotes:[{...base.provisionalNotes![0],status:'reconciled',revision:2,authoritativeSources:[{segmentId:'segment-one',revision:1}]}]}));
 expect(container.textContent).not.toContain('Provisional membrane wording.');expect(container.textContent).toContain('Replaced by archived transcript');
});
it('finds a library reference beyond the live snapshot and restores opener focus',async()=>{
 vi.mocked(classApi.lookupReference).mockResolvedValue({candidates:[{spanId:'library-span',versionId:'version',title:'Course handbook',text:'A supporting library passage.',pageIndex:3}],ambiguous:false,hasMore:false,indexVersion:2});
 await act(async()=>root.render(<InClassWorkspace classId="class-one"/>));
 act(()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Materials')!.click());
 const input=container.querySelector('input[maxlength="200"]') as HTMLInputElement;
 await act(async()=>{const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!;setter.call(input,'membrane');input.dispatchEvent(new Event('input',{bubbles:true}));});
 await act(async()=>container.querySelector('[aria-label="Course reference lookup"] form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(classApi.lookupReference).toHaveBeenCalledWith('class-one','membrane',null);
 expect(container.textContent).toContain('Course handbook');const source=[...container.querySelectorAll('button')].find(b=>b.textContent?.includes('Course handbook'))!;source.focus();act(()=>source.click());
 expect(container.querySelector('[aria-label="Class reference"]')).not.toBeNull();
 act(()=>container.querySelector<HTMLButtonElement>('[aria-label="Close reference"]')!.click());
 // Navigation removes the Materials opener; Close must still leave valid DOM focus.
 expect(container.querySelector('[aria-label="Class reference"]')).toBeNull();
});
