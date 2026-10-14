# In-Class V2 Android acceptance

Status: Android phone available, confirmed by the user on 2026-10-13. No physical-device checks have run. The current Windows host has no Java, Android SDK/adb or Gradle commands available. Expo Go cannot load the custom lecture-capture module.

## Build and connection

Use the existing `mobile/eas.json` development profile with your configured Expo account/project, or install the Android toolchain and build locally. Preserve the existing authentication configuration. Do not replace hosted identity with development headers on a public service.

```powershell
cd mobile
npm run typecheck
npm test
npx eas-cli build --platform android --profile development
```

EAS requires an authenticated Expo account, the configured project ID and build environment values. The phone build needs a reachable HTTPS `EXPO_PUBLIC_API_URL` and the existing OIDC issuer/client/audience configuration. Install the resulting development APK. Start Metro with `npm start` and open the development build. For a local native build with Java/Android SDK installed, use `npm run android` instead.

Backend schema must be at `0091_class_evidence_indexes`; start the existing lecture and In-Class workers. AssemblyAI credentials belong only in backend secrets. Enable the reviewed class speech flags only in a test environment until acceptance passes. Existing usage enforcement, reviewed rates and platform ceilings must stay configured.

## Physical acceptance checklist

Record consenting synthetic speech or an authorized practice lecture. Do not record an actual class without the app's consent step and the required permission for that class.

| Check | Steps | Pass evidence |
| --- | --- | --- |
| Pairing | Choose phone on laptop, scan QR or enter code, sign into the same account, consent | Laptop shows Recording only after native start; another account cannot claim |
| Permission denial | Deny microphone permission, then permit explicitly | Honest error, no false Recording state, no silent restart |
| Native microphone | Read technical words, numbers and an equation for 2 minutes | Audible saved audio, timed transcript, words manually compared |
| Screen lock | Lock phone for 5 minutes | Foreground recording notification and durable chunks; caption limitations recorded separately |
| Network outage | Disable network for 3 minutes, then reconnect | Audio journal survives; backlog drains without duplicated sequence ranges |
| Remote controls | Pause/resume; deny one resume request; request Stop while offline | Commands remain pending until actual device acknowledgment; resume requires phone confirmation |
| Interruption | Receive a call and return to the app | Actual native state matches UI; interruption/gap visible |
| Process death | Kill recording process, reopen | Sealed audio recovered; no automatic microphone restart |
| Handoff | Stop old device through handoff; claim second device before old uploads finish | Epoch advances after acknowledgment, old audio uploads retain original offsets |
| Buddy | Ask at a fixed moment while speech continues | Answer uses frozen moment; source passages visible; no automatic speech output |
| Correction | Correct a cited transcript passage after editing its note | Buddy/visual review warning; student wording preserved; regenerated notes are a suggestion |
| Final package | Stop after offline gap, recover remaining audio | Missing coverage marked partial; later recovery reconciles artifacts |

Record phone model, Android version, build revision, microphone routing, network state, start/stop times, interruptions, server acknowledgment times and failures. Measure caption latency, verified transcript latency, note latency and Buddy first text separately. Include billed provider usage and compare actual words against a manually checked transcript. A passing synthetic API smoke check does not prove these native guarantees.

## Current software evidence

- Integrated backend suite: 83 passed; focused final checks recorded in the build progress document.
- Mobile protocol suite: 16 passed; web/mobile TypeScript checks passed.
- Real prerecorded AssemblyAI: 9.597 seconds of synthetic speech, Universal-3.5 Pro, 22 timed words, 3.17 seconds elapsed, $0.000559825 estimated cost; provider transcript deleted.
- Real streaming relay: Universal-3.6 Pro, 12.45 seconds elapsed, 9 caption events, 3 persisted final captions, zero relay errors, $0.001625 estimated cost.

These costs are conservative local ledger estimates, not a provider invoice. No real lecture accuracy improvement, physical Android behavior or iOS support claim is made yet.


## Wireless installation — no USB required

For an APK that runs without Metro, use the existing **preview** profile:

```powershell
cd mobile
npx eas-cli@latest login
# Configure .env from .env.example with your real public HTTPS/OIDC/project values.
npx eas-cli@latest build --platform android --profile preview
```

Open the resulting Expo installation link on the phone and install the APK. Keep provider keys on the backend. EAS account/project configuration and mobile public environment are required; this host was not logged into Expo and mobile/.env was absent at the last probe. The user explicitly deferred this setup on 2026-10-13. No APK has been built or native test passed.

The development profile uses a development client and Metro. The preview profile bundles the application, so normal installation/testing can happen over the internet. Optional Android wireless debugging can collect native logs on supported devices once adb is installed; local network pairing requires the phone and computer to share a reachable Wi-Fi network. Never expose an adb debugging port to the public internet.

Add the new phone preflight to the checklist: grant permission explicitly, speak for five seconds, check low-input/clipping messages, background/cancel the check, and confirm the temporary sample is deleted and never appears in uploads. Native metering and permission behavior have only passed TypeScript verification so far.
