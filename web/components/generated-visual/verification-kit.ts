// Runtime verification entry point. Built into web/.visual-verification by
// scripts/build-visual-assets.mjs and loaded only by the backend's headless
// verifier (backend/app/visual_verification.py), never by the product UI.
//
// It mounts a candidate exactly as the chat card does: the same Websandbox
// library, final frame document, compatibility program and script order as
// upstream/renderer.tsx (measurement, jsFunctions, then each expression).
import type {OpenGenUIContent} from './upstream/schema';
import {buildFinalFrameContent, MEASUREMENT_JS, RESIZE_MESSAGE_TYPE} from './upstream/frame-content';
import {clampReportedHeight} from './upstream/renderer-sizing';
import {loadWebsandbox} from './upstream/websandbox-loader';
import {visualProgram} from './program';

export type VerificationControl={id:string;initial:number};
export type VerificationEvent={type:string;detail?:unknown;at:number};
export type VerificationInput={content:OpenGenUIContent;controls:VerificationControl[];controlValues:Record<string,number>};

const MAX_EVENTS=200;

export async function mountVisual(container:HTMLElement,input:VerificationInput){
  const events:VerificationEvent[]=[];
  const started=performance.now();
  const record=(type:string,detail?:unknown)=>{if(events.length<MAX_EVENTS)events.push({type,detail,at:Math.round(performance.now()-started)});};
  const program=visualProgram(input.content,input.controlValues);
  const state={revision:1,controls:Object.fromEntries(input.controls.map(control=>[control.id,input.controlValues[control.id]??control.initial]))};
  const api:Record<string,(args:unknown)=>unknown>={
    visualError:async(args)=>{record('error',args);return {ok:true};},
    focusVisual:async()=>({ok:true}),
    getState:async()=>state,
    saveControl:async(args)=>{record('saveControl',args);return {ok:true,revision:1};},
    sendPrompt:async(args)=>{record('sendPrompt',args);return {ok:false,reviewRequired:true};},
    openLink:async(args)=>{record('openLink',args);return {ok:false,reviewRequired:true};},
  };
  container.style.position='relative';container.style.width='100%';container.style.overflow='hidden';
  container.style.height=`${program.initialHeight??200}px`;
  const Websandbox=await loadWebsandbox();
  const sandbox=Websandbox.create(api,{frameContainer:container,frameContent:buildFinalFrameContent((program.html||[]).join(''),program.css),allowAdditionalAttributes:''});
  Object.assign(sandbox.iframe.style,{width:'100%',height:'100%',border:'none',backgroundColor:'transparent'});
  sandbox.iframe.setAttribute('data-openlearn-visual','candidate');
  window.addEventListener('message',event=>{
    if(event.source!==sandbox.iframe.contentWindow||event.data?.type!==RESIZE_MESSAGE_TYPE)return;
    const height=clampReportedHeight(event.data.height);
    if(height!==null){container.style.height=`${height}px`;record('resize',{height,reported:event.data.height});}
  });
  await sandbox.promise;
  record('frameReady');
  void sandbox.run(MEASUREMENT_JS);
  for(const [index,code] of [program.jsFunctions||'',...(program.jsExpressions||[])].entries()){
    if(!code)continue;
    try{await sandbox.run(code);}catch(error){record('runError',{index,message:String(error).slice(0,300)});}
  }
  record('scriptsComplete');
  return {events,destroy:()=>sandbox.destroy()};
}

declare global{interface Window{__openlearnVerification?:{mountVisual:typeof mountVisual}}}
window.__openlearnVerification={mountVisual};
