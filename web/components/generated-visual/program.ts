import type {OpenGenUIContent} from './upstream/schema';
import {compatibleContent} from './library-compat';

/**
 * The exact program a final frame executes: library compatibility shims plus
 * saved numeric state. Shared by the chat card and server-side runtime
 * verification so both run identical code in identical order.
 */
export function visualProgram(content:OpenGenUIContent,controlValues:Record<string,number>):OpenGenUIContent{
  const prepared=compatibleContent(content);
  if(!Object.keys(controlValues).length)return prepared;
  // Only validated numeric input IDs and values cross this bridge. No model
  // function name, source code, or arbitrary DOM selector is invoked.
  const state=JSON.stringify(controlValues);
  const apply=`(()=>{for(const [id,value] of Object.entries(${state})){const input=document.getElementById(id);if(input instanceof HTMLInputElement&&['range','number'].includes(input.type)){input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));}}})()`;
  return {...prepared,jsExpressions:[...(prepared.jsExpressions||[]),apply]};
}
