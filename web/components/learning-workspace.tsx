"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ArrowUpRight, Bookmark, BookOpen, Check, ChevronRight, ChevronsUpDown, CircleHelp, Compass, ExternalLink, FileText, FolderClosed, FolderPlus, GitBranch, List, Maximize2, Minus, Network, PanelRight, Plus, RotateCcw, Search, Settings, Sparkles, SquarePen, X } from 'lucide-react';
import { Sidebar, SidebarContent, SidebarFooter, SidebarProvider, SidebarTrigger, useSidebar } from '@/components/ui/sidebar';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuShortcut, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { LearnChat } from '@/components/learn-chat';
import { MobileNavigation } from '@/components/mobile-navigation';
import { buddyApi } from '@/lib/buddies';
import { BuddyRail, BuddyHeader, useBuddies } from '@/components/buddies';
import { BuddyToday } from './buddy-today';
import { BuddyReminders } from './buddy-reminders';
import {CLASS_OPEN_EVENT,classApi,openClassWorkspace} from '@/lib/in-class';
import { QuizWorkspace } from '@/components/quiz-workspace';
import { ReviewWorkspace } from '@/components/review-workspace';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { maps, mapEdges, positions, type Gear, type LearningMap } from '@/lib/learning-content';
import { learningApi, type LessonArtifact, type CourseSummary } from '@/lib/api';
import { getJourney, navigateToSession, rememberSessionHint, resolveSessionHint, sessionIdFromPath, workflow } from '@/lib/learning-workflows';
import { LocalDataSettings } from '@/components/local-data-settings';
import { WorkspaceSplit, useWorkspacePanel } from '@/components/workspace-split';
import { NotesWorkspace } from '@/components/workspace-panel';
import { ChatHistory } from '@/components/chat-history';
import { CHAT_SESSION_OPEN_EVENT, REVIEW_ASK_TUTOR_EVENT, REVIEW_OPEN_EVENT, REVIEW_RETURN_EVENT, openWorkspaceFlashcards, openWorkspaceNote, openWorkspaceQuiz, requestWorkspaceQuiz, type ReviewAskTutorDetail, type ReviewOpenDetail } from '@/lib/workspace-events';
import { SettingsPage, type SettingsCategory } from '@/components/settings-page';
import { CourseDialog } from '@/components/course-dialog';
import { CourseHome } from '@/components/course-home';
import type { Task } from '@/components/course-study-planner';
import { ClassRecorder } from '@/components/class-recorder';
import { WorkspaceSidebar, type WorkspaceSidebarTab, type NotesCommand } from './workspace-sidebar';
import { sidebarTabFromPath, workspacePath } from '@/lib/workspace-navigation';

type Branch = { id:string;mapId:string;conceptId:string;anchor:string;mode:string;parent:string|null;draft:string;note:string };
type Stored = {version:1;mapId:string|null;conceptId:string;gear:Gear;visited:string[];branches:Branch[];saved:string[];ideas:string[]};
const INITIAL:Stored={version:1,mapId:null,conceptId:'whole',gear:'Quick',visited:[],branches:[],saved:[],ideas:[]};
const STORAGE='forma-workspace-v1';
const validGear=(v:string):v is Gear=>['Quick','Guided','Deep'].includes(v);

function MiniMap({index}:{index:number}){
 return <div className={'mini-map map-color-'+index}><svg viewBox="0 0 250 100" aria-hidden="true"><path d="M50 58 L105 30 L159 62 L209 33 M105 30 L119 82 M159 62 L119 82 M50 58 L119 82"/>{[[50,58],[105,30],[159,62],[209,33],[119,82]].map(([x,y],j)=><circle key={j} cx={x} cy={y} r={j===2?8:5}/>)}</svg><span>0{index+1}</span></div>
}

function NotesPanelTrigger() {
  const { collapsed, toggle } = useWorkspacePanel();
  return (
    <Button
      variant="ghost"
      size="icon"
      className={`h-7 w-7 text-muted-foreground hover:text-foreground ${!collapsed ? 'bg-muted text-foreground' : ''}`}
      aria-label={collapsed ? "Open study canvas" : "Close study canvas"}
      title={collapsed ? "Open study canvas" : "Close study canvas"}
      onClick={toggle}
    >
      <PanelRight size={15} />
    </Button>
  );
}

function AdaptiveSidebarTrigger({ inSidebar = false }: { inSidebar?: boolean }) {
  const { state, isMobile, openMobile } = useSidebar();
  const showInside = isMobile ? openMobile : state === 'expanded';
  if (inSidebar !== showInside) return null;
  return <SidebarTrigger className={inSidebar ? 'collapse-control' : undefined} aria-label={inSidebar ? 'Collapse sidebar' : isMobile ? 'Open chats and navigation' : 'Open sidebar'} title={isMobile ? 'Chats' : undefined} />;
}


