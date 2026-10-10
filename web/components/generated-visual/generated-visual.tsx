"use client";
import { useMemo, useState, useRef, useEffect } from 'react';
import {request} from '@/lib/api';
import { reportVoiceFocus } from '@/lib/voice/client';
import type { GeneratedVisual } from '@/lib/generated-visual';
import { VISUAL_PROMPT_DRAFT } from '@/lib/generated-visual';
import { SandboxFunctions, type SandboxFunction } from './sandbox-context';
import { OpenGenUIActivityRenderer } from './upstream/renderer';
import styles from './generated-visual.module.css';
import {compatibleContent} from './library-compat';

export function GeneratedVisualCard({ visual, lessonId }: { visual:GeneratedVisual;lessonId?:string }) {
  const [question,setQuestion]=useState('');
  const [link,setLink]=useState('');
  const [notice,setNotice]=useState('');
  const [exporting,setExporting]=useState(false);
  const [renderAttempt,setRenderAttempt]=useState(0);
  const [theme,setTheme]=useState('');
  useEffect(()=>{
    const update=()=>setTheme(document.documentElement.matches('.dark,[data-theme="dark"]')?'dark':'light');
    update();const observer=new MutationObserver(update);observer.observe(document.documentElement,{attributes:true,attributeFilter:['class','data-theme']});
    return()=>observer.disconnect();
  },[]);
  const revision=useRef(visual.revision);
  const values=useRef(visual.controlValues);
  const queue=useRef<Promise<unknown>>(Promise.resolve());
  useEffect(()=>{revision.current=visual.revision;values.current=visual.controlValues;},[visual.revision,visual.controlValues]);
  const exportSnapshot=async(copy:boolean)=>{
    setExporting(true);setNotice('');
    try{
      await queue.current;
      const {exportVisualHtml}=await import('./export');const html=await exportVisualHtml({...visual,revision:revision.current,controlValues:values.current});
      if(copy){await navigator.clipboard.writeText(html);setNotice('HTML copied.');}
      else{const url=URL.createObjectURL(new Blob([html],{type:'text/html'}));const anchor=document.createElement('a');anchor.href=url;anchor.download=visual.title.replace(/[^A-Za-z0-9_-]+/g,'-').slice(0,80)+'.html';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
    }catch{setNotice('Export could not finish. Please try again.');}finally{setExporting(false);}
  };
  const bridge=useMemo<SandboxFunction[]>(()=>[
    {name:'visualError',handler:async()=>{setNotice('The visual could not initialize. Retry the saved visual or ask for a new version.');return {ok:true};}},
    {name:'focusVisual',handler:async()=>{if(lessonId)reportVoiceFocus({lesson_id:lessonId,visualization_id:visual.id,expected_revision:revision.current});return {ok:true};}},
    {name:'getState',handler:async()=>({revision:revision.current,controls:Object.fromEntries(visual.controls.map(control=>[control.id,values.current[control.id]??control.initial]))})},
    {name:'saveControl',handler:async(args)=>{
      const input=args as {id?:unknown;value?:unknown};
      const control=visual.controls.find(control=>control.id===input?.id);
      if(!lessonId||!control||typeof input.value!=='number'||!Number.isFinite(input.value)||input.value<control.minimum||input.value>control.maximum)throw new Error('Invalid visual control.');
      const value=input.value;
      const task=queue.current.catch(()=>{}).then(async()=>{
        const changed=await request<GeneratedVisual>(`/v1/lessons/${encodeURIComponent(lessonId)}/visualizations/${encodeURIComponent(visual.id)}`,{method:'PATCH',body:JSON.stringify({operation:'change_parameter',expectedRevision:revision.current,parameterId:control.id,value})});
        revision.current=changed.revision;values.current=changed.controlValues;reportVoiceFocus({lesson_id:lessonId,visualization_id:visual.id,expected_revision:changed.revision});return {ok:true,revision:changed.revision};
      });queue.current=task;
      try{return await task;}catch(error){setNotice('Your change works locally but could not be saved. Reload before voice editing.');throw error;}
    }},
    {name:'sendPrompt',handler:async(args)=>{
      const text=args && typeof args==='object' && 'text' in args?args.text:null;
      if(typeof text!=='string'||!text.trim()||text.length>4000)throw new Error('Enter a shorter question.');
      setQuestion(text.trim());return {ok:false,reviewRequired:true};
    }},
    {name:'openLink',handler:async(args)=>{
      const value=args && typeof args==='object' && 'url' in args?args.url:null;
      if(typeof value!=='string'||value.length>2000)throw new Error('Link unavailable.');
      const url=new URL(value);
      if(url.protocol!=='https:'||url.username||url.password)throw new Error('Link unavailable.');
      setLink(url.href);return {ok:false,reviewRequired:true};
    }},
  ],[visual.controls,visual.id,lessonId]);
  const content=useMemo(()=>{
    if(visual.renderer!=='open_generative_ui')return {};
    const prepared=compatibleContent(visual.content);
    if(!Object.keys(visual.controlValues).length)return prepared;
    // Only validated numeric input IDs and values cross this bridge. No model
    // function name, source code, or arbitrary DOM selector is invoked.
    const state=JSON.stringify(visual.controlValues);
    const apply=`(()=>{for(const [id,value] of Object.entries(${state})){const input=document.getElementById(id);if(input instanceof HTMLInputElement&&['range','number'].includes(input.type)){input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));}}})()`;
    return {...prepared,jsExpressions:[...(prepared.jsExpressions||[]),apply]};
  },[visual]);
  const table=visual.renderer==='a2ui'?visual.content:null;
  const focus=()=>{if(lessonId)reportVoiceFocus({lesson_id:lessonId,visualization_id:visual.id,expected_revision:revision.current});};
  return <figure className={styles.card} onPointerDown={focus} onFocus={focus} aria-label={visual.title} data-visualization-type="generated_ui">
    <figcaption className={styles.caption}>{visual.title}<span className={styles.actions}><button type="button" disabled={exporting} onClick={()=>void exportSnapshot(false)}>Download</button><button type="button" disabled={exporting} onClick={()=>void exportSnapshot(true)}>Copy HTML</button></span></figcaption>
    {table?<div className={styles.tableScroll} role="region" tabIndex={0} aria-label={table.title}>
      <table><caption>{table.title}</caption><thead><tr>{table.columns.map((column,index)=><th key={index} scope="col">{column}</th>)}</tr></thead>
      <tbody>{table.rows.map((row,index)=><tr key={index}>{row.map((cell,column)=><td key={column}>{cell}</td>)}</tr>)}</tbody></table>
      <p>{table.source}</p>
    </div>:visual.renderer==='open_generative_ui'?<SandboxFunctions.Provider value={bridge}><OpenGenUIActivityRenderer key={`${visual.id}:${visual.revision}:${renderAttempt}:${theme}`} activityType="open-generative-ui" content={content} message={null} agent={null}/></SandboxFunctions.Provider>:null}
    {question?<div className={styles.followup}><label>Suggested question<textarea value={question} onChange={event=>setQuestion(event.target.value)} maxLength={4000}/></label>
      <button type="button" onClick={event=>{event.currentTarget.dispatchEvent(new CustomEvent(VISUAL_PROMPT_DRAFT,{bubbles:true,detail:{text:question,lessonId,visualizationId:visual.id}}));setQuestion('');}}>Use this question</button>
      <button type="button" onClick={()=>setQuestion('')}>Dismiss</button></div>:null}
    {link?<div className={styles.followup}><a href={link} target="_blank" rel="noopener noreferrer">Open suggested link</a><button type="button" onClick={()=>setLink('')}>Dismiss</button></div>:null}
    {notice?<p role="status">{notice}</p>:null}
    {notice.startsWith('The visual could not initialize')?<button type="button" onClick={()=>{setNotice('');setRenderAttempt(value=>value+1);}}>Retry saved visual</button>:null}
  </figure>;
}
