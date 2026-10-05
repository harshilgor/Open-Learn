import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {FlashcardWorkspace} from '@/components/flashcard-workspace';
import {flashcardsApi,type Deck,type FlashcardReview} from '@/lib/flashcards-client';
import {rememberCommand,pendingCommands} from '@/lib/offline-commands';
vi.mock('@/lib/flashcards-client',()=>({flashcardsApi:{list:vi.fn(),summary:vi.fn(),deck:vi.fn(),session:vi.fn(),rate:vi.fn(),command:vi.fn(),review:vi.fn(),preferences:vi.fn()}}));
vi.mock('@/components/flashcard-create',()=>({MakeFlashcards:()=>null}));
vi.mock('@/components/flashcard-image',()=>({FlashcardImage:()=>null,NewFlashcard:()=>null}));
vi.mock('@/components/rich-content',()=>({RichContent:({body}:{body:string})=><p>{body}</p>}));
vi.mock('@/components/ui/button',()=>({Button:({children,variant,size,...props}:React.ButtonHTMLAttributes<HTMLButtonElement>&{variant?:string;size?:string})=><button {...props}>{children}</button>}));
const deck:Deck={id:'deck-one',revision:2,title:'Cell recall',status:'draft',cards:[{id:'card-one',versionId:'v-one',publishedVersionId:null,state:'active',stale:false,content:{type:'qa',prompt:'What encloses a cell?',answer:'Membrane',explanation:'Boundary',sourceIds:['note-one'],supportQuote:'A cell has a membrane.'}}],cardCount:1,nextOffset:null,coverage:{partial:true,sources:[{id:'note-one',title:'Cells',ref:{kind:'note',id:'note-one',revision:1},hash:'hash'}]},candidates:[]};
const session:FlashcardReview={id:'fcr-one',revision:1,status:'active',cursor:0,total:1,practice:false,current:{cardId:'card-one',deckId:'deck-one',versionId:'v-one',attemptId:'attempt-one',type:'qa',prompt:'What encloses a cell?',revealed:false}};
let root:Root,container:HTMLDivElement;
beforeEach(()=>{(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;vi.useFakeTimers();localStorage.clear();window.history.replaceState({},'','/');vi.mocked(flashcardsApi.list).mockResolvedValue({decks:[deck],nextOffset:null});vi.mocked(flashcardsApi.summary).mockResolvedValue({dueCount:0,courses:{},sessions:[]});vi.mocked(flashcardsApi.deck).mockResolvedValue(deck);vi.mocked(flashcardsApi.session).mockResolvedValue(session);container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();vi.clearAllMocks();vi.useRealTimers();});
const button=(text:string)=>[...container.querySelectorAll('button')].find(b=>b.textContent?.includes(text))!;
it('requires explicit publication of persistent drafts',async()=>{
 await act(async()=>root.render(<FlashcardWorkspace launch={{deckId:'deck-one',view:'editor'}}/>));
 expect(container.textContent).toContain('Cell recall');expect(container.textContent).toContain('Partial source coverage');expect(flashcardsApi.command).not.toHaveBeenCalled();
 vi.mocked(flashcardsApi.command).mockResolvedValue({revision:3});await act(async()=>button('Publish selected').click());
 expect(flashcardsApi.command).toHaveBeenCalledWith(expect.objectContaining({id:'deck-one',revision:2}),expect.objectContaining({action:'publish',cardIds:['card-one']}));
});
it('reveals before rating and never rates on panel close',async()=>{
 await act(async()=>root.render(<FlashcardWorkspace launch={{reviewSessionId:'fcr-one',view:'review'}}/>));
 expect(container.textContent).not.toContain('Membrane');expect(button('Good')).toBeUndefined();
 vi.mocked(flashcardsApi.rate).mockResolvedValue({...session,revision:2,current:{...session.current!,revealed:true,answer:'Membrane'}});
 await act(async()=>button('Show answer').click());expect(container.textContent).toContain('Membrane');expect(flashcardsApi.rate).toHaveBeenCalledTimes(1);
 await act(async()=>button('Return to decks').click());expect(flashcardsApi.rate).toHaveBeenCalledTimes(1);
});
it('preserves the exact command on transport retry',async()=>{
 await act(async()=>root.render(<FlashcardWorkspace launch={{reviewSessionId:'fcr-one',view:'review'}}/>));
 vi.mocked(flashcardsApi.rate).mockRejectedValueOnce(new Error('Disconnected'));await act(async()=>button('Show answer').click());const original=vi.mocked(flashcardsApi.rate).mock.calls[0][1];
 vi.mocked(flashcardsApi.rate).mockResolvedValue({...session,revision:2,current:{...session.current!,revealed:true,answer:'Membrane'}});
 await act(async()=>button('Retry saved command').click());expect(vi.mocked(flashcardsApi.rate).mock.calls[1][1]).toEqual(original);
});
it('keyboard shortcuts leave response editing alone',async()=>{
 await act(async()=>root.render(<FlashcardWorkspace launch={{reviewSessionId:'fcr-one',view:'review'}}/>));
 await act(async()=>container.querySelector('textarea')!.dispatchEvent(new KeyboardEvent('keydown',{code:'Space',bubbles:true})));expect(flashcardsApi.rate).not.toHaveBeenCalled();
});
it('queues owner-scoped edits and pinned ratings',()=>{
 const body=JSON.stringify({commandId:'rate-one',expectedRevision:3,attemptId:'attempt-one',action:'rate',rating:'good'});
 rememberCommand('alice','http://localhost/v1/flashcard-review-sessions/fcr-one/commands',{method:'POST',body});rememberCommand('alice','http://localhost/v1/flashcard-review-sessions/fcr-one/commands',{method:'POST',body});
 expect(pendingCommands('alice')).toHaveLength(1);expect(pendingCommands('bob')).toHaveLength(0);expect(JSON.parse(pendingCommands('alice')[0].body).attemptId).toBe('attempt-one');
});
