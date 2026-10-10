import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkspaceSidebar, type WorkspaceSidebarTab, type NotesCommand } from '@/components/workspace-sidebar';
import { NotesWorkspace } from '@/components/workspace-panel';
import { noteDisplayTitle } from '@/lib/note-list';
import { needsFloatingRecovery, processingStarted } from '@/lib/recording-ui';
import { workspacePath, sidebarTabFromPath } from '@/lib/workspace-navigation';
import type { CourseSummary, WorkspaceNoteSummary, LectureStatus } from '@/lib/api';
import type { LocalLecture } from '@/lib/lecture-local-store';

const mocks = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), update: vi.fn(), create: vi.fn(), chats: vi.fn(), refresh: vi.fn() }));
vi.mock('@/lib/api', async original => ({ ...await original<object>(), learningApi: { listWorkspaceNotes: mocks.list, getWorkspaceNote: mocks.get, updateWorkspaceNote: mocks.update, createWorkspaceNote: mocks.create, listChatSessions: mocks.chats, refreshNoteTitles: mocks.refresh } }));
const buddyFixture = vi.hoisted(() => ({ snapshot: { chats: { s1: 'buddy', s2: 'buddy' }, profiles: [{ id: 'buddy', name: 'Buddy' }] }, active: { id: 'buddy' }, refresh: vi.fn(async () => {}) }));
vi.mock('@/components/buddies', () => ({ useBuddies: () => buddyFixture }));
vi.mock('@/components/study-note-bar', () => ({ StudyNoteBar: () => null }));
vi.mock('@/components/study-note-panel', () => ({ NoteProposalList: () => null }));
vi.mock('@/components/visualization-reference', () => ({ NoteVisualReferences: () => null }));
vi.mock('@/components/lecture-notes-view', () => ({ LectureNotesView: () => null }));
vi.mock('@/components/quiz-workspace', () => ({ QuizWorkspace: () => null, LessonPractice: () => null }));
vi.mock('@/components/compact-tutor-chat', () => ({ CompactTutorChat: ({ context }: {context: {excerpt:string}}) => <aside aria-label="Note discussion">{context.excerpt}</aside> }));

