"use client";
import {useEffect,useState} from 'react';
import {request} from '@/lib/api';
import {Visualization} from '../visualization';
import {parseVisualArtifact} from '@/lib/generated-visual';

type Run={id:string;phase:string;errorCode?:string;plan?:{approach:string;technology:string;keyElements:string[]};snapshots:unknown[];artifactRefs:unknown[]};
const errors:Record<string,string>={visual_setup_required:'Visual generation needs provider configuration.',visual_missing_artifact:'The model did not produce a visual.',visual_invalid_javascript:'The model produced invalid visual code.',visual_missing_dom_target:'The model could not finish the visual controls.',visual_validation_attempt_limit:'The model could not finish a valid visual.',visual_usage_window_exhausted:'Your visual allowance is used up. Retry after it resets.',visual_usage_input_limit:'The visual request is too large. Try a more focused request.',visual_usage_platform_budget_exhausted:'Visual generation has reached its spending limit. Try again later.'};
const terminal=new Set(['completed','skipped','failed','interrupted','cancelled','superseded']);
export function LessonVisualRuns({lessonId,existingIds}:{lessonId:string;existingIds:string[]}) {
  const [runs,setRuns]=useState<Run[]>([]);
  const [error,setError]=useState('');
  const [refresh,setRefresh]=useState(0);
  useEffect(()=>{
    let live=true;let timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try{
        const value=await request<{runs:Run[]}>(`/v1/lessons/${encodeURIComponent(lessonId)}/visual-runs`,{cache:'no-store'});
        if(!live)return;
        setRuns(value.runs);setError('');
        if(value.runs.some(run=>!terminal.has(run.phase)))timer=setTimeout(()=>void poll(),2000);
      }catch{if(live)setError('Visual status is unavailable. Reload to reconnect.');}
    }
    void poll();return()=>{live=false;clearTimeout(timer);};
  },[lessonId,refresh]);
  const action=async(run:Run,kind:'retry'|'cancel')=>{
    try{await request(`/v1/visual-runs/${encodeURIComponent(run.id)}/${kind}`,{method:'POST',headers:kind==='retry'?{'Idempotency-Key':crypto.randomUUID()}:undefined});setRefresh(value=>value+1);}
    catch{setError('The visual action could not finish. Please try again.');}
  };
  return <div aria-label="Lesson visuals">
    {runs.map((run,index)=><div key={run.id}>
      {index===runs.length-1&&run.plan&&run.phase!=='superseded'?<details><summary>Visual design plan</summary><p>{run.plan.approach}</p><p>{run.plan.technology}</p><ul>{run.plan.keyElements.map((item,index)=><li key={index}>{item}</li>)}</ul></details>:null}
      {run.phase==='queued'||run.phase==='running'||run.phase==='generated'?<p role="status">Preparing an interactive visual… <button type="button" onClick={()=>void action(run,'cancel')}>Stop visual</button></p>:null}
      {index===runs.length-1&&(run.phase==='failed'||run.phase==='interrupted')?<p role="status">{errors[run.errorCode||'']||'The visual was interrupted.'} Your explanation is saved. <button type="button" onClick={()=>void action(run,'retry')}>Retry visual</button></p>:null}
      {(run.phase==='completed'?run.artifactRefs:terminal.has(run.phase)?[]:run.snapshots).filter(value=>{const spec=parseVisualArtifact(value);return spec&&!existingIds.includes(spec.id);}).map(value=>{const spec=parseVisualArtifact(value)!;return <Visualization key={spec.id} value={value} lessonId={lessonId}/>;})}
    </div>)}
    {error?<p role="status">{error}</p>:null}
  </div>;
}
