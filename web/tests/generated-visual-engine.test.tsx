import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {describe,it,expect,vi} from 'vitest';
import {parseGeneratedVisual} from '@/lib/generated-visual';
import {visualProgram} from '@/components/generated-visual/program';
import {MEASUREMENT_JS,buildFinalFrameContent} from '@/components/generated-visual/upstream/frame-content';
import {IMPORTMAP} from '@/components/generated-visual/upstream/design-system';

vi.mock('@/lib/api',()=>({request:vi.fn()}));
vi.mock('@/lib/voice/client',()=>({reportVoiceFocus:vi.fn(),VOICE_REFRESH:'voice-refresh'}));
vi.mock('@/components/generated-visual/upstream/renderer',()=>({OpenGenUIActivityRenderer:()=><div data-testid="frame"/>}));

const base={version:2,type:'generated_ui',id:'v2',revision:1,title:'Pendulum',renderer:'open_generative_ui',content:{html:['<p>Pendulum</p>']},
  controls:[{id:'gravity',label:'Gravity',minimum:1,maximum:25,initial:9.8}],controlValues:{gravity:3.7}};

describe('generative UI engine contracts',()=>{
  it('accepts optional lineage and verification and stays compatible with historical records',()=>{
    const visual=parseGeneratedVisual({...base,lineage:{rootId:'v1',parentId:'v1',parentRevision:4,version:2},
      verification:{status:'passed',digest:'abc',durationMs:4100,findings:[{severity:'warning',code:'unlabeled_control'}]}})!;
    expect(visual.lineage?.version).toBe(2);
    expect(visual.verification?.status).toBe('passed');
    const historical=parseGeneratedVisual(base)!;
    expect(historical.lineage).toBeUndefined();
    expect(parseGeneratedVisual({...base,lineage:{rootId:'v1',parentId:'bad id',parentRevision:1,version:2}})).toBeNull();
    expect(parseGeneratedVisual({...base,lineage:{rootId:'v1',parentId:'v1',parentRevision:1,version:1}})).toBeNull();
  });

  it('runs saved control state through the shared program used by the card and the verifier',()=>{
    const program=visualProgram({html:['<input id="gravity" type="range">'],jsExpressions:['setup()']},{gravity:3.7});
    expect(program.jsExpressions?.[0]).toBe('setup()');
    expect(program.jsExpressions?.at(-1)).toContain('{"gravity":3.7}');
    expect(visualProgram({html:['<p>x</p>']},{})).toEqual({html:['<p>x</p>']});
  });

  it('reports bounded runtime error messages through the bridge',()=>{
    expect(MEASUREMENT_JS).toContain('reportVisualError("error",event.error||event.message)');
    expect(MEASUREMENT_JS).toContain('message.slice(0,300)');
    expect(buildFinalFrameContent('<p>x</p>')).toContain("connect-src 'none'");
  });

  it('resolves the OrbitControls path taught by the upstream skill',()=>{
    expect(IMPORTMAP.imports['three/examples/jsm/controls/OrbitControls.js']).toBe(IMPORTMAP.imports['three/addons/controls/OrbitControls.js']);
  });

  it('labels revised versions and offers full screen',async()=>{
    (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
    const {GeneratedVisualCard}=await import('@/components/generated-visual/generated-visual');
    const visual=parseGeneratedVisual({...base,lineage:{rootId:'v1',parentId:'v1',parentRevision:4,version:3}})!;
    const container=document.createElement('div');document.body.appendChild(container);const root=createRoot(container);
    await act(async()=>root.render(<GeneratedVisualCard visual={visual} lessonId="lesson"/>));
    expect(container.textContent).toContain('Version 3');
    const expand=Array.from(container.querySelectorAll('button')).find(button=>button.textContent==='Full screen')!;
    await act(async()=>{expand.click();});
    expect(container.querySelector('figure')!.className).toMatch(/expanded/);
    expect(expand.getAttribute('aria-pressed')).toBe('true');
    act(()=>root.unmount());container.remove();
  });

  it('describes repair progress truthfully',async()=>{
    const {progressLabel}=await import('@/components/generated-visual/visual-runs');
    expect(progressLabel()).toBe('Preparing an interactive visual…');
    expect(progressLabel({attempt:1,maxAttempts:3,stage:'verifying',findings:[]})).toBe('Testing the visual in a sandbox…');
    expect(progressLabel({attempt:1,maxAttempts:3,stage:'repairing',findings:['runtime_exception']})).toBe('Fixing 1 problem found in testing (attempt 2 of 3)…');
    expect(progressLabel({attempt:2,maxAttempts:3,stage:'generating',findings:['a','b']})).toBe('Fixing 2 problems found in testing (attempt 2 of 3)…');
    expect(progressLabel({attempt:2,maxAttempts:3,stage:'verifying',findings:[]})).toBe('Testing the revised visual (attempt 2 of 3)…');
  });
});
