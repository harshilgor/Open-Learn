import type {GeneratedVisual} from '@/lib/generated-visual';
import {THEME_CSS,SVG_CLASSES_CSS,FORM_STYLES_CSS,IMPORTMAP} from './upstream/design-system';
import {LEAFLET_CSS} from './upstream/leaflet-css';
import {TRIP_ANIMATOR_SCRIPT} from './upstream/trip-animator';
import {compatibleContent} from './library-compat';
import {hostVisualTheme} from './theme';

const escapeHtml=(value:string)=>value.replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]!));
const script=(value:string)=>value.replace(/<\/script/gi,'<\\/script');
const css=(value:string)=>value.replace(/<\/style/gi,'<\\/style');
const assetCache=new Map<string,Promise<string>>();
function dataModule(text:string){
  const bytes=new TextEncoder().encode(text);let binary='';
  for(let index=0;index<bytes.length;index+=32768)binary+=String.fromCharCode(...bytes.subarray(index,index+32768));
  return 'data:text/javascript;base64,'+btoa(binary);
}
async function localModule(name:string):Promise<string>{
  let value=assetCache.get(name);
  if(!value){
    value=(async()=>{
      const url=new URL(IMPORTMAP.imports[name as keyof typeof IMPORTMAP.imports]);
      if(url.origin!==window.location.origin||!url.pathname.startsWith('/visual-assets/'))throw new Error('Export library unavailable.');
      const response=await fetch(url);if(!response.ok)throw new Error('Export library unavailable.');
      let source=await response.text();if(source.length>6000000)throw new Error('Export library too large.');
      if(name==='three/addons/controls/OrbitControls.js')source=source.replaceAll('"./three.js"',JSON.stringify(await localModule('three')));
      return dataModule(source);
    })();assetCache.set(name,value);value.catch(()=>assetCache.delete(name));
  }return value;
}

/** Portable, isolated snapshot. Reviewed libraries are embedded; no provider keys or host access. */
export async function exportVisualHtml(visual:GeneratedVisual):Promise<string>{
  let body:string,styles='',functions='',expressions:string[]=[];
  const imports:Record<string,string>={};
  if(visual.renderer==='a2ui'){
    const table=visual.content;
    body=`<table><caption>${escapeHtml(table.title)}</caption><thead><tr>${table.columns.map(value=>`<th>${escapeHtml(value)}</th>`).join('')}</tr></thead><tbody>${table.rows.map(row=>`<tr>${row.map(value=>`<td>${escapeHtml(value)}</td>`).join('')}</tr>`).join('')}</tbody></table><p>${escapeHtml(table.source)}</p>`;
  }else{
    const content=compatibleContent(visual.content);
    body=(content.html||[]).join('');styles=content.css||'';functions=content.jsFunctions||'';expressions=[...(content.jsExpressions||[])];
    const code=body+functions+expressions.join('\n');
    for(const name of Object.keys(IMPORTMAP.imports))if(code.includes(`'${name}'`)||code.includes(`"${name}"`))imports[name]=await localModule(name);
    expressions.push(`for(const [id,value] of Object.entries(${JSON.stringify(visual.controlValues)})){const input=document.getElementById(id);if(input instanceof HTMLInputElement&&['number','range'].includes(input.type)){input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));}}`);
  }
  const state=JSON.stringify({revision:visual.revision,controls:Object.fromEntries(visual.controls.map(control=>[control.id,visual.controlValues[control.id]??control.initial]))});
  const bridge=`window.Websandbox={connection:{remote:{getState:async()=>(${state}),focusVisual:async()=>({ok:true}),saveControl:async()=>({ok:false,localOnly:true}),sendPrompt:async()=>{alert('This exported snapshot is not connected to Open Learn.');return {ok:false}},openLink:async()=>{alert('Open links from the original Open Learn conversation.');return {ok:false}}}}};`;
  const frame=`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none';script-src 'unsafe-inline' 'unsafe-eval' data:;style-src 'unsafe-inline';img-src data: blob: https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/ https://upload.wikimedia.org/ https://thumb.wikimedia.org/;connect-src 'none';form-action 'none';base-uri 'none'"><script type="importmap">${script(JSON.stringify({imports}))}</script><style>${css(THEME_CSS+SVG_CLASSES_CSS+FORM_STYLES_CSS+LEAFLET_CSS+hostVisualTheme()+styles)}</style>${TRIP_ANIMATOR_SCRIPT}<script>${script(bridge)}</script></head><body>${body}<script>${script(functions)}\n(async()=>{${expressions.map(script).join(';\n')}})().catch(()=>{const error=document.createElement('p');error.textContent='This visual could not initialize.';document.body.append(error)});</script></body></html>`;
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(visual.title)}</title><style>body{margin:0;font:14px system-ui}header{padding:12px}iframe{border:0;width:100%;height:calc(100vh - 70px)}</style></head><body><header>${escapeHtml(visual.title)} · saved revision ${visual.revision}. Maps and photos require internet.</header><iframe title="${escapeHtml(visual.title)}" sandbox="allow-scripts allow-modals" srcdoc="${escapeHtml(frame)}"></iframe></body></html>`;
}
