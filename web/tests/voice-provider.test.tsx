import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { VoiceProvider, useVoice } from '@/components/voice/voice-provider';

const mocks = vi.hoisted(() => ({ mic: vi.fn(async () => undefined), observe: vi.fn(), end: vi.fn(async () => undefined) }));
vi.mock('@/lib/voice/client', () => ({
  VOICE_FOCUS:'voice-focus', VOICE_REFRESH:'voice-refresh',
  voiceApi:{ capabilities:async()=>({enabled:true}), create:async()=>({id:'voice',chatId:'chat',url:'wss://test',token:'test',expiresAt:Date.now()/1000+120}), end:mocks.end },
  observeVoice:mocks.observe,
}));
vi.mock('livekit-client', () => ({
  Room:class { localParticipant={setMicrophoneEnabled:mocks.mic}; on(){return this;} async connect(){} async disconnect(){} async startAudio(){} },
  RoomEvent:{}, Track:{Kind:{Audio:'audio'}},
}));
vi.mock('@/lib/account-session', () => ({ACCOUNT_CHANGED:'account-changed'}));
vi.mock('@/lib/workspace-events', () => ({openWorkspaceNote:vi.fn(),openWorkspaceQuiz:vi.fn(),openWorkspaceFlashcards:vi.fn()}));

function Launcher(){const voice=useVoice();return <button onClick={()=>void voice?.start('chat')}>Open voice</button>;}
let cleanup = () => {};
afterEach(()=>{cleanup();vi.clearAllMocks();});

async function start(label:string){
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  const original=Object.getOwnPropertyDescriptor(navigator,'mediaDevices');
  Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{enumerateDevices:async()=>[]}});
  const container=document.createElement('div');document.body.appendChild(container);
  const root=createRoot(container);
  cleanup=()=>{act(()=>root.unmount());container.remove();if(original)Object.defineProperty(navigator,'mediaDevices',original);else Reflect.deleteProperty(navigator,'mediaDevices');};
  mocks.observe.mockImplementation((_id,_signal,receive)=>{receive({type:'session.ready',sequence:1,voiceSessionId:'voice'});return new Promise(()=>{});});
  await act(async()=>root.render(<VoiceProvider><Launcher/></VoiceProvider>));
  await act(async()=>container.querySelector('button')!.click());
  await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent===label)!.click());
  return container;
}

it('never opens the microphone when starting with text, including media readiness',async()=>{
  const container=await start('Start with text');
  expect(mocks.mic).not.toHaveBeenCalledWith(true);
  expect(container.querySelector('[aria-label="Unmute microphone"]')).not.toBeNull();
});

it('opens the microphone for the standard voice start after media readiness',async()=>{
  await start('Start conversation');
  expect(mocks.mic).toHaveBeenCalledWith(true);
});
