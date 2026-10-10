import {describe,it,expect,vi,afterEach} from 'vitest';
import {exportVisualHtml} from '@/components/generated-visual/export';
import {parseGeneratedVisual} from '@/lib/generated-visual';
afterEach(()=>vi.unstubAllGlobals());
describe('portable visual exports',()=>{
  it('isolates code and embeds reviewed libraries with current numeric state',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>new Response('export const value=1;')));
    const visual=parseGeneratedVisual({version:2,type:'generated_ui',id:'v',revision:3,title:'<unsafe>',renderer:'open_generative_ui',controls:[{id:'mass',label:'Mass',minimum:1,maximum:10,initial:2}],controlValues:{mass:5},content:{html:['<input id="mass" type="range" min="1" max="10">'],jsFunctions:'async function init(){await import("d3")}',jsExpressions:['init()']}})!;
    const html=await exportVisualHtml(visual);
    expect(html).toContain('sandbox="allow-scripts allow-modals"');
    expect(html).not.toContain('allow-same-origin');expect(html).toContain('&lt;unsafe&gt;');
    expect(html).toContain('data:text/javascript;base64,');expect(html).toContain('&quot;mass&quot;:5');
    expect(html).toContain("connect-src &#39;none&#39;");
  });
  it('exports tables as escaped accessible values without fetching assets',async()=>{
    const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
    const visual=parseGeneratedVisual({version:2,type:'generated_ui',id:'v',revision:1,title:'Table',renderer:'a2ui',content:{title:'Values',columns:['Name'],rows:[['<script>bad()</script>']],source:'User data'}})!;
    const html=await exportVisualHtml(visual);
    expect(html).toContain('&amp;lt;script&amp;gt;');expect(html).toContain('&lt;caption&gt;Values');expect(fetch).not.toHaveBeenCalled();
  });
});
