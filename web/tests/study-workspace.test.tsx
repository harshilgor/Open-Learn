import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { WorkspacePanel, type WorkspacePanelLayout } from '@/components/workspace-panel';
import { WORKSPACE_NOTE_IMPROVE_EVENT, WORKSPACE_NOTE_MENTION_EVENT } from '@/lib/workspace-events';
const api = vi.hoisted(() => ({update:vi.fn()}));
vi.mock('@/lib/api', () => ({LearningApiError:class extends Error{}, friendlyServiceError:()=>({message:'Unavailable',detail:''}), learningApi:{
  listWorkspaceNotes:async()=>[{id:'n1',title:'Motion',frontmatter:{},revision:4,updatedAt:'2026-10-07'}], listCourses:async()=>[],
  getWorkspaceNote:async()=>({id:'n1',title:'Motion',body:'Velocity describes motion.',frontmatter:{},revision:4}), updateWorkspaceNote:api.update,
}}));
vi.mock('@/components/study-note-bar',()=>({StudyNoteBar:()=>null}));
vi.mock('@/components/study-note-panel',()=>({NoteProposalList:()=>null}));
vi.mock('@/components/visualization-reference',()=>({NoteVisualReferences:()=>null}));
vi.mock('@/components/flashcard-create',()=>({MakeFlashcards:()=>null}));
vi.mock('@/components/quiz-workspace',()=>({QuizWorkspace:()=>null,LessonPractice:()=>null}));
vi.mock('@/lib/voice/client',()=>({reportVoiceFocus:()=>undefined}));
let root:Root,container:HTMLDivElement;
function Harness(){const [layout,setLayout]=useState<WorkspacePanelLayout>({width:45,collapsed:false,tabs:['notes','sources','practice'],activeTab:'notes'});return <WorkspacePanel layout={layout} onLayoutChange={setLayout} onCollapse={()=>{}} onExpand={()=>{}} noteSeed={null} noteToOpen="n1" onNoteSeedConsumed={()=>{}} onNoteOpenConsumed={()=>{}}/>;}
beforeEach(async()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true; vi.useFakeTimers(); localStorage.clear(); vi.clearAllMocks(); HTMLElement.prototype.scrollIntoView=vi.fn(); api.update.mockImplementation(async(id,input)=>({...input,id,revision:5})); container=document.createElement('div');document.body.appendChild(container);root=createRoot(container); await act(async()=>{root.render(<Harness/>);await vi.advanceTimersByTimeAsync(250);}); await act(async()=>{await vi.advanceTimersByTimeAsync(250);});});
afterEach(()=>{act(()=>root.unmount());container.remove();window.getSelection()?.removeAllRanges();vi.useRealTimers();});
function selectPassage(){const p=container.querySelector('[aria-label="Note body"] p')!;const range=document.createRange();range.selectNodeContents(p);range.getBoundingClientRect=()=>({left:10,top:60,width:150,height:20} as DOMRect);window.getSelection()?.removeAllRanges();window.getSelection()?.addRange(range);act(()=>p.dispatchEvent(new MouseEvent('mouseup',{bubbles:true})));}
function click(label:string){const button=[...container.querySelectorAll('button')].find(item=>item.textContent===label);if(!button)throw Error(`Missing ${label}`);act(()=>button.click());}
it('links the exact saved revision and selected range to the prepared chat question',()=>{const receive=vi.fn();window.addEventListener(WORKSPACE_NOTE_MENTION_EVENT,receive);selectPassage();click('Give an example');expect(receive.mock.calls[0][0].detail).toMatchObject({noteId:'n1',revision:4,startOffset:0,endOffset:26,prompt:'Give an example:\n\nVelocity describes motion.'});window.removeEventListener(WORKSPACE_NOTE_MENTION_EVENT,receive);});
it('requests a reviewable suggestion without writing directly to the note',()=>{const receive=vi.fn();window.addEventListener(WORKSPACE_NOTE_IMPROVE_EVENT,receive);selectPassage();click('Suggest improvements');expect(receive.mock.calls[0][0].detail.noteId).toBe('n1');expect(api.update).not.toHaveBeenCalled();window.removeEventListener(WORKSPACE_NOTE_IMPROVE_EVENT,receive);});
it('persists a revisit checklist using the existing revision check',async()=>{selectPassage();click('Revisit later');await act(async()=>{await vi.advanceTimersByTimeAsync(800);});expect(api.update).toHaveBeenCalledWith('n1',expect.objectContaining({expectedRevision:4,body:expect.stringContaining('- [ ] Velocity describes motion.')}));});
