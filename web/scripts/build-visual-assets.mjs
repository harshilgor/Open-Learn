// Bundle reviewed libraries so generated frames need no CDN or arbitrary network.
import { build } from 'esbuild';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import {dirname,resolve} from 'node:path';
const root=fileURLToPath(new URL('../',import.meta.url));
const require=createRequire(new URL('../package.json',import.meta.url));
const out=new URL('../public/visual-assets/',import.meta.url);
await mkdir(out,{recursive:true});
const modules={three:'three',gsap:'gsap',d3:'d3',chart:'chart.js/auto',leaflet:'leaflet','orbit-controls':'three/addons/controls/OrbitControls.js'};
for(const [name,module] of Object.entries(modules)) {
  const entry=name==='three'?resolve(dirname(require.resolve('three')),'three.module.js'):name==='leaflet'?resolve(dirname(require.resolve('leaflet')),'leaflet-src.esm.js'):require.resolve(module);
  await build({...name==='leaflet'?{stdin:{contents:`import * as L from ${JSON.stringify(entry)}; export * from ${JSON.stringify(entry)}; export default L; export const createTripAnimator=(...args)=>window.createTripAnimator(...args);`,resolveDir:root}}:{entryPoints:[entry]},bundle:true,format:'esm',platform:'browser',minify:true,
    outfile:fileURLToPath(new URL(name+'.js',out)),absWorkingDir:root,
    plugins:name==='orbit-controls'?[{name:'shared-three',setup(builder){builder.onResolve({filter:/^three$/},()=>({path:'./three.js',external:true}));}}]:[]});
}
await writeFile(new URL('manifest.json',out),JSON.stringify({version:1,modules,network:'local-only'},null,2));
console.log('Local visual library assets built.');
