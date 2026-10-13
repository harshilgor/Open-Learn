import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CourseHome } from '@/components/course-home';
import { ChatHistory } from '@/components/chat-history';

const mocks = vi.hoisted(()=>({
  list: vi.fn(), request: vi.fn(), allNotes: vi.fn(), open: vi.fn(),
  snapshot: {profiles:[{id:'a',name:'Ada'},{id:'b',name:'Ben'}],chats:{old:'a',recent:'b'},classes:[],courses:{},defaultBuddyId:'a'},
}));
vi.mock('@/components/buddies',()=>({useBuddies:()=>({snapshot:mocks.snapshot,active:{id:'a'},refresh:async()=>{},select:vi.fn()}),CourseBuddy:()=> <div>Study partner</div>}));
vi.mock('@/components/course-study-planner',()=>({CourseStudyPlanner:()=> <div>Planning form</div>}));
vi.mock('@/components/canvas-connection',()=>({CanvasConnection:()=> <div>Canvas setup</div>}));
vi.mock('@/components/flashcard-workspace',()=>({FlashcardLibraryEntry:()=> <div>Flashcards</div>}));
vi.mock('@/components/material-library',()=>({MaterialLibrary:({initiallyOpen}:{initiallyOpen:boolean})=> <div>{initiallyOpen?'Open material library':'Closed material library'}</div>}));
vi.mock('@/lib/api',()=>({LearningApiError:class extends Error{},request:mocks.request,learningApi:{
  getCourse:async()=>({id:'physics',name:'Physics'}),listCourseSessions:async()=>({sessions:[{id:'old',title:'Forces',updatedAt:'2026-10-01T10:00:00Z'},{id:'recent',title:'Momentum',updatedAt:'2026-10-06T10:00:00Z'}]}),listCourseNotes:async()=>({notes:[]}),listChatSessions:mocks.list,listWorkspaceNotes:mocks.allNotes,
}}));
let root:Root, container:HTMLDivElement;
beforeEach(()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  vi.clearAllMocks();
  mocks.list.mockResolvedValue({sessions:[{id:'old',title:'Forces',updatedAt:'2026-10-01T10:00:00Z'},{id:'recent',title:'Momentum',updatedAt:'2026-10-06T10:00:00Z'}],total:2});
  mocks.request.mockImplementation(async(path:string)=>path==='/v1/quizzes'?{quizzes:[]}:{materials:[{id:'pdf',title:'Physics textbook',role:'textbook',status:'ready'}]});
  container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
});
afterEach(()=>{act(()=>root.unmount());container.remove();});
async function settle(){await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20));});}
function button(text:string){return [...container.querySelectorAll('button')].find(item=>item.textContent===text)!;}
it('resumes the most recent course chat and shows assets without loading attachment pickers',async()=>{
  await act(async()=>root.render(<CourseHome courseId="physics" onOpenSession={mocks.open} onNewSession={vi.fn()} onOpenNote={vi.fn()} onQuizSession={vi.fn()} onUpdated={vi.fn()} onDeleted={vi.fn()} onLaunchTask={async()=>''} onLaunchReady={vi.fn()}/>));
  await settle();
  expect(container.textContent).toContain('Physics textbook');
  expect(container.textContent).not.toContain('Planning form');
  expect(mocks.list).not.toHaveBeenCalled();expect(mocks.allNotes).not.toHaveBeenCalled();
  act(()=>button('Continue conversation').click());expect(mocks.open).toHaveBeenCalledWith('recent');
  act(()=>button('Study plan').click());expect(container.textContent).toContain('Planning form');expect(container.querySelector('h1')?.textContent).toBe('Physics');
  act(()=>button('Materials').click());expect(container.textContent).toContain('Open material library');
});
it('shows conversations across buddies in recency order and supports explicit filtering',async()=>{
  await act(async()=>root.render(<ChatHistory activeSessionId={null} refreshKey={0} onOpen={mocks.open}/>));await settle();
  const titles=()=>[...container.querySelectorAll('button[title]')].map(item=>item.getAttribute('title'));
  expect(titles()).toEqual(['Momentum','Forces']);
  act(()=>{const select=container.querySelector('select')!;select.value='a';select.dispatchEvent(new Event('change',{bubbles:true}));});
  expect(titles()).toEqual(['Forces']);
  act(()=>{const select=container.querySelector('select')!;select.value='';select.dispatchEvent(new Event('change',{bubbles:true}));});
  expect(titles()).toEqual(['Momentum','Forces']);
});
