"use client";
import { useState } from 'react';
import { VoiceDock } from './voice-dock';

/** Development-only presentation fixture; never dispatches provider or domain calls. */
export function VoicePreview() {
  const [setup, setSetup] = useState(false);
  const [muted, setMuted] = useState(false);
  const [captions, setCaptions] = useState(true);
  const [active, setActive] = useState(true);
  return <main style={{ maxWidth: 760, margin: 'auto', padding: 32 }}><h1>Voice UI preview</h1><p>Presentation fixture — no microphone, provider session, or saved actions.</p>
    <button onClick={() => setSetup(true)}>Preview first-use notice</button><button onClick={() => setActive(true)}>Show conversation dock</button>
    <h2>Study workspace</h2><p>The normal quiz, note, and diagram panels stay available during a call.</p>
    <VoiceDock setup={setup} session={active ? { id: 'preview', chatId: 'preview', status: 'active', sequence: 2, epoch: 0, expiresAt: 0, url: '', token: '' } : null} state={muted ? 'Muted' : 'Listening'} error="" muted={muted} captions={captions} device="" devices={[]} onDevice={() => undefined} onStart={() => setSetup(false)} onDismiss={() => setSetup(false)} onEnd={() => setActive(false)} onMute={() => setMuted(!muted)} onStop={() => undefined} onCaptions={() => setCaptions(!captions)} onOpen={() => undefined} onResume={() => undefined} events={[
      { sequence: 1, voiceSessionId: 'preview', type: 'turn.started', text: 'Create a quiz from this chapter.' },
      { sequence: 2, voiceSessionId: 'preview', type: 'speech.ready', text: 'Your quiz is ready. Let’s start with the first question.' },
      { sequence: 3, voiceSessionId: 'preview', type: 'action.updated', callId: 'preview-task', status: 'succeeded', userMessage: 'Five questions · Photosynthesis', artifactRef: { kind: 'quiz', id: 'preview-quiz' }, uiIntent: { action: 'open_quiz', targetId: 'preview-quiz' } },
    ]} />
  </main>;
}
