"""Import pinned MIT renderer sources; explicit host adaptations remain reviewable."""
from pathlib import Path
import json
import subprocess
import re

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'work/research/openintelligentui-20261009'
COMMIT = 'f6e4388b26a64b9a0714943b08a1ce622b924eec'
actual = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
if actual != COMMIT:
    raise SystemExit('Upstream revision mismatch; review the import before updating it.')
TARGET = ROOT / 'web/components/generated-visual/upstream'
TARGET.mkdir(parents=True, exist_ok=True)
base = SOURCE / 'apps/app/src/components/generative-ui'
for name in ('schema.ts', 'websandbox-loader.ts', 'websandbox.d.ts', 'process-partial-html.ts', 'trip-animator.ts', 'frame-content.ts', 'renderer.tsx'):
    code = (base / 'open-generative-ui' / name).read_text(encoding='utf-8')
    code = code.replace('from "@repo/design-system"', 'from "./design-system"')
    code = code.replace('import { useSandboxFunctions } from "@copilotkit/react-core/v2";', 'import { useSandboxFunctions } from "../sandbox-context";')
    code = code.replace('import { ExportOverlay } from "../export-overlay";\n', '')
    code = code.replace('import { assembleStandaloneHtmlFromActivity } from "../export-utils";\n', '')
    code = code.replace('from "../idiomorph-inline"', 'from "./idiomorph-inline"')
    if name == 'trip-animator.ts':
        code = code.replace('return { play, pause, replay, seek, dispose };','return { play, pause, replay, restart: replay, resume: play, seek, dispose };')
        code = code.replace('options.pinElements?.forEach', 'options.pinElements?.filter(Boolean).forEach')
        code = code.replace('const { stopCount, onFrame, onState } = options;', 'const { stopCount, onFrame, onState } = options;\n  if (options.pinElements?.some(pin => !pin)) options.pinElements = Array.from(document.querySelectorAll<HTMLElement>(".pin-dot")).slice(0, stopCount);')
    if name == 'renderer.tsx':
        code = code.replace('console.error("[OpenGenUI] Failed to load sandbox module:", err);', 'console.error("[OpenGenUI] Failed to load sandbox module:", err); Promise.resolve(localApi.visualError?.({})).catch(()=>{});')
        start = code.index('    const exportHtml = useMemo(')
        end = code.index('    const frame = (', start)
        code = code[:start] + code[end:]
        start = code.index('    // Always wrap in ExportOverlay')
        end = code.index('\n  },', start)
        code = code[:start] + '    return <div>{frame}</div>;\n' + code[end:]
        # These statements must describe real progress, not hypothetical actions.
        start = code.index('export const LOADING_PHRASES = [')
        end = code.index('];', start) + 2
        code = code[:start] + 'export const LOADING_PHRASES = ["Preparing interactive visual"];' + code[end:]
    if name == 'frame-content.ts':
        code = 'import { hostVisualTheme } from "../theme";\n' + code
        code = 'import { LEAFLET_CSS } from "./leaflet-css";\n' + code
        code = code.replace('${THEME_CSS}\\n', '${LEAFLET_CSS}\\n${THEME_CSS}\\n')
        code = code.replace('DESIGN_SYSTEM_STYLE_TAG +', 'DESIGN_SYSTEM_STYLE_TAG + `<style>${hostVisualTheme()}</style>` +')
        code = code.replace('const parts = [OVERFLOW_HIDDEN_STYLE_TAG, DESIGN_SYSTEM_STYLE_TAG];', 'const parts = [OVERFLOW_HIDDEN_STYLE_TAG, DESIGN_SYSTEM_STYLE_TAG, `<style>${hostVisualTheme()}</style>`];')
        # The preview and final frame get the same restrictive policy. Trusted
        # library assets are bundled locally; model code cannot contact CDNs.
        start = code.index('export const CSP_META_TAG = ')
        end = code.index('\n\nexport function ensureHead', start)
        code = code[:start] + '''const ASSET_ORIGIN = typeof window === "undefined" ? "" : window.location.origin;
export const CSP_META_TAG = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' ${ASSET_ORIGIN}/visual-assets/; style-src 'unsafe-inline'; img-src data: blob: https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/ https://upload.wikimedia.org/ https://thumb.wikimedia.org/; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none';">`;\n''' + code[end:]
        code = code.replace('export const PREVIEW_FRAME_CONTENT = "<head></head><body></body>";', '')
        code += '\nexport const PREVIEW_FRAME_CONTENT = `<head>${CSP_META_TAG}</head><body></body>`;\n'
        # User interaction in a cross-origin iframe cannot bubble to the host.
        # Forward focus through a canonical host callback, without target IDs.
        code = code.replace('export const MEASUREMENT_JS = `', 'export const MEASUREMENT_JS = `document.addEventListener("pointerdown",()=>{window.Websandbox?.connection?.remote?.focusVisual?.().catch(()=>{});},{passive:true});')
        code = code.replace('export const MEASUREMENT_JS = `', 'export const MEASUREMENT_JS = `document.addEventListener("change",(event)=>{const input=event.target;if(event.isTrusted&&input instanceof HTMLInputElement&&["range","number"].includes(input.type)&&input.id&&input.value.trim()&&Number.isFinite(input.valueAsNumber)){window.Websandbox?.connection?.remote?.saveControl?.({id:input.id,value:input.valueAsNumber}).catch(()=>{});}});')
        code = code.replace('export const MEASUREMENT_JS = `', 'export const MEASUREMENT_JS = `window.addEventListener("error",()=>{window.Websandbox?.connection?.remote?.visualError?.({}).catch(()=>{});});window.addEventListener("unhandledrejection",()=>{window.Websandbox?.connection?.remote?.visualError?.({}).catch(()=>{});});')
        code = code.replace('export const MEASUREMENT_JS = `', 'export const MEASUREMENT_JS = `const originalVisualError=console.error.bind(console);console.error=(...args)=>{originalVisualError(...args);window.Websandbox?.connection?.remote?.visualError?.({}).catch(()=>{});};')
    (TARGET / name).write_text('// Adapted from CopilotKit/OpenIntelligentUI; see LICENSE and UPSTREAM.json.\n' + code, encoding='utf-8')