export default function LearningWorkspace({
  initialSessionId = null,
  initialCourseId = null,
  initialSidebarTab = 'home',
}: {
  initialSessionId?: string | null;
  initialCourseId?: string | null;
  initialSidebarTab?: WorkspaceSidebarTab;
}) {
 const [state,setState]=useState<Stored>(INITIAL);
 const buddies=useBuddies();
 const appliedReminderLink=useRef('');
 const buddySnapshot=useRef(buddies.snapshot);
 useEffect(()=>{buddySnapshot.current=buddies.snapshot;},[buddies.snapshot]);
 const lastBuddyChats=useRef<Record<string,string|null>>({});
 const [learnVersion,setLearnVersion]=useState(0);
 const [ready,setReady]=useState(false);
  const [view,setView]=useState<'home'|'maps'|'saved'|'topic'|'quiz'|'notes'|'review'|'settings'|'course'|'reminders'|'courses'>(initialSidebarTab);
  const [sidebarTab, setSidebarTab] = useState<WorkspaceSidebarTab>(initialSidebarTab);
  const [notesHost, setNotesHost] = useState<HTMLDivElement | null>(null);
  const [notesCommand, setNotesCommand] = useState<NotesCommand | null>(null);
  const [courses,setCourses]=useState<CourseSummary[]>([]);
  const [activeCourseId,setActiveCourseId]=useState<string|null>(null);
  const [reminderId,setReminderId]=useState<string|null>(null);
  const [courseDialogOpen,setCourseDialogOpen]=useState(false);
  const [recordSetupOpen,setRecordSetupOpen]=useState(false);
  const [recordFolder,setRecordFolder]=useState<string|null>(null);
  const [recordedNoteId,setRecordedNoteId]=useState<string|null>(null);
  const [selectedNoteId,setSelectedNoteId]=useState<string|null>(null);
  const [settingsCategory,setSettingsCategory]=useState<SettingsCategory>('general');
  const [activeSessionId,setActiveSessionId]=useState<string|null>(initialSessionId);
  useEffect(()=>{const identifier=activeSessionId?buddies.snapshot?.chats[activeSessionId]:undefined;if(identifier&&identifier!==buddies.active?.id)buddies.select(identifier);},[activeSessionId,buddies.snapshot,buddies.active?.id,buddies.select]);
  useEffect(()=>{
    if(initialSessionId||!buddies.snapshot||new URLSearchParams(window.location.search).get('view')==='reminders')return;
    const hint=resolveSessionHint();let active=true;
    if(hint&&buddies.snapshot.chats[hint])queueMicrotask(()=>{if(active)setActiveSessionId(hint);});
    return()=>{active=false;};
  },[initialSessionId,buddies.snapshot]);
  useEffect(()=>{if(!buddies.snapshot)return;const query=new URLSearchParams(window.location.search);if(query.get('view')!=='reminders'||appliedReminderLink.current===window.location.search)return;appliedReminderLink.current=window.location.search;const buddy=query.get('buddy');if(buddy&&buddies.snapshot.profiles.some(p=>p.id===buddy))buddies.select(buddy);setReminderId(query.get('reminder'));setView('reminders');},[buddies.snapshot,buddies.select]);
  const [historyVersion,setHistoryVersion]=useState(0);
  const [chatTitle,setChatTitle]=useState('Chat');
  const [activeConceptTitle,setActiveConceptTitle]=useState<string|null>(null);
 const [quizContext,setQuizContext]=useState<{sessionId:string;conceptId?:string}|null>(null);
 const [reviewContext,setReviewContext]=useState<{sessionId?:string;conceptId?:string}|null>(null);
 const [reviewReturnBanner,setReviewReturnBanner]=useState<string|null>(null);
 const [askTutorPrompt,setAskTutorPrompt]=useState<string|null>(null);
 const [askTutorMode,setAskTutorMode]=useState<'ask'|'learn'>('ask');
 const [autoSubmitTutorPrompt,setAutoSubmitTutorPrompt]=useState(false);
 const [studyTask,setStudyTask]=useState<{taskId:string;courseId:string;revision:number;canonicalConceptIds:string[]}|null>(null);
 const [reviewDueCount,setReviewDueCount]=useState(0);
 const [mode,setMode]=useState('map');
 const [topic]=useState('');
 const [query,setQuery]=useState('');
  const [dialog,setDialog]=useState<'topic'|'setup'|null>(null);
 const [sources,setSources]=useState(false);
 const [branchId,setBranchId]=useState<string|null>(null);
 const [zoom,setZoom]=useState(1);
 const [outline,setOutline]=useState(false);
 const [localAction,setLocalAction]=useState('');
 const [checkOpen,setCheckOpen]=useState(false);
 const [answer,setAnswer]=useState<number|null>(null);
 const [selection,setSelection]=useState('');
  const [notice,setNotice]=useState('');
  const [insightBusy,setInsightBusy]=useState(false);
 const [generatedMap]=useState<LearningMap|null>(null);

 const [assistantLesson,setAssistantLesson]=useState<LessonArtifact|null>(null);
 const lessonRef=useRef<HTMLElement>(null);
 const branchRef=useRef<HTMLHeadingElement>(null);
 const triggerRef=useRef<HTMLElement|null>(null);
 const liveState=useRef(state);
 useEffect(()=>{liveState.current=state;},[state]);
 const currentMap=(generatedMap?.id===state.mapId?generatedMap:null)??maps.find(m=>m.id===state.mapId)??maps[0];
 const concept=currentMap.concepts.find(c=>c.id===state.conceptId)??currentMap.concepts[0];
 const branch=state.branches.find(b=>b.id===branchId);
 const branchMap=(generatedMap?.id===branch?.mapId?generatedMap:null)??maps.find(m=>m.id===branch?.mapId)??currentMap;
 const branchConcept=branchMap.concepts.find(c=>c.id===branch?.conceptId)??concept;
 const crumbs:Branch[]=[];
 if(branch){let b:Branch|undefined=branch;let guard=0;while(b&&guard++<20){crumbs.unshift(b);b=state.branches.find(p=>p.id===b?.parent);}}

 useEffect(()=>{
  const timer = window.setTimeout(() => {
    try{const raw=localStorage.getItem(STORAGE);if(raw){const d=JSON.parse(raw);if(d.version===1&&Array.isArray(d.visited)&&Array.isArray(d.branches)&&validGear(d.gear)){const strings=(a:unknown)=>Array.isArray(a)?a.filter(x=>typeof x==='string'):[];const restored={...INITIAL,mapId:maps.some(m=>m.id===d.mapId)?d.mapId:null,conceptId:typeof d.conceptId==='string'?d.conceptId:'whole',gear:d.gear,visited:strings(d.visited),branches:d.branches.filter((b:Branch)=>b&&typeof b.id==='string'&&typeof b.anchor==='string'&&typeof b.draft==='string'&&maps.some(m=>m.id===b.mapId)),saved:strings(d.saved),ideas:strings(d.ideas)};setState(restored);const ui=JSON.parse(localStorage.getItem(STORAGE+'-view')||'{}');if(['home','maps','saved','topic','settings'].includes(ui.view)){setMode(ui.mode==='lesson'?'lesson':'map');if(restored.branches.some((b:Branch)=>b.id===ui.branchId))setBranchId(ui.branchId);}}}}catch{setNotice('Your saved workspace could not be restored. You can still explore the samples.');}setReady(true);
  }, 0);
  return () => window.clearTimeout(timer);
 },[]);
 useEffect(()=>{if(!ready)return;try{localStorage.setItem(STORAGE,JSON.stringify(state));}catch{const timer = window.setTimeout(() => setNotice('Storage is unavailable. Changes will last only for this visit.'), 0); return () => window.clearTimeout(timer);}},[state,ready]);
 useEffect(()=>{if(!ready)return;try{localStorage.setItem(STORAGE+'-view',JSON.stringify({view,mode,branchId}));}catch{}},[ready,view,mode,branchId]);
 useEffect(()=>{if(!ready || typeof window==='undefined')return;const desktop=(window as Window & {formaDesktop?:unknown}).formaDesktop;if(!desktop||localStorage.getItem('forma-desktop-setup-v1'))return;const timer=window.setTimeout(()=>setDialog('setup'),0);return()=>window.clearTimeout(timer);},[ready]);
 useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(''),5000);return()=>clearTimeout(timer)},[notice]);
 useEffect(()=>{if(branchId)branchRef.current?.focus()},[branchId]);
  useEffect(()=>{const desktop=(window as Window & {formaDesktop?:{onOpenSettings?: (callback:()=>void)=>()=>void}}).formaDesktop;return desktop?.onOpenSettings?.(()=>{setSettingsCategory('general');setView('settings');setBranchId(null);});},[]);
  useEffect(()=>{const key=(e:KeyboardEvent)=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setView('home');setBranchId(null);setTimeout(()=>document.getElementById('topic')?.focus(),0)}if(e.key==='Escape'&&branchId){setBranchId(null);triggerRef.current?.focus();}const target=e.target as HTMLElement|null;const typing=target&&(target.tagName==='INPUT'||target.tagName==='TEXTAREA'||target.tagName==='SELECT'||target.isContentEditable);if(e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.altKey&&e.key===','&&!typing){e.preventDefault();setSettingsCategory('general');setView('settings');setBranchId(null);}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key)},[branchId]);

   function openSession(id:string|null,focus=true){
    if(id&&buddies.snapshot?.chats[id])buddies.select(buddies.snapshot.chats[id]);
    if(id&&buddies.snapshot?.chats[id]){const buddy=buddies.snapshot.chats[id];lastBuddyChats.current[buddy]=id;void buddyApi.remember(buddy,id).catch(()=>{});try{localStorage.setItem(`openlearn-last-chat:${buddy}`,id);}catch{}}
    rememberSessionHint(id);
    navigateToSession(id);
    try{localStorage.removeItem('forma-job:chat');}catch{/* Optional recovery pointer */}
    setSidebarTab('home');setActiveSessionId(id);setQuizContext(null);setLearnVersion(v=>v+1);setHistoryVersion(v=>v+1);setView('home');setBranchId(null);if(focus)setTimeout(()=>document.getElementById('chat-message')?.focus(),0);
  }
  function switchBuddy(id:string){
    if(buddies.active&&activeSessionId)lastBuddyChats.current[buddies.active.id]=activeSessionId;
    buddies.select(id);setActiveCourseId(null);
    let previous:string|null|undefined=lastBuddyChats.current[id]||buddies.snapshot?.lastChats[id];
    try{previous??=localStorage.getItem(`openlearn-last-chat:${id}`);}catch{}
    openSession(previous&&buddies.snapshot?.chats[previous]===id?previous:null);
  }
  useEffect(()=>{
    const opened=(event:Event)=>{const detail=(event as CustomEvent<{classId:string;sessionId?:string}>).detail;if(!detail?.classId)return;setView('home');if(detail.sessionId){openSession(detail.sessionId,false);window.history.replaceState({},'',window.location.pathname+'?class='+encodeURIComponent(detail.classId));void buddies.refresh();}else void classApi.snapshot(detail.classId).then(value=>{openSession(value.session.sessionId,false);window.history.replaceState({},'',window.location.pathname+'?class='+encodeURIComponent(detail.classId));void buddies.refresh();}).catch(()=>undefined);};
    window.addEventListener(CLASS_OPEN_EVENT,opened);return()=>window.removeEventListener(CLASS_OPEN_EVENT,opened);
  });
  const initialClassId=useRef(typeof window==='undefined'?null:new URLSearchParams(window.location.search).get('class'));
  useEffect(()=>{if(initialClassId.current)openClassWorkspace(initialClassId.current);},[]);
  const selectNote = useCallback((id: string | null) => {
    setSelectedNoteId(id);
    if (window.location.pathname === '/notes') window.history.replaceState({}, '', workspacePath('notes', activeSessionId, activeCourseId, id));
  }, [activeSessionId, activeCourseId]);
  function switchSidebarTab(tab: WorkspaceSidebarTab) {
    setSidebarTab(tab); setView(tab); setBranchId(null);
    window.history.pushState({}, '', workspacePath(tab, activeSessionId, activeCourseId, tab === 'notes' ? recordedNoteId || selectedNoteId : null));
  }
  function selectCourse(id: string | null) {
    setActiveCourseId(id); setView(sidebarTab); setBranchId(null);
    window.history.replaceState({}, '', workspacePath(sidebarTab, activeSessionId, id, selectedNoteId));
  }
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const timer = window.setTimeout(() => {
      if (query.has('course')) setActiveCourseId(query.get('course') || null);
      if (initialSidebarTab === 'notes' && query.get('note')) setRecordedNoteId(query.get('note'));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [initialSidebarTab]);
  useEffect(()=>{
    if(initialSessionId){
      rememberSessionHint(initialSessionId);
      const timer = window.setTimeout(() => {
        setActiveSessionId(initialSessionId);
      }, 0);
      return () => window.clearTimeout(timer);
    }
  },[initialSessionId]);
  useEffect(()=>{
    const onPop=()=>{
      const tab = sidebarTabFromPath(window.location.pathname);
      const query = new URLSearchParams(window.location.search);
      setSidebarTab(tab); setActiveCourseId(query.get('course') || null);
      if(query.get('view')==='reminders'){const buddy=query.get('buddy');if(buddy&&buddySnapshot.current?.profiles.some(p=>p.id===buddy))buddies.select(buddy);setReminderId(query.get('reminder'));setActiveSessionId(null);setView('reminders');return;}
      if (tab === 'notes') { setView('notes'); setRecordedNoteId(query.get('note')); return; }
      const fromRoute=sessionIdFromPath(window.location.pathname);
      rememberSessionHint(fromRoute);
      setActiveSessionId(fromRoute);
      setLearnVersion(v=>v+1);
      setHistoryVersion(v=>v+1);
      setView('home');
    };
    window.addEventListener('popstate',onPop);
    return()=>window.removeEventListener('popstate',onPop);
  },[]);
  useEffect(()=>{const sync=()=>{try{setActiveSessionId(resolveSessionHint());setHistoryVersion(v=>v+1);}catch{}};window.addEventListener('forma:chat-history-changed',sync);return()=>window.removeEventListener('forma:chat-history-changed',sync);},[]);
  useEffect(()=>{const refresh=()=>setHistoryVersion(v=>v+1);window.addEventListener('forma:chat-title-changed',refresh);return()=>window.removeEventListener('forma:chat-title-changed',refresh);},[]);
  useEffect(()=>{if(!activeSessionId){const timer=window.setTimeout(()=>{setChatTitle('Chat');setActiveConceptTitle(null);},0);return()=>window.clearTimeout(timer);}let live=true;void Promise.all([learningApi.getSession(activeSessionId),getJourney(activeSessionId).catch(()=>null)]).then(([session,journey])=>{if(!live)return;setChatTitle(session.title||session.goal||'Chat');setActiveCourseId(session.courseId||null);const step=journey?.steps.find(item=>item.conceptId===session.currentConceptId)||journey?.steps[journey.position];setActiveConceptTitle(step?.title||null);}).catch(()=>{if(live){setChatTitle('Chat');setActiveConceptTitle(null);}});return()=>{live=false;};},[activeSessionId,historyVersion]);
  useEffect(()=>{const open=(event:Event)=>{const id=(event as CustomEvent<string>).detail;if(typeof id==='string'&&id)openSession(id);};window.addEventListener(CHAT_SESSION_OPEN_EVENT,open);return()=>window.removeEventListener(CHAT_SESSION_OPEN_EVENT,open);},[]);
  useEffect(()=>{const open=(event:Event)=>{const detail=(event as CustomEvent<ReviewOpenDetail>).detail||{};setReviewContext({sessionId:detail.sessionId,conceptId:detail.conceptId});setView('review');setBranchId(null);};window.addEventListener(REVIEW_OPEN_EVENT,open);return()=>window.removeEventListener(REVIEW_OPEN_EVENT,open);},[]);
  useEffect(()=>{const open=(event:Event)=>{const id=(event as CustomEvent<string>).detail;if(typeof id==='string'&&id){setReviewContext({sessionId:id});setView('review');setBranchId(null);setReviewReturnBanner(null);}};window.addEventListener(REVIEW_RETURN_EVENT,open);return()=>window.removeEventListener(REVIEW_RETURN_EVENT,open);},[]);
  useEffect(()=>{const ask=(event:Event)=>{const detail=(event as CustomEvent<ReviewAskTutorDetail>).detail;if(!detail)return;setAskTutorPrompt(detail.prompt);setReviewReturnBanner(detail.returnReviewSessionId);setView('home');setBranchId(null);};window.addEventListener(REVIEW_ASK_TUTOR_EVENT,ask);return()=>window.removeEventListener(REVIEW_ASK_TUTOR_EVENT,ask);},[]);

  const refreshCourses = useCallback(async () => {
    try {
      const list = await learningApi.listCourses();
      setCourses(list);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshCourses();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshCourses]);

  useEffect(() => {
    if (initialCourseId) {
      const timer = window.setTimeout(() => {
        setActiveCourseId(initialCourseId);
        setView('course');
        setBranchId(null);
      }, 0);
      return () => window.clearTimeout(timer);
    }
  }, [initialCourseId]);

  useEffect(() => {
    if (!activeSessionId) return;
    if (new URLSearchParams(window.location.search).has('course') || window.location.pathname === '/notes') return;
    let cancelled = false;
    void learningApi.getSession(activeSessionId).then((sess) => {
      if (!cancelled && sess.courseId !== undefined) {
        setActiveCourseId(sess.courseId || null);
      }
    }).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [activeSessionId]);

  useEffect(()=>{let active=true;void learningApi.getReviewDashboard().then(dash=>{if(active)setReviewDueCount(dash.dueCount||0);}).catch(()=>undefined);return()=>{active=false;};},[view,historyVersion]);
  function openMap(id:string){const m=maps.find(x=>x.id===id);if(!m)return;setAssistantLesson(null);setState(s=>({...s,mapId:id,conceptId:s.mapId===id?s.conceptId:m.concepts[0].id}));setView('topic');setMode('map');setBranchId(null);setZoom(1);setQuery('');setSelection('');}
 function openConcept(id:string){if(!currentMap.concepts.some(c=>c.id===id))return;setState(s=>({...s,conceptId:id,visited:Array.from(new Set([...s.visited,`${currentMap.id}:${id}`]))}));setMode('lesson');setLocalAction('');setAnswer(null);setCheckOpen(false);setSelection('');setBranchId(null);}

 function openBranch(anchor:string,action='Explain',parent:string|null=null){triggerRef.current=document.activeElement as HTMLElement;const base=parent?state.branches.find(b=>b.id===parent):null;const b:Branch={id:crypto.randomUUID(),mapId:base?.mapId??currentMap.id,conceptId:base?.conceptId??concept.id,anchor:anchor.slice(0,600),mode:action,parent,draft:'',note:''};setState(s=>({...s,branches:[...s.branches,b]}));setBranchId(b.id);setSelection('');}
  function closeBranch(){setBranchId(null);setTimeout(()=>triggerRef.current?.focus(),0);}
  async function saveBranchInsight(){
    if(!branch||insightBusy)return;
    const sid:string|null=activeSessionId||resolveSessionHint();
    if(!sid){setNotice('Start or open a chat first — insights belong to a living study note.');return;}
    const explanation=branch.mode==='Why?'?branchConcept.why:branchConcept.detail;
    const source=`${branch.anchor}\n\n${explanation}\n\nExample: ${branchConcept.example}`.slice(0,4000);
    setInsightBusy(true);
    try{
      const link=await learningApi.getStudyNote(sid).catch(()=>null);
      await workflow(`/sessions/${sid}/note-proposals`,{origin:'insight',sourceText:source,sourceLabel:branchConcept.title.slice(0,200),expectedNoteRevision:link?.revision??null},`note-proposal:branch:${sid}:${branch.id}`);
      setNotice('Insight proposed — review it in the chat.');
    }catch(cause){setNotice(cause instanceof Error?cause.message:'The insight could not be proposed.');}
    finally{setInsightBusy(false);}
  }
  function saveLesson(){const id=`${currentMap.id}:${concept.id}`;setState(s=>({...s,saved:s.saved.includes(id)?s.saved.filter(x=>x!==id):[...s.saved,id]}));}
  function setGear(v:string){if(validGear(v)){setState(s=>({...s,gear:v}));setLocalAction('');}}
  function onSelection(){const sel=window.getSelection();if(sel&&sel.toString().trim()&&lessonRef.current?.contains(sel.anchorNode)){setSelection(sel.toString().trim().slice(0,600));}}
  function followBranch(){if(!branch?.draft.trim())return;const text=branch.draft.trim();const matched=branchMap.concepts.find(c=>text.toLowerCase().includes(c.title.toLowerCase()));const b:Branch={id:crypto.randomUUID(),mapId:branchMap.id,conceptId:matched?.id??branch.conceptId,anchor:text,mode:matched?'Explain':'Question',parent:branch.id,draft:'',note:matched?'':'Live answers are not connected in this preview. Here is the sample explanation for this concept; your question is saved.'};setState(s=>({...s,branches:[...s.branches.map(x=>x.id===branch.id?{...x,draft:''}:x),b]}));setBranchId(b.id);}

 useEffect(()=>{
  const ctx=(document as Document & {modelContext?:{registerTool:(tool:unknown,options:unknown)=>void}}).modelContext;
  if(!ctx?.registerTool)return;const lifecycle=new AbortController();
  const register=async()=>{await ctx.registerTool({name:'open_sample_learning_map',description:'Open one of the three sample learning maps in this preview. Does not generate an AI map.',inputSchema:{type:'object',properties:{mapId:{type:'string',enum:maps.map(m=>m.id)}},required:['mapId'],additionalProperties:false},annotations:{readOnlyHint:false},execute:async(input:unknown)=>{const id=(input as {mapId?:string})?.mapId;if(!id||!maps.some(m=>m.id===id))throw new Error('Choose systems, light, or calculus.');openMap(id);await new Promise(resolve=>setTimeout(resolve,0));return{mapId:id,status:'opened',content:'sample'};}},{signal:lifecycle.signal});await ctx.registerTool({name:'read_learning_workspace',description:'Read the selected sample map, teaching gear, and locally explored concepts.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true},execute:()=>({mapId:liveState.current.mapId,conceptId:liveState.current.conceptId,gear:liveState.current.gear,explored:liveState.current.visited})},{signal:lifecycle.signal});};void register().catch(()=>{});return()=>lifecycle.abort();
 },[]);

   return <SidebarProvider className="forma-app-shell" style={{'--sidebar-width':'260px'} as CSSProperties}>
  <BuddyRail onSwitch={switchBuddy} onHome={()=>openSession(null)} onSettings={()=>{setSettingsCategory('general');setView('settings');}} />
  {view==='settings'?<div className="settings-full"><SettingsPage category={settingsCategory} onCategoryChange={setSettingsCategory} onBack={()=>setView('home')} /></div>:<><Sidebar className="forma-sidebar"><SidebarContent>
    <WorkspaceSidebar tab={sidebarTab} onTabChange={switchSidebarTab} collapseControl={<AdaptiveSidebarTrigger inSidebar />} courses={courses} activeCourseId={activeCourseId} onCourseSelect={selectCourse} onCourseOpen={id=>{setActiveCourseId(id);setView('course');setBranchId(null);}} onNewChat={()=>openSession(null)} onNewCourse={()=>setCourseDialogOpen(true)} onNotesCommand={action=>setNotesCommand(current=>({id:(current?.id||0)+1,action}))} onReminders={()=>setView('reminders')} onReview={()=>{setView('review');setBranchId(null);}} onQuiz={()=>{setView('quiz');setBranchId(null);}} activeSessionId={activeSessionId} refreshKey={historyVersion} onOpenSession={openSession} notesHost={setNotesHost} />
   </SidebarContent><SidebarFooter><DropdownMenu><DropdownMenuTrigger asChild><button className="profile" aria-label="Account menu"><span className="avatar">L</span><div>Learner</div><ChevronsUpDown size={15}/></button></DropdownMenuTrigger><DropdownMenuContent side="top" align="start" sideOffset={8} className="w-[224px] learner-menu"><DropdownMenuLabel><div className="flex items-center gap-2.5"><span className="avatar">L</span><div className="grid gap-0.5"><strong className="text-sm font-semibold leading-none">Learner</strong><small className="text-xs text-muted-foreground">Free · On this device</small></div></div></DropdownMenuLabel><DropdownMenuSeparator /><DropdownMenuItem onSelect={()=>openSession(null)}><Plus size={15}/>New topic<DropdownMenuShortcut>⌘ K</DropdownMenuShortcut></DropdownMenuItem><DropdownMenuItem onSelect={()=>{setSettingsCategory('general');setView('settings');setBranchId(null);}}><Settings size={15}/>Settings<DropdownMenuShortcut>Ctrl+,</DropdownMenuShortcut></DropdownMenuItem><DropdownMenuItem onSelect={()=>{setSettingsCategory('about');setView('settings');setBranchId(null);}}><CircleHelp size={15}/>About Open Learn</DropdownMenuItem></DropdownMenuContent></DropdownMenu></SidebarFooter></Sidebar>
    <WorkspaceSplit quizSessionId={quizContext?.sessionId} quizConceptId={quizContext?.conceptId} hidePanel={view==='notes'||view==='review'||view==='course'||view==='reminders'||view==='courses'}><main className={'workspace '+(branch?'with-branch':'')+(view==='home'?' chat-focus':'')}><header className="topbar">
      <div className="flex items-center gap-2">
        <AdaptiveSidebarTrigger/>
        <Button className="buddy-desktop-action" variant="ghost" size="sm" onClick={()=>openSession(null)}>Today</Button>
        <Button className="buddy-desktop-action" variant="ghost" size="sm" onClick={()=>setView('reminders')}>Reminders</Button>
        <BuddyHeader onSwitch={switchBuddy} />
        {view === 'course' ? (
          <><button className="text-muted-foreground hover:text-foreground transition-colors" onClick={()=>{setView('courses');setActiveCourseId(null);}}>Courses</button><ChevronRight size={13}/><strong className="truncate max-w-[200px]">{courses.find((c) => c.id === activeCourseId)?.name || 'Course'}</strong></>
        ) : view === 'home' && activeCourseId ? (
          <><button className="text-muted-foreground hover:text-foreground transition-colors truncate max-w-[160px]" onClick={()=>{setView('course');}}>{courses.find((c) => c.id === activeCourseId)?.name || 'Course'}</button><ChevronRight size={13}/><strong className="truncate max-w-[210px]" title={chatTitle}>{chatTitle}</strong>{activeConceptTitle?<><ChevronRight size={13}/><span className="truncate max-w-[160px]" title={activeConceptTitle}>{activeConceptTitle}</span></>:null}{(courses.find(c=>c.id===activeCourseId)?.roadmapProgress||0)>0?<span className="header-progress" role="img" aria-label={`${courses.find(c=>c.id===activeCourseId)?.roadmapProgress}% course progress`} style={{'--progress':`${courses.find(c=>c.id===activeCourseId)?.roadmapProgress}%`} as CSSProperties}/>:null}</>
        ) : (
          <><strong className="text-foreground font-medium truncate max-w-[250px]" title={view==='home'?chatTitle:undefined}>{view==='topic'?currentMap.title:view==='saved'?'Saved explorations':view==='maps'?'Knowledge maps':view==='quiz'?'Quiz':view==='notes'?'Notes':view==='review'?'Review':view==='reminders'?'Reminders':view==='courses'?'Courses':chatTitle}</strong>{view==='home'&&activeConceptTitle?<><ChevronRight size={13}/><span className="truncate max-w-[160px]" title={activeConceptTitle}>{activeConceptTitle}</span></>:null}</>
        )}
      </div>
      <div className="flex items-center gap-2">
        {reviewDueCount > 0 ? <Button variant="outline" size="sm" className="review-due-button" onClick={()=>{setView('review');setBranchId(null);}}>Review · {reviewDueCount} due</Button> : null}
        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-foreground" aria-label="Open settings" onClick={()=>{setSettingsCategory('general');setView('settings');setBranchId(null);}}><Settings size={14}/></Button>
        {view !== 'notes' && view !== 'review' && view !== 'course' ? <NotesPanelTrigger /> : null}
      </div>
    </header>
   {reviewReturnBanner?<div className="toast-message" role="status"><RotateCcw size={16}/>Return to your review when you are ready.<button type="button" onClick={()=>{if(reviewReturnBanner.startsWith('fcr_'))openWorkspaceFlashcards({view:'review',reviewSessionId:reviewReturnBanner});else{setReviewContext({sessionId:reviewReturnBanner});setView('review');}setReviewReturnBanner(null);}}>Return to Review</button><button onClick={()=>setReviewReturnBanner(null)} aria-label="Dismiss"><X size={14}/></button></div>:null}
   {view==='home'&&!activeSessionId?<BuddyToday onClass={id=>{setActiveCourseId(id);setRecordSetupOpen(true);}} onPrep={(id,title)=>{const buddy=buddies.snapshot?.courses[id]||buddies.snapshot?.defaultBuddyId;if(buddy)buddies.select(buddy);setActiveCourseId(id);openSession(null);setAskTutorPrompt(`Help me prepare for ${title}. Use my course materials when available.`);setAutoSubmitTutorPrompt(false);}} courses={courses} due={reviewDueCount} onCourse={id=>{setActiveCourseId(id);setView('course');}} onReview={()=>setView('review')} onAdd={()=>setCourseDialogOpen(true)} onReminders={()=>setView('reminders')}/>:null}
   {view==='reminders'?<BuddyReminders initialReminderId={reminderId} onCourse={id=>{setActiveCourseId(id);setView('course');}}/>:null}
   {view==='courses'?<section className="buddy-home"><h2>Your courses</h2><Button onClick={()=>setCourseDialogOpen(true)}>Add a course</Button>{courses.map(course=>{const id=buddies.snapshot?.courses[course.id]||buddies.snapshot?.defaultBuddyId;return <button className="nav-item" key={course.id} onClick={()=>{setActiveCourseId(course.id);setView('course');}}>{course.name} · {buddies.snapshot?.profiles.find(p=>p.id===id)?.name||'Buddy'}</button>;})}{!courses.length?<p>Add a course to organize your chats and class sessions.</p>:null}</section>:null}
   <div className="chat-view" hidden={view!=='home'}><LearnChat onMissingSession={()=>openSession(null)} key={`${learnVersion}:${buddies.active?.id}`} onInClass={()=>setRecordSetupOpen(true)} onSessionCreated={id=>{setActiveSessionId(id);if(buddies.active){lastBuddyChats.current[buddies.active.id]=id;void buddyApi.remember(buddies.active.id,id).catch(()=>{});try{localStorage.setItem(`openlearn-last-chat:${buddies.active.id}`,id);}catch{}}}} initialSessionId={activeSessionId} initialPrompt={askTutorPrompt||undefined} preferredMode={askTutorMode} autoSubmitInitialPrompt={autoSubmitTutorPrompt} studyTask={studyTask} onStudyTaskCompleted={()=>setStudyTask(null)} onInitialPromptConsumed={()=>{setAskTutorPrompt(null);setAutoSubmitTutorPrompt(false);}} onQuiz={async (sessionId,conceptId,origin='ask',requestedTopic,sourceTransitionId)=>{const lessonNoteId=origin==='learn'?(await learningApi.createStudyNote(sessionId)).noteId:undefined;setQuizContext({sessionId,conceptId});setView('home');openWorkspaceQuiz({sessionId,conceptId,origin,requestedTopic,lessonNoteId,sourceTransitionId});}} onReview={(sessionId,conceptId)=>{setReviewContext({sessionId,conceptId});setView('review')}} courseId={activeCourseId} courseName={courses.find(c => c.id === activeCourseId)?.name} onCourseClick={(cid)=>{setActiveCourseId(cid);setView('course');}} /></div>
   {view==='course'&&activeCourseId?<CourseHome key={activeCourseId} onSavedQuiz={quiz=>{openSession(quiz.sessionId);openWorkspaceQuiz({sessionId:quiz.sessionId,quizId:quiz.id,lessonNoteId:quiz.lessonNoteId||undefined,origin:quiz.origin==='learn'?'learn':'ask'});}} onStartClass={()=>setRecordSetupOpen(true)} courseId={activeCourseId} onOpenSession={(sid)=>openSession(sid)} onNewSession={()=>{const buddy=buddies.snapshot?.courses[activeCourseId]||buddies.snapshot?.defaultBuddyId;if(buddy)buddies.select(buddy);openSession(null);}} onOpenNote={(nid)=>{setRecordedNoteId(nid);switchSidebarTab('notes');}} onQuizSession={(sid)=>{void Promise.all([learningApi.getSession(sid),learningApi.getStudyNote(sid)]).then(([session,note])=>{setActiveSessionId(sid);setQuizContext({sessionId:sid});setView('home');openWorkspaceQuiz({sessionId:sid,origin:note?'learn':'ask',lessonNoteId:note?.noteId,requestedTopic:session.goal||undefined});}).catch(cause=>setNotice(cause instanceof Error?cause.message:'Could not open this quiz.'));}} onLaunchTask={async(task:Task)=>{const topic=String(task.launch.requestedTopic||task.reason).slice(0,200);const session=await learningApi.createSession({topic,goal:task.reason,courseId:activeCourseId||undefined});setActiveCourseId(activeCourseId);openSession(session.id);return session.id;}} onLaunchReady={(task:Task,sessionId:string,revision:number)=>{const workflow=String(task.launch.workflow);const topic=String(task.launch.requestedTopic||task.reason);const canonicalConceptIds=task.conceptIds||[];if(workflow==='quiz'){setQuizContext({sessionId,conceptId:undefined});openWorkspaceQuiz({sessionId,origin:'ask',requestedTopic:topic,taskId:task.id,taskCourseId:activeCourseId||undefined,taskRevision:revision,canonicalConceptIds});return;}setStudyTask({taskId:task.id,courseId:activeCourseId||'',revision,canonicalConceptIds});setAskTutorMode('learn');setAskTutorPrompt(`Teach me ${topic}. Focus on the learning task: ${task.reason}`);setAutoSubmitTutorPrompt(true);}} onUpdated={()=>{void refreshCourses();setHistoryVersion(v=>v+1);}} onDeleted={()=>{setActiveCourseId(null);setView('home');void refreshCourses();}} />:null}
  <div className="notes-view" hidden={view!=='notes'}><NotesWorkspace listHost={notesHost} courses={courses} courseFilter={activeCourseId} onCourseFilter={selectCourse} command={notesCommand} onRecordClass={folder=>{setRecordFolder(folder);setRecordSetupOpen(true);}} noteToOpen={recordedNoteId || selectedNoteId} onNoteOpenConsumed={()=>setRecordedNoteId(null)} onNoteSelected={selectNote} /></div>
  {view==='quiz' ? <QuizWorkspace historyOnly sessionId={quizContext?.sessionId} conceptId={quizContext?.conceptId} onStartQuiz={()=>{setView('home');requestWorkspaceQuiz();}} onReturn={()=>setView('home')} onReviewInLearn={suggestion=>{
    const sid = quizContext?.sessionId || activeSessionId;
    if (!sid) { setNotice('Open the original conversation to review this topic.'); return; }
    void learningApi.recordTransitionInteraction(suggestion.id, 'accept', 'learn', sid, suggestion.modeRevision ?? undefined).then(()=>{
      setActiveSessionId(sid); setQuizContext(null); setAskTutorMode('learn');
      setAskTutorPrompt(String(suggestion.context.seedPrompt || `Review ${suggestion.context.conceptTitle || 'this concept'}, focusing on my missed quiz questions.`));
      setAutoSubmitTutorPrompt(true); setView('home');
      return learningApi.recordTransitionInteraction(suggestion.id, 'applied', 'learn', sid);
    }).catch(cause=>setNotice(cause instanceof Error?cause.message:'The review could not be started.'));
  }} /> : null}
  {view==='review' ? <ReviewWorkspace resumeSessionId={reviewContext?.sessionId} focusConceptId={reviewContext?.conceptId} onDone={()=>setView('home')} onStartLearning={()=>setView('home')} /> : null}
  {view==='maps'?<div className="library-content"><div className="eyebrow">YOUR SPACE</div><h1>Knowledge maps</h1><p className="intro">A growing collection of connected ideas.</p><div className="search-field"><Search size={16}/><input aria-label="Search maps" placeholder="Find a map…" value={query} onChange={e=>setQuery(e.target.value)}/></div><div className="map-cards">{maps.filter(m=>m.title.toLowerCase().includes(query.toLowerCase())).map(m=><button className="map-card" key={m.id} onClick={()=>openMap(m.id)}><MiniMap index={maps.indexOf(m)}/><div className="map-card-body"><small>SAMPLE MAP</small><h3>{m.title}<ArrowUpRight size={16}/></h3><p>{m.description}</p></div></button>)}</div>{!maps.some(m=>m.title.toLowerCase().includes(query.toLowerCase()))?<div className="empty-state"><Search size={24}/><h2>No matching maps</h2><p>Try “systems”, “light”, or “calculus”.</p><Button variant="outline" onClick={()=>setQuery('')}>Clear search</Button></div>:null}{state.ideas.length>0?<section className="ideas"><h2>Ideas for later</h2><p>Saved on this device. Live map generation is not connected yet.</p>{state.ideas.map(t=><div key={t}><Sparkles size={15}/>{t}</div>)}</section>:null}</div>:null}
  {view==='saved'?<div className="library-content"><div className="eyebrow">YOUR SPACE</div><h1>Keep the useful parts.</h1><p className="intro">Saved lessons and the questions you followed.</p>{state.saved.length+state.branches.length===0?<div className="empty-state"><Bookmark size={28}/><h2>A little space for your discoveries.</h2><p>Save a lesson or open an exploration. It will be waiting here.</p><Button variant="outline" onClick={()=>setView('maps')}>Explore the maps <ArrowRight size={15}/></Button></div>:<div className="saved-list">{state.saved.map(id=>{const [mi,ci]=id.split(':');const m=maps.find(m=>m.id===mi);const c=m?.concepts.find(c=>c.id===ci);return c&&m?<button key={id} onClick={()=>{setState(s=>({...s,mapId:mi,conceptId:ci}));setView('topic');setMode('lesson')}}><Bookmark size={18}/><span><strong>{c.title}</strong><small>{m.title} · Saved lesson</small></span><ChevronRight size={16}/></button>:null})}{state.branches.map(b=><button key={b.id} onClick={()=>{setState(s=>({...s,mapId:b.mapId,conceptId:b.conceptId}));setView('topic');setMode('lesson');setBranchId(b.id)}}><GitBranch size={18}/><span><strong>{b.anchor}</strong><small>{maps.find(m=>m.id===b.mapId)?.title} · {b.mode}</small></span><ChevronRight size={16}/></button>)}</div>}</div>:null}
  {view==='topic'?<div className="topic-workspace"><div className="topic-heading"><div><span className="eyebrow">{currentMap.id.startsWith('generated:')?'LIMITED DRAFT GRAPH':'SAMPLE LEARNING MAP'}</span><h1>{currentMap.title}</h1><p>{currentMap.description}</p></div><button className="source-button" onClick={()=>setSources(true)}><BookOpen size={15}/>{currentMap.id.startsWith('generated:')?'Trust status':'Reading reference'}<ArrowUpRight size={13}/></button></div>
  {assistantLesson?<section className="chat-response" aria-label="Tutor response"><div className="chat-user-message"><span className="chat-avatar">Y</span><p>{topic}</p></div><article className="chat-assistant-message"><div className="chat-response-meta"><span className="assistant-mark"><Sparkles size={14}/></span><strong>Forma</strong><span>First lesson · {assistantLesson.gear}</span></div>{assistantLesson.blocks.filter(block=>block.kind!=='source_note').map(block=><div className="chat-block" key={block.id}>{block.heading?<h3>{block.heading}</h3>:null}<p>{block.body}</p></div>)}<div className="chat-trust-note"><CircleHelp size={14}/><span>{assistantLesson.generatedBy?.startsWith('openrouter/')?'This lesson was written with an AI model. It has no retrieved citations or independent verification, and does not update mastery.':'This first response is a deterministic scaffold with insufficient source support. It is useful for testing the learning flow and does not update mastery.'}</span></div></article></section>:null}
   <div className="topic-toolbar"><Tabs value={mode} onValueChange={v=>{setMode(v);setBranchId(null)}}><TabsList><TabsTrigger value="map"><Network size={15}/>Map</TabsTrigger><TabsTrigger value="lesson"><BookOpen size={15}/>Learn</TabsTrigger></TabsList></Tabs><span className="explored-count">{state.visited.filter(x=>x.startsWith(currentMap.id+':')).length} of {currentMap.concepts.length} explored</span><div className="gear-control"><span>Teaching gear</span><Select value={state.gear} onValueChange={setGear}><SelectTrigger aria-label="Teaching gear"><Sparkles size={14}/><SelectValue/></SelectTrigger><SelectContent>{(['Quick','Guided','Deep'] as Gear[]).map(g=><SelectItem key={g} value={g}>{g}</SelectItem>)}</SelectContent></Select></div></div>
   {mode==='map'?<><div className="graph-surface"><div className="graph-caption"><span>THE CONNECTIONS</span><p>Choose an idea to begin.</p></div><div className="graph-scroll"><div className="graph-inner" style={{transform:`scale(${zoom})`}}><svg className="graph-lines" viewBox="0 0 1100 360" aria-hidden="true">{mapEdges.map(([a,b])=><path key={`${a}-${b}`} d={`M ${positions[a][0]} ${positions[a][1]} C ${positions[a][0]+100} ${positions[a][1]}, ${positions[b][0]-100} ${positions[b][1]}, ${positions[b][0]} ${positions[b][1]}`}/>)}</svg>{currentMap.concepts.map((c,i)=><button key={c.id} aria-label={`Learn ${c.title}`} className={'concept-node '+(c.id===concept.id?'selected ':'')+(state.visited.includes(`${currentMap.id}:${c.id}`)?'explored':'')} style={{left:positions[i][0],top:positions[i][1]}} onClick={()=>openConcept(c.id)}><span className="node-symbol">{state.visited.includes(`${currentMap.id}:${c.id}`)?<Check size={13}/>:<span/>}</span><strong>{c.title}</strong><small>{c.label}</small></button>)}</div></div><div className="graph-bottom"><span><i/> Suggested learning connections</span><div><Button variant="ghost" size="icon" aria-label="Zoom out" onClick={()=>setZoom(z=>Math.max(.65,z-.15))}><Minus size={15}/></Button><span>{Math.round(zoom*100)}%</span><Button variant="ghost" size="icon" aria-label="Zoom in" onClick={()=>setZoom(z=>Math.min(1.45,z+.15))}><Plus size={15}/></Button><Button variant="ghost" size="icon" aria-label="Reset zoom" onClick={()=>setZoom(1)}><Maximize2 size={14}/></Button></div></div></div><div className="below-map"><span><CircleHelp size={15}/>Connections are suggested learning paths, not mastery requirements.</span><button onClick={()=>setOutline(x=>!x)}><List size={15}/>{outline?'Hide':'Show'} concept list</button></div>{outline?<div className="concept-list">{currentMap.concepts.map((c,i)=><button key={c.id} onClick={()=>openConcept(c.id)}><span>0{i+1}</span><strong>{c.title}</strong><small>{c.label}</small><ArrowRight size={15}/></button>)}</div>:null}<button className="start-lesson" onClick={()=>openConcept(concept.id)}><span className="resume-icon"><BookOpen size={19}/></span><span><small>YOUR NEXT EXPLORATION</small><strong>{concept.title}</strong><p>{concept.summary}</p></span><ArrowRight size={20}/></button></>:null}
   {mode==='lesson'?<><div className="concept-path">{currentMap.concepts.map((c,i)=><button key={c.id} className={concept.id===c.id?'active':''} onClick={()=>openConcept(c.id)}><span>{i+1}</span>{c.title}</button>)}</div><article className="lesson" ref={lessonRef} onMouseUp={onSelection} onKeyUp={onSelection}><div className="lesson-meta"><span>CONCEPT {currentMap.concepts.indexOf(concept)+1} / {currentMap.concepts.length}</span><button aria-label={state.saved.includes(`${currentMap.id}:${concept.id}`)?'Unsave lesson':'Save lesson'} onClick={saveLesson}><Bookmark size={17} fill={state.saved.includes(`${currentMap.id}:${concept.id}`)?'currentColor':'none'}/></button></div><h2>{concept.title}</h2><p className="lesson-lead">{concept.summary}</p>
    {state.gear!=='Quick'||localAction==='Go deeper'||localAction==='Simpler'?<div className="lesson-copy"><h3>{localAction==='Simpler'?'In everyday terms':'Let’s build the intuition.'}</h3><p>{localAction==='Simpler'?concept.example:concept.detail}</p>{localAction==='Simpler'&&state.gear==='Deep'?<p>{concept.detail}</p>:null}</div>:null}
    {state.gear!=='Quick'||localAction==='Example'?<div className="example-block"><div><span className="example-icon"><Sparkles size={15}/></span><small>A CONCRETE EXAMPLE</small></div><p>{concept.example}</p><button onClick={()=>openBranch(concept.example,'Why?')}>Why does this work?<ArrowUpRight size={13}/></button></div>:null}
    {state.gear==='Deep'||localAction==='Go deeper'?<div className="deep-block"><h3>Connect it to the bigger picture.</h3><p>{concept.why} {currentMap.concepts[(currentMap.concepts.indexOf(concept)+1)%currentMap.concepts.length].summary}</p><p className="muted">The map’s connections offer a route for exploring these ideas. They do not mean every idea is a strict prerequisite.</p></div>:null}
    {localAction==='Visualize'?<div className="concept-visual"><small>IDEA → EXAMPLE → CONNECTION</small><div><span>{concept.title}</span><ArrowRight size={18}/><span>{concept.label}</span></div><p>{concept.example}</p></div>:null}
    {selection?<div className="selection-actions"><span>“{selection.slice(0,75)}{selection.length>75?'…':''}”</span><Button size="sm" onClick={()=>openBranch(selection)}>Explain selection<ArrowUpRight size={13}/></Button></div>:null}
    <div className="lesson-actions">{['Simpler','Go deeper','Example','Visualize'].map(a=><button className={localAction===a?'active':''} key={a} onClick={()=>setLocalAction(a)}>{a==='Simpler'?<ArrowDown size={14}/>:a==='Go deeper'?<Plus size={14}/>:a==='Example'?<Sparkles size={14}/>:<Network size={14}/>} {a}</button>)}<button onClick={()=>openBranch(concept.summary)}><GitBranch size={14}/>Explore this</button></div>
    <div className="understanding"><div><span className="eyebrow">A MOMENT TO REFLECT</span><h3>Make the idea your own.</h3><p>A short check, whenever you feel ready.</p></div><Button variant="outline" onClick={()=>{setCheckOpen(v=>!v);setAnswer(null)}}>{checkOpen?'Close check':'Check understanding'}<ArrowRight size={15}/></Button></div>
    {checkOpen?<div className="quick-check"><h3>{concept.question}</h3>{concept.choices.map((choice,i)=><button className={answer===i?(i===concept.answer?'correct':'incorrect'):''} key={choice} onClick={()=>setAnswer(i)} disabled={answer!==null}><span>{String.fromCharCode(65+i)}</span>{choice}{answer===i?<Check size={15}/>:null}</button>)}{answer!==null?<div role="status" className="check-feedback"><strong>{answer===concept.answer?'That’s right.':'Let’s look at that again.'}</strong><p>{concept.why}</p><small>This sample check does not assign a mastery score.</small><button onClick={()=>setAnswer(null)}>Try again</button></div>:null}</div>:null}
    <div className="lesson-footer"><span>Sample lesson · Select a passage to ask about it.</span><button onClick={()=>{const next=currentMap.concepts[(currentMap.concepts.indexOf(concept)+1)%currentMap.concepts.length];openConcept(next.id);lessonRef.current?.scrollIntoView({behavior:'smooth',block:'start'})}}>Next concept<ArrowRight size={15}/></button></div>
   </article></>:null}
  </div>:null}
   </main></WorkspaceSplit></>}
  {branch?<aside className="exploration-panel" aria-label="Exploration panel"><header><div><GitBranch size={16}/><span>Exploration</span></div><Button variant="ghost" size="icon" aria-label="Close exploration" onClick={closeBranch}><X size={18}/></Button></header><div className="branch-breadcrumb"><button onClick={closeBranch}>Lesson</button>{crumbs.map((b,i)=><span key={b.id}><ChevronRight size={11}/><button onClick={()=>setBranchId(b.id)}>{i+1}</button></span>)}</div><div className="branch-scroll"><small className="eyebrow">{branch.mode==='Question'?'YOUR QUESTION':'DETAILS'}</small><h2 ref={branchRef} tabIndex={-1}>{branch.mode==='Why?'?'Why does this work?':branchConcept.title}</h2><blockquote>{branch.anchor}</blockquote>{branch.note?<p className="branch-notice">{branch.note}</p>:null}<p>{branch.mode==='Why?'?branchConcept.why:branchConcept.detail}</p><div className="branch-example"><small>THINK OF IT THIS WAY</small><p>{branchConcept.example}</p></div><button className="branch-deeper" onClick={()=>openBranch(branchConcept.why,'Why?',branch.id)}>Go one level deeper <ArrowUpRight size={14}/></button><button className="branch-deeper" disabled={insightBusy} onClick={()=>void saveBranchInsight()}>{insightBusy?'Proposing…':'Save insight to study note'}</button><span className="branch-save"><Check size={12}/>Saved on this device</span></div><div className="branch-bottom"><form onSubmit={e=>{e.preventDefault();followBranch()}}><label className="sr-only" htmlFor="branch-question">Ask a follow-up</label><textarea id="branch-question" placeholder="What else are you wondering?" value={branch.draft} rows={2} maxLength={1000} onChange={e=>setState(s=>({...s,branches:s.branches.map(b=>b.id===branch.id?{...b,draft:e.target.value}:b)}))}/><div><small>Sample exploration</small><Button type="submit" size="icon" disabled={!branch.draft.trim()} aria-label="Send follow-up"><ArrowUp size={16}/></Button></div></form><button className="return-button" onClick={()=>branch.parent?setBranchId(branch.parent):closeBranch()}><ArrowLeft size={14}/>{branch.parent?'Back to parent exploration':'Return to your lesson'}</button></div></aside>:null}
  <Sheet open={sources} onOpenChange={setSources}><SheetContent><SheetHeader><SheetTitle>{currentMap.id.startsWith('generated:')?'Trust status':'Reading reference'}</SheetTitle><SheetDescription>{currentMap.id.startsWith('generated:')?'This graph is a structural draft awaiting retrieval and claim review.':'A place to continue learning about this sample map.'}</SheetDescription></SheetHeader><div className="source-content"><BookOpen size={26}/><h3>{currentMap.source.title}</h3><p>{currentMap.id.startsWith('generated:')?'The concepts and relationships came from the local deterministic baseline. They are useful for evaluating the learning flow, but they are not source-verified teaching.':'These are authored sample lessons, not live source-verified AI responses. The reference provides related reading; it is not a claim that each sentence has been independently verified.'}</p>{currentMap.source.url?<a href={currentMap.source.url} target="_blank" rel="noreferrer">Open reference<ExternalLink size={15}/></a>:null}</div></SheetContent></Sheet>
  <Dialog open={dialog!==null} onOpenChange={v=>{if(!v)setDialog(null)}}><DialogContent className={dialog==='setup'?'settings-dialog':undefined}><DialogHeader><DialogTitle>{dialog==='topic'?'Keep that curiosity.':dialog==='setup'?'Set up Open Learn on this device.':'A first look at Open Learn.'}</DialogTitle><DialogDescription>{dialog==='topic'?'The graph service could not complete this request. You can save the idea and explore one of the sample maps.':dialog==='setup'?'Add a provider key to enable model-powered lessons and quizzes. Keys stay in this device encrypted credential store.':'This workspace combines authored sample lessons with a functional draft-graph backend.'}</DialogDescription></DialogHeader>{dialog==='topic'?<div className="dialog-body"><div className="pending-topic"><Sparkles size={18}/>{topic}</div><Button onClick={()=>{setState(s=>({...s,ideas:Array.from(new Set([...s.ideas,topic.trim()]))}));setDialog(null);setNotice('Topic saved to Knowledge maps → Ideas for later.')}}>Save topic for later<Bookmark size={15}/></Button><Button variant="outline" onClick={()=>{setDialog(null);openMap('systems')}}>Explore a sample map<ArrowRight size={15}/></Button></div>:dialog==='setup'?<div className="dialog-body"><LocalDataSettings onDone={()=>{localStorage.setItem('forma-desktop-setup-v1','done');setDialog(null)}}/><Button variant="ghost" onClick={()=>{localStorage.setItem('forma-desktop-setup-v1','done');setDialog(null)}}>Continue with the built-in tutor</Button></div>:<div className="dialog-body"><p>Try the maps, change teaching gear, select a passage, and follow an exploration without losing your place.</p><p>Progress here means <strong>explored</strong>, not mastered. Your saved lessons, branches, and preferences stay in this browser. Live model teaching, source retrieval, and account sync are the next backend layers.</p><Button onClick={()=>setDialog(null)}>Back to learning<ArrowRight size={15}/></Button></div>}</DialogContent></Dialog>
  {notice?<div className="toast-message" role="status"><Check size={16}/>{notice}<button onClick={()=>setNotice('')} aria-label="Dismiss notification"><X size={14}/></button></div>:null}
  <ClassRecorder courseName={courses.find(c=>c.id===activeCourseId)?.name} setupOpen={recordSetupOpen} onSetupOpenChange={setRecordSetupOpen} folder={recordFolder} courseId={activeCourseId} onNoteCreated={noteId=>{setRecordedNoteId(noteId);switchSidebarTab('notes');}} />
  <CourseDialog
    open={courseDialogOpen}
    onOpenChange={setCourseDialogOpen}
    onCreated={(c) => {
      setActiveCourseId(c.id);
      setView('course');
      void refreshCourses();
    }}
  />
 <MobileNavigation onCourses={()=>setView('courses')} view={view} onBuddy={()=>switchSidebarTab('home')} onNotes={()=>{setView('review');setBranchId(null);}} />
 </SidebarProvider>
}
