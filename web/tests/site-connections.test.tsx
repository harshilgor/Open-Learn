import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {SiteConnections} from '@/components/site-connections';

const mocks=vi.hoisted(()=>({request:vi.fn(),capabilities:{enabled:true,providerConfigured:true,cloud:{enabled:false,paidRoutesEnabled:true,tariffConfigured:true,credentialsConfigured:true,runtimeInstalled:true,egressVerified:false,lifecycleVerified:false,privateLoginVerified:false}}}));
vi.mock('@/lib/api',()=>({request:mocks.request,apiBaseUrl:()=>''}));
vi.mock('@/lib/account-session',()=>({authenticatedFetch:vi.fn(),ACCOUNT_CHANGED:'account-changed'}));
vi.mock('@/lib/browser-assistant',()=>({SITE_CHANGED:'site-changed'}));

let root:Root,container:HTMLDivElement;
beforeEach(()=>{
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  vi.clearAllMocks();
  mocks.capabilities={enabled:true,providerConfigured:true,cloud:{enabled:false,paidRoutesEnabled:true,tariffConfigured:true,credentialsConfigured:true,runtimeInstalled:true,egressVerified:false,lifecycleVerified:false,privateLoginVerified:false}};
  mocks.request.mockImplementation(async(path:string)=>path==='/v1/assistant/capabilities'?mocks.capabilities:{connections:[]});
  container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);
});
afterEach(()=>{act(()=>root.unmount());container.remove();});

async function render(){await act(async()=>root.render(<SiteConnections/>));await act(async()=>{await Promise.resolve();});}

it('keeps the cloud browser unavailable until every server readiness gate passes',async()=>{
  await render();
  expect(container.querySelector('option[value="cloud"]')?.hasAttribute('disabled')).toBe(true);
});

it('offers temporary read-only cloud sessions without exposing saved-login controls',async()=>{
  mocks.capabilities={enabled:true,providerConfigured:true,cloud:{enabled:true,paidRoutesEnabled:true,tariffConfigured:true,credentialsConfigured:true,runtimeInstalled:true,egressVerified:true,lifecycleVerified:true,privateLoginVerified:false}};
  await render();
  const option=container.querySelector('option[value="cloud"]');
  expect(option?.hasAttribute('disabled')).toBe(false);
  const connection=container.querySelectorAll('select')[1];
  await act(async()=>{connection.value='cloud';connection.dispatchEvent(new Event('change',{bubbles:true}));});
  expect(container.textContent).toContain('temporary and read-only');
  expect(container.textContent).not.toContain('Remember sign-in for this website');
});
