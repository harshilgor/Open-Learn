# Chat dictation implementation plan

Status: core streaming service and composer integration implemented. Production enablement and live-provider/browser acceptance remain required. See DICTATION_SETUP.md for the implemented behavior and configuration. October 6, 2026.

## Product behavior

Dictation turns microphone audio into an editable chat draft. It does not create a chat, send a message, start a Buddy conversation, or change Conversation/Ask/Learn/Quiz or explanation depth. The existing Send action submits the reviewed draft through the existing workflow.

The main composer keeps its attachment button on the left and adds a microphone immediately before the existing waveform voice-conversation button on the right. Tooltips and accessible names distinguish “Dictate message” from “Talk to Buddy”. Explain and Conversation remain below the composer. Both entry points are available on mobile.

On activation, request microphone permission from an explicit click. Preserve the draft and selection. Show a small listening strip inside the composer: cancel, an audio-reactive waveform, elapsed time, and Done. Use the existing Motion library for a spring transition into this strip, fades between states, and microphone activation. The waveform reflects actual microphone amplitude; reduced motion uses a static level indicator. Keep the exterior composer dimensions stable as far as text growth allows.

Show live provisional transcription separately from the editable draft. On Done, stop capture immediately, finalize remaining audio, and insert the finalized transcript at the saved cursor or selection. Return focus to the textarea, place the cursor after the inserted text, and enable editing and sending. Do not automatically submit on silence or Done. During listening/finalization, block Send and prevent typing from conflicting with the pending insertion. Cancel restores the exact original draft and discards only this dictation session. Recording and full voice conversation are mutually exclusive.

Proposed initial limits: 90 seconds per recording, with a warning before cutoff; automatic finalization at the limit. Server limits must enforce this independently of browser timers. Silence can prompt the user to finish but must not submit a message. Enforce the existing 4,000-character composer limit without silent transcript truncation: retain overflow in the review panel and explain what needs shortening before insertion.

## Existing implementation to reuse

- `web/components/chat-composer.tsx`: controlled draft, textarea, attachments, note mentions, voice and send/stop actions.
- `web/components/voice/voice-provider.tsx`: voice-active state and existing microphone lifecycle patterns. Dictation must coordinate with this provider rather than use its agent session as a transport.
- `voice-agent/agent.py`: already uses Deepgram Flux for conversational STT. Dictation should use a transcription-oriented provider configuration rather than agent turn-taking.
- `backend/app/mobile_routes.py`: `/v1/mobile/voice-transcriptions` implements bounded upload, authentication, duplicate-request handling, and short-recording transcription. It is mobile-feature-gated, uses a daily-call policy, and stores receipts; extract reusable services rather than directly wiring the web composer to it.
- `backend/app/lecture_provider.py`: existing batch transcription adapter can support an explicitly configured fallback.
- `backend/app/voice/routes.py` and `backend/app/usage/`: reuse ledger reservations, dispatch/settlement, ownership validation, and concurrency patterns. Dictation should meter only speech transcription, without LiveKit agent or TTS charges.

## Recommended transport

Use browser microphone capture -> authenticated FastAPI WebSocket proxy -> Deepgram Nova streaming -> normalized transcript events -> local draft review.

The backend proxy keeps provider credentials private and controls wall-clock, audio bytes, concurrency, and allowance limits. Host the WebSocket on the backend service, not a long-lived Next.js/Vercel function. Start with explicit language configuration and evaluate accents, course vocabulary, and mixed-language speech before broad multilingual claims.

Use AudioWorklet to deliver continuous mono PCM. Set the provider sample rate to the actual capture rate, or use a tested resampler; never label 48 kHz audio as 16 kHz. This avoids dependence on browser-specific MediaRecorder containers for streaming. A bounded MediaRecorder upload adapter is a later fallback; choose supported MIME types at runtime with `MediaRecorder.isTypeSupported()` and preserve the actual MIME type in the upload. Do not silently retranscribe the same recording with a second provider after an uncertain failure.

Nova supports provisional and final transcript events and explicit Finalize. Keep provisional text separate, deduplicate finalized segments, and wait for bounded finalization before closing the provider connection. Do not treat every interim string as new text to append.

Do not rely on browser SpeechRecognition as the primary engine: support is limited and provider behavior varies across browsers.

## Proposed service and client boundaries

- `POST /v1/dictation/sessions`: normal account auth; idempotency key; validate capability, account status, allowance and concurrent microphone/session use; reserve bounded speech usage; issue a single-use, short-lived connection ticket. No chat ID required.
- `WS /v1/dictation/sessions/{id}/stream`: validate ticket and owner association before accepting audio. Prefer ticket authentication as the first protocol message with a short auth timeout; do not put account bearer tokens in URL query strings. Tickets cannot select arbitrary provider models or change limits.
- Normalize events as ready, transcript.interim, transcript.final, completed, and error. Include session ID, sequence and stable segment IDs to reject duplicates and stale updates. A new dictation attempt increments the client generation guard.
- Client commands: finish and cancel. Enforce server shutdown on duration/byte caps, budget exhaustion, heartbeat loss, disconnect, sign-out and expiration. Close the upstream provider socket on every exit path.
- `useDictation`: idle -> requesting permission -> connecting -> listening -> finalizing -> review/idle or error. Own microphone tracks, AudioContext/worklet, socket, timers, provisional transcript and session generation. Cancel late permission results and stop tracks even when the component has already unmounted.
- `DictationControls`: reusable UI independent of chat submit. Integrate first into the main ChatComposer; extend to compact tutor inputs after verification.

Keep audio in memory only by default; do not store recordings in course materials or chat attachments. On a connection failure, preserve the original draft and finalized text for explicit review. Show any unfinished provisional phrase as uncertain instead of silently treating it as final. A cancelled recording can still incur already-used STT cost; cancel must stop further usage. Record usage receipts and outcomes without putting transcript bodies into operational logs. Provider retention should be checked against the chosen account configuration; memory-only app handling does not imply zero provider retention.

## Verification and rollout

1. Unit-test transcript replacement/deduplication, stale events, cursor insertion, cancellation, overflow and permission/unmount races.
2. Component-test recording controls, draft preservation, disabled send, mode/depth preservation and accessibility.
3. Backend-test session ownership, ticket expiry/replay, duration and byte caps, allowance refusal, disconnect cleanup and idempotent settlement.
4. Real-browser-test Chrome, Safari/iOS and Firefox; microphone denial, no microphone, backgrounding, silence, disconnect during finalization, repeat dictation and conflict with voice conversation. Use deliberate test audio, and check actual provider-session shutdown.
5. Release behind an independent dictation capability flag. Measure first interim latency, finalization latency, correction quality and usage settlement before enabling broadly. Initial targets, not guarantees: first interim within about one second, finalization within about two seconds under normal network conditions.

## Primary references

- [Deepgram streaming API](https://developers.deepgram.com/reference/speech-to-text/listen-streaming)
- [Deepgram interim results](https://developers.deepgram.com/docs/interim-results)
- [Deepgram Finalize](https://developers.deepgram.com/docs/finalize)
- [Deepgram models](https://developers.deepgram.com/docs/model)
- [MDN MediaRecorder format support](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/isTypeSupported_static)
- [MDN SpeechRecognition support](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition)