const courses = [{id:'physics',name:'Physics',roadmapProgress:20},{id:'math',name:'Math',roadmapProgress:0}] as CourseSummary[];
const notes: WorkspaceNoteSummary[] = [
  { id:'n1', title:'Motion',preview:'Velocity describes motion.',noteType:'lesson',frontmatter:{course_id:'physics'},revision:1,relativePath:'n1.md',updatedAt:'2026-09-28T12:00:00Z' },
  { id:'n2', title:'My equations',preview:'An equation balances both sides.',noteType:'manual',frontmatter:{course_id:'math'},revision:1,relativePath:'n2.md',updatedAt:'2026-09-29T12:00:00Z' },
];
let root:Root, container:HTMLDivElement;
beforeEach(() => {
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers(); localStorage.clear(); vi.clearAllMocks();
  HTMLElement.prototype.scrollIntoView = vi.fn();
  mocks.refresh.mockResolvedValue({updated:0,skipped:0}); mocks.list.mockResolvedValue(notes);
  mocks.get.mockImplementation(async id => ({...notes.find(n=>n.id===id),body:'## Motion\n\nVelocity describes motion.',createdAt:'2026-09-28',learnerId:'local'}));
  mocks.chats.mockResolvedValue({sessions:[{id:'s1',title:'Physics chat',courseId:'physics',updatedAt:new Date().toISOString(),createdAt:new Date().toISOString()},{id:'s2',title:'Math chat',courseId:'math',updatedAt:new Date().toISOString(),createdAt:new Date().toISOString()}]});
  mocks.create.mockImplementation(async input=>({...input,id:'new',revision:1,frontmatter:input.frontmatter,createdAt:'2026-09-29',updatedAt:'2026-09-29',learnerId:'local'}));
  mocks.update.mockImplementation(async (id,input)=>({...input,id,revision:2}));
  container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
});
afterEach(()=>{act(()=>root.unmount());container.remove();vi.useRealTimers();});
async function settle(ms=200){await act(async()=>{await vi.advanceTimersByTimeAsync(ms);});}
function button(label:string){const found=[...container.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')===label||b.textContent?.trim()===label);if(!found)throw Error(`Missing ${label}`);return found;}
function click(label:string){act(()=>button(label).click());}
function Harness(){
  const [tab,setTab]=useState<WorkspaceSidebarTab>('notes');const [course,setCourse]=useState<string|null>(null);const [host,setHost]=useState<HTMLDivElement|null>(null);const [command,setCommand]=useState<NotesCommand|null>(null);
  return <><WorkspaceSidebar tab={tab} onTabChange={setTab} collapseControl={<button aria-label="Toggle Sidebar"/>} courses={courses} activeCourseId={course} onCourseSelect={setCourse} onCourseOpen={()=>{}} onNewChat={()=>{}} onNewCourse={()=>{}} onNotesCommand={action=>setCommand({id:Date.now(),action})} onDashboard={()=>{}} activeSessionId={null} refreshKey={0} onOpenSession={()=>{}} notesHost={setHost}/><div hidden={tab!=='notes'}><NotesWorkspace listHost={host} courses={courses} courseFilter={course} onCourseFilter={setCourse} command={command} noteToOpen={null} onNoteOpenConsumed={()=>{}}/></div><button onClick={()=>setCommand({id:1,action:'new-note'})}>Test new note</button><button onClick={()=>setCommand({id:2,action:'new-folder'})}>Test new folder</button></>;
}
describe('unified sidebar and notes',()=>{
  it('restores an explicitly selected note and does not reload it on parent rerenders',async()=>{
    const selected=vi.fn(); const consumed=vi.fn();
    const render=()=>root.render(<NotesWorkspace courses={courses} noteToOpen="n1" onNoteSelected={selected} onNoteOpenConsumed={consumed}/>);
    act(render); await settle();
    expect(container.querySelector<HTMLInputElement>('[aria-label="Note title"]')?.value).toBe('Motion');
    expect(mocks.get).toHaveBeenCalledTimes(1);
    act(render); await settle();
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(selected).toHaveBeenCalledWith('n1');
  });
  it('swaps bodies by keyboard and keeps the same course filter and selected note',async()=>{
    act(()=>root.render(<Harness/>));await settle();
    expect(container.querySelectorAll('[aria-label="Toggle Sidebar"]').length).toBe(1);
    const courseButtons=[...container.querySelectorAll('button')].filter(b=>b.textContent==='Physics');act(()=>courseButtons[0].click());
    expect(container.querySelector('#sidebar-body-notes')?.textContent).toContain('Motion');
    expect(container.querySelector('#sidebar-body-notes')?.textContent).not.toContain('My equations');
    act(()=>container.querySelector<HTMLButtonElement>('[title="Motion"]')!.click());await settle();
    expect(container.querySelector('[aria-current="page"][title="Motion"]')).not.toBeNull();
    const tab=container.querySelector('#sidebar-tab-notes')!;act(()=>tab.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true})));
    expect(container.querySelector('#sidebar-tab-home')?.getAttribute('aria-selected')).toBe('true');
    expect(container.querySelector('#sidebar-body-home')?.textContent).toContain('Physics chat');
    expect(container.querySelector('#sidebar-body-home')?.textContent).not.toContain('Math chat');
    click('Notes');expect(container.querySelector<HTMLInputElement>('[aria-label="Note title"]')?.value).toBe('Motion');
    expect(courseButtons[0].getAttribute('aria-pressed')).toBe('true');
  });
  it('groups notes with preview, course, type and active state; opens discussion with saved context',async()=>{
    act(()=>root.render(<Harness/>));await settle();
    const list=container.querySelector('#sidebar-body-notes')!;
    expect(list.textContent).toContain('Folders');expect(list.textContent).toContain('Generated');expect(list.textContent).toContain('Your notes');expect(list.textContent).toContain('Velocity describes motion.');
    act(()=>container.querySelector<HTMLButtonElement>('[title="Motion"]')!.click());await settle();click('Discuss this note');
    expect(container.querySelector('[aria-label="Note discussion"]')?.textContent).toContain('Velocity describes motion.');
    expect(container.querySelector('[aria-current="page"]')).not.toBeNull();
  });
  it('renders mutually exclusive empty and blank editor states and hides empty formatting tools',async()=>{
    act(()=>root.render(<Harness/>));await settle();expect(container.textContent).toContain('Your notes');
    expect(container.querySelector('[aria-label="Note title"]')).toBeNull();
    click('Test new note');await settle();expect(container.textContent).not.toContain('Start writing, or save something from your conversation.');
    expect(container.querySelector('[aria-label="Note title"]')).not.toBeNull();expect(container.querySelector('[data-note-toolbar]')).toBeNull();
    const editor=container.querySelector<HTMLElement>('[contenteditable="true"]')!;
    act(()=>{editor.textContent='My first sentence.';editor.dispatchEvent(new Event('input',{bubbles:true}));});await settle(800);
    expect(mocks.create).toHaveBeenCalled();expect(mocks.create.mock.calls[0][0].body).toContain('My first sentence.');
    expect(container.querySelector('[data-note-toolbar]')).toBeNull();
  });
  it('creates a folder through the shared Notes command',async()=>{
    act(()=>root.render(<Harness/>));await settle();click('Test new folder');await settle();
    const input=container.querySelector<HTMLInputElement>('[aria-label="Folder name"]')!;
    act(()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'Lab notes');input.dispatchEvent(new Event('input',{bubbles:true}));});
    act(()=>input.closest('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
    expect(localStorage.getItem('open-learn-note-folders-v1')).toContain('Lab notes');expect(container.textContent).toContain('Lab notes');
  });
});
describe('navigation, duplicate titles and recording status',()=>{
  it('encodes course and note IDs for refresh and separates equal titles even on the same date',()=>{
    expect(workspacePath('notes','s1','physics','n1')).toBe('/notes?course=physics&note=n1');expect(sidebarTabFromPath('/notes')).toBe('notes');
    expect(workspacePath('home','s1',null)).toBe('/s/s1?course=');
    const duplicate={...notes[0],id:'n3'};expect(noteDisplayTitle(notes[0],[notes[0],duplicate])).not.toBe(noteDisplayTitle(duplicate,[notes[0],duplicate]));
  });
  it('keeps failed server-backed recordings inline and reserves floating recovery for orphan audio',()=>{
    const local={id:'recording',phase:'interrupted',noteId:'n1'} as LocalLecture;
    const status={captureComplete:true,recordingStatus:'failed',noteId:'n1'} as LectureStatus;
    expect(needsFloatingRecovery(local,status)).toBe(false);expect(processingStarted(status)).toBe(false);
    expect(needsFloatingRecovery({...local,noteId:null},undefined)).toBe(true);
    expect(processingStarted({...status,recordingStatus:'processing'} as LectureStatus)).toBe(true);
    expect(processingStarted({...status,recordingStatus:'completed'})).toBe(false);
  });
});
