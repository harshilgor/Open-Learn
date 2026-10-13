import type {GeneratedVisual} from '@/lib/generated-visual';

/** Support common global-style library output using only reviewed local modules. */
export function compatibleContent(content:Extract<GeneratedVisual,{renderer:'open_generative_ui'}>['content']){
  const code=(content.jsFunctions||'')+'\n'+(content.jsExpressions||[]).join('\n');
  const loads:string[]=[];
  if(/\bTHREE\b/.test(code))loads.push('window.THREE={...(await import("three"))};');
  if(/\bOrbitControls\b/.test(code))loads.push('window.OrbitControls=(await import("three/addons/controls/OrbitControls.js")).OrbitControls;if(window.THREE)window.THREE.OrbitControls=window.OrbitControls;');
  if(/\bChart\b/.test(code))loads.push(`const chartModule=await import("chart.js");window.Chart=chartModule.Chart||chartModule.default;
const theme=getComputedStyle(document.documentElement);Chart.defaults.color=theme.getPropertyValue('--color-text-primary').trim()||'#777';
Chart.register({id:'openlearn-theme-colors',beforeInit(chart){const colors=['--color-text-info','--color-text-success','--color-text-warning','--color-text-danger'].map(name=>theme.getPropertyValue(name).trim());for(const [index,dataset] of chart.data.datasets.entries()){for(const key of ['backgroundColor','borderColor']){const color=dataset[key];if(typeof color==='string'&&!CSS.supports('color',color)||color==null)dataset[key]=colors[index%colors.length]||'#6688bb';}}}});`);
  if(/\bd3\b/.test(code))loads.push('window.d3=await import("d3");');
  if(/\bgsap\b/.test(code))loads.push('const gsapModule=await import("gsap");window.gsap=gsapModule.gsap||gsapModule.default;');
  if(/\bL\.(?:map|tileLayer|circleMarker|marker|polyline)\b/.test(code))loads.push('const leafletModule=await import("leaflet");window.L=leafletModule.default||leafletModule;');
  if(!loads.length)return content;
  const initialize=loads.join('\n');
  return {...content,jsExpressions:(content.jsExpressions||[]).map(expression=>`(async()=>{${initialize}\n${expression}\n})()`)};
}
