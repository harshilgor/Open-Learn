# Dictation setup and verification

The web composer now has separate **Dictate message** (microphone) and **Talk to Buddy** (waveform) actions. Dictation produces editable text and never submits a chat message. Conversation mode, explanation depth, notes and attachments retain their existing behavior.

## Backend configuration

Install the backend requirements, including `websockets>=14,<17`, then configure:

```dotenv
OPENLEARN_DICTATION_ENABLED=true
OPENLEARN_DICTATION_SECRET=<random secret of at least 32 characters shared across backend workers>
DEEPGRAM_API_KEY=<server-side Deepgram key>
OPENLEARN_DICTATION_USD_PER_MINUTE=<your verified Nova-3 streaming USD tariff>
OPENLEARN_DICTATION_WS_URL=wss://YOUR-BACKEND-HOST/v1/dictation/stream
```

Keep secrets server-side. Use the existing enforced usage configuration, including `OPENLEARN_USAGE_PAID_ROUTES_ENABLED=true`, a pinned `OPENLEARN_PROVIDER_RATE_VERSION`, and the platform budget settings required by production. The independent dictation rate must match Nova-3; the existing Flux voice-conversation rate may differ. No guessed rate or paid-production configuration has been enabled by this change.

`OPENLEARN_DICTATION_WS_URL` must point directly to the FastAPI service, not the website's HTTP API proxy. The proxy can serve session creation through normal authenticated requests, but it cannot relay a persistent WebSocket on the current frontend hosting setup. For direct local backend access, the server derives a loopback URL when the override is absent. HTTPS/WSS is required outside loopback. Reverse proxies must permit WebSocket upgrades and at least a 100-second connection. The app sends the single-use session ticket in its first socket message, never in the URL.

`GET /v1/dictation/capability` reports availability. Session creation reserves up to 90 seconds of STT usage. Reservations are single-use, owner-bound and durable; unused sessions can be cancelled through the authenticated cancellation endpoint. Cancelled/expired holds also remain covered by the existing reconciliation machinery. When Deepgram returns final Metadata, sessions settle using its processed-audio duration and request ID at the immutable reserved rate. Missing or invalid provider receipts retain the conservative 90-second bound as estimated usage, including interrupted recordings without a receipt. No LiveKit or TTS charges are added.

## User behavior

- Click the microphone, grant microphone permission, and speak. The composer shows provisional text, audio-reactive bars, an elapsed timer, Cancel and Done.
- Click Done to stop capture immediately. Finalized text is inserted at the saved cursor or selection. Review/edit the draft, then click Send yourself.
- Cancel leaves the original draft intact. No audio is retained in application storage.
- On interruption, finalized text is available for explicit review and insertion. Unfinished provisional text is labelled separately.
- Text exceeding the 4,000-character composer limit is retained in a review field for shortening; it is not silently truncated.
- Another dictation, a voice conversation, account change, backgrounding or component unmount stops the microphone. Permission results arriving after cancellation also have their tracks stopped.
- Initial language configuration is English (`en-US`). Mixed-language accuracy has not been validated.
- The AudioWorklet capture runs at a browser-resampled 48 kHz and sends mono PCM. Unsupported capture environments show an actionable error and preserve typing.

## Readiness check

Run `python backend/scripts/check_dictation.py` to validate environment readiness. It reports presence and validity flags without exposing credentials or making paid calls. The local key and dictation settings are now configured. The live acceptance script enables a speech-only policy in its own process; the general backend paid-routing flag remains disabled because the existing local sandbox configuration is incompatible with enforced paid usage.

## Automated checks

```powershell
python -m pytest backend/tests/test_dictation.py backend/tests/test_mobile_release.py -q -p no:cacheprovider
cd web
npx vitest run tests/dictation.test.tsx tests/dictation-capture.test.tsx tests/tutor-components.test.tsx
```

Coverage includes streaming finalization, provider shutdown, durable replay rejection, cancelled holds, concurrent recordings, expired/invalid tickets, oversized frames, disabled capability, microphone shutdown, stale results, late permission results, transcript deduplication, selection insertion and overflow handling. Tests use a fake speech provider and fake microphone, without external paid calls.

## Production acceptance still required

Use a deliberate test recording in Chrome, Safari/iOS and Firefox with the configured backend. Verify first microphone permission, denied permission, no microphone, silent recording, accents/course vocabulary, 90-second cutoff, loss of connectivity during finalization, repeated dictation and switching to Talk to Buddy. Confirm provider connection shutdown and matching ledger settlement. Do not consider mocked tests proof of live provider connectivity or cross-browser audio capture.


## Local live acceptance — October 6, 2026

A Windows-synthesized 5.38-second phrase was streamed through the real dictation routes to Deepgram Nova-3. Deepgram returned: “Explain gravity in simple terms. Do not send this message yet.” Finalization and provider-duration settlement passed. At the published Nova-3 English pay-as-you-go rate of $0.0048/minute, the 5,384 ms receipt produced a calculated cost of $0.00043072. Source: https://deepgram.com/pricing (checked October 6, 2026).

Run `python backend/scripts/test_dictation_live.py` after creating `work/dictation-live/test-speech.wav` as mono, 16-bit PCM. This makes paid provider calls using synthetic test audio. It isolates unrelated sandbox, browser and voice-agent capabilities in the test process, uses a separate SQLite database, and writes `work/dictation-live/result.json`. No production configuration is changed. Browser permission prompts, AudioWorklet capture on physical devices, and mobile browsers remain separate manual acceptance checks.