(TARGET / 'idiomorph-inline.ts').write_text((base / 'idiomorph-inline.ts').read_text(encoding='utf-8'), encoding='utf-8')
design = (SOURCE / 'packages/design-system/src/index.ts').read_text(encoding='utf-8')
integration = ROOT / 'integrations/openintelligentui'
(integration / 'design-skill.md').write_text(re.search(r'export const OPEN_GEN_UI_DESIGN_SKILL = `([\s\S]*?)`\.trim\(\);', design).group(1).strip(),encoding='utf-8')
(integration / 'design-system.json').write_text(json.dumps({name:re.search(r'export const '+name+r' = `([\s\S]*?)`;', design).group(1) for name in ('THEME_CSS','SVG_CLASSES_CSS','FORM_STYLES_CSS')}),encoding='utf-8')
for name, module in (('three', 'three'), ('gsap', 'gsap'), ('d3', 'd3'), ('chart.js', 'chart')):
    design = design.replace('"https://esm.sh/' + name + '"', '`${VISUAL_ASSET_ORIGIN}/visual-assets/' + module + '.js`')
# Restrict submodule imports to the specifically reviewed OrbitControls bundle.
for name in ('three/', 'gsap/', 'd3/', 'chart.js/'):
    design = design.replace('    "' + name + '": "https://esm.sh/' + name + '",\n', '')
design = 'const VISUAL_ASSET_ORIGIN = typeof window === "undefined" ? "" : window.location.origin;\n' + design
design = design.replace('"three":', '"three/addons/controls/OrbitControls.js": `${VISUAL_ASSET_ORIGIN}/visual-assets/orbit-controls.js`,\n    "three":')
design = design.replace('"three":', '"leaflet": `${VISUAL_ASSET_ORIGIN}/visual-assets/leaflet.js`,\n    "three":')
(TARGET / 'design-system.ts').write_text(design, encoding='utf-8')
leaflet = ROOT / 'web/node_modules/leaflet'
(TARGET / 'leaflet-css.ts').write_text('export const LEAFLET_CSS = ' + json.dumps((leaflet / 'dist/leaflet.css').read_text(encoding='utf-8')) + ';\n', encoding='utf-8')
(TARGET / 'LEAFLET-LICENSE').write_text((leaflet / 'LICENSE').read_text(encoding='utf-8'), encoding='utf-8')
(TARGET / 'LICENSE').write_text((SOURCE / 'LICENSE').read_text(encoding='utf-8'), encoding='utf-8')
(TARGET / 'UPSTREAM.json').write_text(json.dumps({'repository': 'https://github.com/CopilotKit/OpenIntelligentUI', 'commit': COMMIT,
    'adaptations': ['Open Learn host bridge instead of CopilotKit chat submission', 'local bundled library importmap',
                    'preview and final CSP', 'portable isolated export supplied by host', 'truthful progress message', 'typed numeric state persistence']}, indent=2), encoding='utf-8')
print('Pinned OpenIntelligentUI renderer imported; MIT license preserved.')
