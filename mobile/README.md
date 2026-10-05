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
