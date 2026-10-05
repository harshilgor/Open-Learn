# Open Learn native client

Expo/React Native client for the existing authenticated FastAPI, agent, learning, lecture and responsibility contracts. Use a native development build, because lecture capture includes a local Android/iOS Expo module.

Copy `.env.example` to `.env` and supply public identifiers. Keep API/provider/storage secrets on the backend. See [hosted setup](../docs/HOSTED_MOBILE_SETUP.md) for account choices and required device acceptance.

```powershell
npm ci
npm run typecheck
npm test
npm run export
npm run check:release
```

Regenerate schema types from the repository root with `python -m backend.scripts.generate_mobile_contracts`. For local Android native development, install the Android/JDK toolchain and use `npm run android`; iOS local builds need macOS/Xcode. EAS profiles are provided for development, preview and production, but no signed build has been produced.

Messages and lecture manifests are durable and scoped to the verified owner. Failed messages retry with their original idempotency key; revision conflicts require review. Lecture capture writes playable WAV segments and native recovery journals, then uploads the same recording/sequence/hash through the existing protocol. Stop and acknowledgment are required before finalization. A short voice message is reviewed and transcribed separately; its transcript must be sent explicitly.

Chats expose task controls, clarification, retained sources, downloads, connected-action review, explanation/quiz continuation and expiring cloud browser takeover. Recordings expose local recovery, remote processing, transcript, timestamped notes and audio playback. Inbox supports responsibilities and optional phone push. Hosted workers continue execution while the phone is closed.

Classes now exposes consent-gated microphone capture, course/title setup, pause/resume, timestamp markers, explicit Stop, slice upload/transcription counts, retry, and live class workspace navigation. The capture controller stays mounted across navigation. The existing native WAV journal seals slices locally; foreground inspection recovers interrupted capture after process death, while uploaded slices keep the same recording/sequence/checksum and class device/epoch fences. A process restart never silently starts the microphone. Stopped pending class uploads retry on reconnect. Sign out stops this phone's class microphone before removing the account. Local audio remains in the private app directory; finalized class audio can be explicitly deleted from the capture panel (uploaded audio/notes remain governed by server retention).

Deterministic protocol tests cover persisted lost-response recovery, stable class setup/device headers, markers, account isolation, checksums and finalize ordering. TypeScript checks pass. Native iOS/Android acceptance remains required: microphone denial/revocation, phone calls, background/foreground, OS kill/restart, battery restrictions, low storage, offline capture/reconnect, logout/Stop and cross-device reopen. Android uses a visible microphone foreground service; iOS uses the audio session/background capability. No device or signed build was available for acceptance here; OS background recording guarantees must be measured on supported versions. Captures interrupted by the OS are sealed/recovered and remain marked interrupted rather than silently resumed.
