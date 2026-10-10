import {THEME_CSS} from './upstream/design-system';
export function hostVisualTheme(){
  if(typeof document==='undefined')return '';
  const dark=document.documentElement.matches('.dark,[data-theme="dark"]');
  const parts=dark?THEME_CSS.match(/@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{([\s\S]*?)\}/):THEME_CSS.match(/:root\s*\{([\s\S]*?)\}/);
  return parts?`:root{${parts[1]}}`:'';
}
