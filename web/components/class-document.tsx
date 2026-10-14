"use client";
import {useEffect,useRef,useState} from 'react';
import {request} from '@/lib/api';
import {askClassBuddy} from '@/lib/class-buddy';
import {RichContent} from './rich-content';
import {Button} from './ui/button';
import {ClassVisual,type ClassVisual as Visual,type VisualSpec,type VisualAction} from './class-visual';
import {useClassPanelState} from '@/lib/class-panel-state';
import styles from './class-document.module.css';

type Generated={title:string;body:string;segmentIds:string[];sourceManifest?:{startMs:number;endMs?:number;segments:{segmentId:string;revision:number}[]}};
type Block={id:string;revision:number;title:string;body:string;studentEdited:boolean;generated:Generated;suggestion:Generated|null;state:string;topicId?:string;position?:number};
type Page={items:Block[];nextCursor:string|null;totalCount:number};
type Topic={id:string;revision:number;title:string;position:number;blockCount:number};
export function ClassDocument({classId,version,visualsEnabled=false,markers=[],onMarker}:{classId:string;version:number;visualsEnabled?:boolean;markers?:number[];onMarker?:(milliseconds:number,index:number)=>void}){
  const [blocks,setBlocks]=useState<Block[]>([]),[cursor,setCursor]=useState<string|null>(null),[error,setError]=useState('');
  const [editing,setEditing]=useState<string|null>(null),[draft,setDraft]=useState({title:'',body:''}),[saving,setSaving]=useState(false);
  const [visuals,setVisuals]=useState<Visual[]>([]),[visualKind,setVisualKind]=useState<VisualSpec['kind']>('concept_map');
  const [topics,setTopics]=useState<Topic[]>([]),[total,setTotal]=useState(0),[topicEdit,setTopicEdit]=useState<Topic|null>(null),[topicTitle,setTopicTitle]=useState(''),[mergeTarget,setMergeTarget]=useState('');
  const loadedPages=useRef<string[]>(['']);const pageScope=useRef(classId);
  const pendingVisual=useRef(new Map<string,Record<string,unknown>>());
  const [topicCursor,setTopicCursor]=useState<string|null>(null),[visualCursor,setVisualCursor]=useState<string|null>(null);
  const base=`/v1/class-sessions/${encodeURIComponent(classId)}/document`;
  const [outlineOpen,setOutlineOpen]=useClassPanelState(classId,'outline');
  const reader=useRef<HTMLDivElement>(null),following=useRef(true),seenTotal=useRef(0),seenScope=useRef(classId),received=useRef(false);
  const [unread,setUnread]=useState(0),[navigating,setNavigating]=useState(false);
  const latest=blocks.reduce<Block|null>((best,block)=>!best||(block.generated.sourceManifest?.endMs??block.position??0)>(best.generated.sourceManifest?.endMs??best.position??0)?block:best,null);
  function scrollToBlock(id:string,focus=true){const node=document.getElementById(id),pane=reader.current;if(node&&pane){pane.scrollTop+=node.getBoundingClientRect().top-pane.getBoundingClientRect().top;if(focus)node.focus({preventScroll:true});}}
  useEffect(()=>{
    if(seenScope.current!==classId){seenScope.current=classId;seenTotal.current=0;received.current=false;following.current=true;setUnread(0);}
    const added=received.current?Math.max(0,total-seenTotal.current):0;seenTotal.current=total;if(blocks.length||total)received.current=true;
    const selection=window.getSelection();const active=Boolean(document.activeElement?.matches('input,textarea,select,[contenteditable="true"]')&&reader.current?.contains(document.activeElement))||Boolean(selection&&!selection.isCollapsed&&reader.current?.contains(selection.anchorNode));
    if(added&&(!following.current||editing||active||cursor)){following.current=false;setUnread(value=>value+added);}
    else if(following.current&&!editing&&!active&&latest&&!cursor){scrollToBlock(latest.id,false);setUnread(0);}
  },[classId,total,blocks,editing,cursor,latest?.id]);
  async function navigate(topicId?:string){
    if(navigating)return;setNavigating(true);following.current=false;
    try{
      let all=[...blocks],next=cursor;
      while(next&&(!topicId||!all.some(block=>block.topicId===topicId))){
        if(loadedPages.current.length>=20)throw Error('Navigation exceeds 1,000 notes. Export the class to review the full notebook.');
        const start=next;const page=await request<Page>(`${base}?cursor=${encodeURIComponent(start)}`);
        if(pageScope.current!==classId)return;
        if(!loadedPages.current.includes(start))loadedPages.current.push(start);
        all=[...all,...page.items.filter(block=>!all.some(value=>value.id===block.id))];next=page.nextCursor;
      }
      setBlocks(current=>[...current,...all.filter(block=>!current.some(value=>value.id===block.id))]);setCursor(next);
      window.requestAnimationFrame(()=>{
        if(pageScope.current!==classId)return;
        if(topicId)scrollToBlock(topicId);
        else{const newest=all.reduce<Block|null>((best,block)=>!best||(block.generated.sourceManifest?.endMs??block.position??0)>(best.generated.sourceManifest?.endMs??best.position??0)?block:best,null);if(newest)scrollToBlock(newest.id);following.current=true;setUnread(0);}
      });
    }catch(cause){setError(String(cause));}finally{setNavigating(false);}
  }
  useEffect(()=>{let active=true;if(pageScope.current!==classId){pageScope.current=classId;loadedPages.current=[''];}const starts=[...loadedPages.current];void Promise.all(starts.map(start=>request<Page>(`${base}${start?`?cursor=${encodeURIComponent(start)}`:''}`))).then(pages=>{if(active){const refreshed=pages.flatMap(page=>page.items);setBlocks(current=>[...new Map([...current,...refreshed].map(block=>[block.id,block])).values()]);setTotal(pages[0].totalCount);setCursor(pages.at(-1)!.nextCursor);}}).catch(cause=>{if(active)setError(String(cause));});return()=>{active=false;};},[base,version]);
  useEffect(()=>{setEditing(null);setError('');setBlocks([]);setCursor(null);setTopics([]);setTopicEdit(null);setVisuals([]);setTopicCursor(null);setVisualCursor(null);pendingVisual.current.clear();loadedPages.current=[''];},[classId]);
  useEffect(()=>{let active=true;void request<{items:Topic[];nextCursor:string|null}>(base.replace(/\/document$/,'/topics')).then(page=>{if(active){setTopics(current=>[...page.items,...(page.nextCursor?current.filter(topic=>topic.position>=(page.items.at(-1)?.position??0)&&!page.items.some(value=>value.id===topic.id)):[])]);setTopicCursor(page.nextCursor);}}).catch(cause=>{if(active)setError(String(cause));});return()=>{active=false;};},[base,version]);
  useEffect(()=>{let active=true;void request<{items:Visual[];nextCursor:string|null}>(base.replace(/\/document$/,'/visuals')).then(page=>{if(active){setVisuals(current=>[...page.items,...current.filter(visual=>!page.items.some(value=>value.id===visual.id))]);setVisualCursor(page.nextCursor);}}).catch(()=>undefined);return()=>{active=false;};},[base,version]);
  async function moreOutline(){try{const page=await request<{items:Topic[];nextCursor:string|null}>(`${base.replace(/\/document$/,'/topics')}?cursor=${encodeURIComponent(topicCursor||'')}`);setTopics(current=>[...current,...page.items.filter(topic=>!current.some(value=>value.id===topic.id))]);setTopicCursor(page.nextCursor);}catch(cause){setError(String(cause));}}
  async function moreVisuals(){try{const page=await request<{items:Visual[];nextCursor:string|null}>(`${base.replace(/\/document$/,'/visuals')}?cursor=${encodeURIComponent(visualCursor||'')}`);setVisuals(current=>[...current,...page.items.filter(visual=>!current.some(value=>value.id===visual.id))]);setVisualCursor(page.nextCursor);}catch(cause){setError(String(cause));}}
  async function createVisual(block:Block){try{const visual=await request<Visual>(base.replace(/\/document$/,'/visuals'),{method:'POST',body:JSON.stringify({commandId:crypto.randomUUID(),blockId:block.id,expectedRevision:block.revision,kind:visualKind})});setVisuals(current=>[visual,...current]);}catch(cause){setError(String(cause));}}
  async function visualChange(visual:Visual,action:VisualAction,spec?:VisualSpec){
    const body=pendingVisual.current.get(visual.id)||{commandId:crypto.randomUUID(),expectedRevision:visual.revision,action,spec};
    if(body.action!==action)throw Error('Retry the pending visual action before starting another change.');
    pendingVisual.current.set(visual.id,body);
    const saved=await request<Visual>(`${base.replace(/\/document$/,'/visuals')}/${encodeURIComponent(visual.id)}`,{method:'PATCH',body:JSON.stringify(body)});
    pendingVisual.current.delete(visual.id);setVisuals(current=>current.map(value=>value.id===visual.id?saved:value));
  }
  async function changeTopic(topic:Topic,action:'rename'|'merge'|'move',position?:number){try{const target=topics.find(value=>value.id===mergeTarget);const page=await request<{items:Topic[]}>(`${base.replace(/\/document$/,'/topics')}/${encodeURIComponent(topic.id)}`,{method:'PATCH',body:JSON.stringify({expectedRevision:topic.revision,action,title:topicTitle,targetTopicId:target?.id,targetRevision:target?.revision,position})});setTopics(page.items);setTopicEdit(null);const pageBlocks=await request<Page>(base);setBlocks(current=>[...pageBlocks.items,...current.filter(block=>!pageBlocks.items.some(value=>value.id===block.id))]);setCursor(current=>loadedPages.current.length===1?pageBlocks.nextCursor:current);}catch(cause){setError(String(cause));}}
  async function moveBlock(block:Block,topicId:string,position=block.position||0){try{const saved=await request<Block>(`${base}/${encodeURIComponent(block.id)}`,{method:'PATCH',body:JSON.stringify({expectedRevision:block.revision,action:'move',topicId,position})});setBlocks(current=>current.map(value=>value.id===block.id?saved:value));}catch(cause){setError(String(cause));}}
  async function update(block:Block,action:'edit'|'accept_suggestion'|'dismiss_suggestion'){
    setSaving(true);setError('');
    try{const saved=await request<Block>(`${base}/${encodeURIComponent(block.id)}`,{method:'PATCH',body:JSON.stringify({expectedRevision:block.revision,action,...draft})});setBlocks(current=>current.map(value=>value.id===block.id?saved:value));setEditing(null);}catch(cause){setError(String(cause));}finally{setSaving(false);}
  }
  async function more(){try{if(!cursor)return;if(loadedPages.current.length>=20)throw Error('For more than 1,000 notes, export the class or open the saved class note.');const page=await request<Page>(`${base}?cursor=${encodeURIComponent(cursor)}`);if(!loadedPages.current.includes(cursor))loadedPages.current.push(cursor);setBlocks(current=>[...current,...page.items.filter(value=>!current.some(old=>old.id===value.id))]);setCursor(page.nextCursor);}catch(cause){setError(String(cause));}}
  async function exportNotes(){
    try{const all:Block[]=[];let next:string|null=null;do{const page:Page=await request<Page>(`${base}${next?`?cursor=${encodeURIComponent(next)}`:''}`);all.push(...page.items);next=page.nextCursor;if(all.length>=1000&&next)throw new Error('Export exceeds 1,000 note blocks. Export a smaller class.');}while(next);
      const exportVisuals:{items:Visual[]}={items:[]};let visualNext:string|null=null;do{const page:{items:Visual[];nextCursor:string|null}=await request(`${base.replace(/\/document$/,'/visuals')}${visualNext?`?cursor=${encodeURIComponent(visualNext)}`:''}`);exportVisuals.items.push(...page.items);visualNext=page.nextCursor;if(exportVisuals.items.length>=500&&visualNext)throw Error('Export exceeds 500 visuals. Export individual figures instead.');}while(visualNext);
      const markdown=all.map(block=>{
        const figures=exportVisuals.items.filter(visual=>visual.request.blockId===block.id&&visual.state!=='removed').map(visual=>{
          if(!visual.spec)return `Visual ${visual.state}; retained text notes above.`;
          const data=JSON.stringify(visual.spec,null,2),fence='~'.repeat(Math.max(4,...(data.match(/~+/g)||[]).map(value=>value.length+1)));
          return `### ${visual.spec.title}\n\n${visual.state!=='ready'?`Previous visual · ${visual.state}; review against current lecture evidence.\n\n`:''}${visual.spec.description}\n\nVisual fallback: validated declarative data (rendered diagrams remain available in Open Learn).\n\n${fence}json\n${data}\n${fence}`;
        }).join('\n\n');
        return `## ${block.title}\n\n${block.body}\n\n${block.studentEdited?'Student edited. ':''}Lecture sources: ${block.generated.segmentIds.join(', ')}${block.suggestion?'\n\nA regenerated suggestion is awaiting your review.':''}${figures?'\n\n'+figures:''}`;
      }).join('\n\n');
      const url=URL.createObjectURL(new Blob([markdown],{type:'text/markdown;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download='class-notes.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(cause){setError(String(cause));}
  }
  return <section aria-label="Editable class notes"><header><h3>Class notebook</h3><Button size="sm" variant="outline" onClick={()=>void exportNotes()}>Export Markdown</Button></header>
    {error?<p role="alert">{error}</p>:null}
    <label>Visual style <select value={visualKind} onChange={event=>setVisualKind(event.target.value as VisualSpec['kind'])}>{(['concept_map','flowchart','table','equation_steps','plot','illustration'] as const).map(kind=><option key={kind} value={kind}>{kind.replaceAll('_',' ')}</option>)}</select></label>
    <div className={styles.controls}><Button size="sm" variant="outline" aria-expanded={outlineOpen} aria-controls="class-note-outline" onClick={()=>setOutlineOpen(!outlineOpen)}>{outlineOpen?'Hide':'Show'} topics and bookmarks</Button></div>
    <div className={styles.layout} data-outline={outlineOpen}>
    <aside id="class-note-outline" className={styles.outline} hidden={!outlineOpen} aria-label="Topics and bookmarks"><strong>Topics</strong><nav aria-label="Note outline">{topics.map(topic=><button key={topic.id} type="button" disabled={navigating} onClick={()=>void navigate(topic.id)}>{topic.title} ({topic.blockCount})</button>)}</nav>{topicCursor?<Button size="sm" variant="outline" onClick={()=>void moreOutline()}>Load more outline topics</Button>:null}<strong>Bookmarks</strong><nav aria-label="Recording bookmarks">{markers.map((value,index)=><button key={`${index}:${value}`} type="button" onClick={()=>{following.current=false;onMarker?.(value,index);}}>Marker {index+1} · {Math.floor(value/60000)}:{String(Math.floor(value/1000)%60).padStart(2,'0')}</button>)}</nav>{!markers.length?<small>Use Mark this moment while recording to add a bookmark.</small>:null}</aside>
    <div className={styles.reader}>
    <div className={styles.live}><span role="status">{unread?`${unread} new ${unread===1?'note':'notes'} below`:'Live class notebook'}</span><Button size="sm" variant="outline" disabled={navigating||Boolean(editing)} onClick={()=>void navigate()}>{navigating?'Opening latest notes…':'Return to live'}</Button></div>
    {editing?<small>Save or cancel your edit to return to live.</small>:null}
    <div ref={reader} className={styles.pages} tabIndex={0} aria-label="Scrollable class notebook" onScroll={()=>{const pane=reader.current;if(pane){const bounds=pane.getBoundingClientRect(),tail=latest?document.getElementById(latest.id)?.getBoundingClientRect():null;const atLatest=Boolean(bounds.height&&tail&&tail.top>=bounds.top-48&&tail.top<bounds.bottom);following.current=!cursor&&(atLatest||pane.scrollHeight-pane.clientHeight-pane.scrollTop<48);if(following.current)setUnread(0);}}} onFocusCapture={()=>{following.current=false;}} onPointerDown={()=>{following.current=false;}}>
    {!blocks.length?<p>Notes appear here when verified lecture passages are ready.</p>:null}
    {total>blocks.length?<p role="status">{total-blocks.length} more note blocks available. Your reading position stays here.</p>:null}
    {visualCursor?<Button size="sm" variant="outline" onClick={()=>void moreVisuals()}>Load earlier visuals</Button>:null}
    {topicEdit?<form onSubmit={event=>{event.preventDefault();void changeTopic(topicEdit,'rename');}}><label>Topic heading<input value={topicTitle} maxLength={300} onChange={event=>setTopicTitle(event.target.value)}/></label><Button type="submit">Rename topic</Button><label>Merge into<select value={mergeTarget} onChange={event=>setMergeTarget(event.target.value)}><option value="">Choose topic</option>{topics.filter(topic=>topic.id!==topicEdit.id).map(topic=><option key={topic.id} value={topic.id}>{topic.title}</option>)}</select></label><Button type="button" disabled={!mergeTarget} onClick={()=>void changeTopic(topicEdit,'merge')}>Merge sections</Button><Button type="button" variant="ghost" onClick={()=>setTopicEdit(null)}>Cancel</Button></form>:null}
    {[...topics.filter(topic=>blocks.some(block=>block.topicId===topic.id)),...(blocks.some(block=>!topics.some(topic=>topic.id===block.topicId))?[{id:'ungrouped',title:'Lecture notes',revision:1,position:0,blockCount:0}]:[])].map((topic,topicIndex)=><section id={topic.id} tabIndex={-1} key={topic.id} aria-label={topic.title}><header><h3>{topic.title}</h3>{topic.id!=='ungrouped'?<><Button size="sm" variant="ghost" onClick={()=>{setTopicEdit(topic);setTopicTitle(topic.title);setMergeTarget('');}}>Organize topic</Button><Button size="sm" variant="ghost" disabled={!topicIndex} onClick={()=>void changeTopic(topic,'move',(topics[topicIndex-1]?.position??topic.position)-1)}>Move topic up</Button></>:null}</header>
    {blocks.filter(block=>topic.id==='ungrouped'?!topics.some(value=>value.id===block.topicId):block.topicId===topic.id).sort((a,b)=>(a.position||0)-(b.position||0)||a.id.localeCompare(b.id)).map(block=><article id={block.id} tabIndex={-1} key={block.id}>
      {editing===block.id?<form onSubmit={event=>{event.preventDefault();void update(block,'edit');}}><label>Heading<input value={draft.title} maxLength={300} onChange={event=>setDraft(current=>({...current,title:event.target.value}))}/></label><label>Your notes<textarea value={draft.body} maxLength={20000} rows={8} onChange={event=>setDraft(current=>({...current,body:event.target.value}))}/></label><Button disabled={saving} type="submit">Save</Button><Button type="button" variant="ghost" onClick={()=>setEditing(null)}>Cancel</Button></form>:<><h4>{block.title}</h4><RichContent body={block.body}/><Button size="sm" variant="ghost" onClick={()=>{setEditing(block.id);setDraft({title:block.title,body:block.body});}}>Edit notes</Button><Button size="sm" variant="ghost" onClick={()=>askClassBuddy({classId,anchorMs:block.generated.sourceManifest?.endMs??block.generated.sourceManifest?.startMs??0,segmentRefs:block.generated.sourceManifest?.segments.slice(0,12),noteRefs:[{blockId:block.id,revision:block.revision}],review:true},`Explain this note: ${block.title}`)}>Ask Buddy</Button></>}
      {block.studentEdited?<small>Your edits are protected from automatic updates.</small>:null}
      {block.state==='stale'?<p role="status">Transcript support changed. These notes need review; your wording is preserved.</p>:null}
      {visualsEnabled?<Button size="sm" variant="outline" onClick={()=>void createVisual(block)}>Create visual from lecture</Button>:null}
      {visuals.filter(visual=>visual.request.blockId===block.id).map(visual=><ClassVisual key={visual.id} visual={visual} classId={classId} onChange={(action,spec)=>visualChange(visual,action,spec)}/>)}
      <label>Move note to topic <select value={block.topicId||''} onChange={event=>void moveBlock(block,event.target.value)}><option value="" disabled>Choose topic</option>{topics.map(value=><option key={value.id} value={value.id}>{value.title}</option>)}</select></label><Button size="sm" variant="ghost" onClick={()=>void moveBlock(block,block.topicId||'',Math.min(...blocks.filter(value=>value.topicId===block.topicId).map(value=>value.position||0))-1)}>Move note to top</Button>
      {block.suggestion?<details><summary>Updated lecture notes available</summary><h4>{block.suggestion.title}</h4><RichContent body={block.suggestion.body}/><Button disabled={saving} size="sm" onClick={()=>void update(block,'accept_suggestion')}>Replace with update</Button><Button disabled={saving} size="sm" variant="ghost" onClick={()=>void update(block,'dismiss_suggestion')}>Keep my notes</Button></details>:null}
    </article>)}</section>)}{cursor&&total>blocks.length?<Button variant="outline" onClick={()=>void more()}>Load more notes</Button>:null}
    </div></div></div>
  </section>;
}
