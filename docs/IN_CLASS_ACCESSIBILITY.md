# In-Class accessibility and acceptance evidence

Reviewed 5 October 2026. This report distinguishes source review and deterministic DOM checks from actual assistive technology acceptance. No native device or screen reader was exercised in this environment.

## Evidence recorded

| Area | Environment | Result | Scope |
| --- | --- | --- | --- |
| Class workspace update/reconnect | Windows 11, Node, Vitest 4.1.10, jsdom | 4 integration tests passed | Retained notes and keyboard focus during specialist failure, reconnect, SSE delta; old-class response rejected; processing pause distinct from capture |
| Mobile capture protocol | Node, TypeScript CommonJS transpilation in process | 11 protocol/release tests passed | Durable lost-response retry, checksums, owner scope, class device/epoch headers, markers and finalize ordering |
| Mobile source types | TypeScript 5.9, React Native source | Passed `npm run typecheck` | API and UI types; no native build acceptance |
| Backend foundation probes | Isolated SQLite, deterministic providers, no network | Passed operational runner | 205 transcript segments paged at 100, live notes before stop, replay, queue fairness, metrics percentiles/retention |
| Windows screen reader/browser | Not available | Pending | NVDA/Narrator announcement order, focus navigation, PDF text reading |
| iOS VoiceOver | Device unavailable | Pending | Consent, native permissions, interruption/recovery and dynamic type |
| Android TalkBack | Device unavailable | Pending | Foreground service notification, controls, announcement order and font scaling |
| Zoom/reflow/contrast on deployed UI | Browser acceptance not performed | Pending | Real theme, PDF split pane and responsive capture layout at 200–400% zoom |

The browser suite can run without spawning the config bundler:

```powershell
cd web
node --experimental-strip-types node_modules/vitest/vitest.mjs run tests/in-class.test.tsx --configLoader native --pool threads --maxWorkers 1
```

`--configLoader runner` failed with `require is not defined`. The default bundled loader and the mobile `tsx --test` command previously hit Windows `spawn EPERM`; the native Vitest loader and in-process TypeScript test import worked. These workarounds do not substitute for browser/device acceptance.

## Mobile fixes implemented

- Capture controls expose button roles and disabled states. Consent exposes checkbox/checked state. Course selectors expose selected state. Title input has an accessible name.
- The capture panel remains mounted across app navigation. Opening a class never starts a microphone. Returning from background restores saved state and upload progress without silently restarting capture.
- Recording, paused and stopped transitions use `AccessibilityInfo.announceForAccessibility`. Elapsed seconds and upload/transcription counts remain readable but do not repeatedly announce every five seconds.
- Errors use alert roles. The capture heading uses the header role. Provisional and unmatched live notes explicitly state that they await authoritative evidence or remain unverified.
- Explicit local-audio deletion uses a confirmation dialog, preserves uploaded notes/audio and requires finalized capture.

## Source review findings for web integration

Capture has explicit consent, native microphone labels, pause/resume/mark/stop names, recording state announcements and error alerts. Class view buttons use `aria-pressed`; cue buttons name their timestamp or reference; processing controls explain that they do not stop the microphone. PDF search and zoom controls have names, page count and search status are announced, the PDF scroll viewport is keyboard focusable, and citations have an extracted text fallback.

The parent integration implemented findings 1–5 below (status text, pane focus fallback, canvas hiding and reduced-motion scroll); DOM checks passed. Actual AT/theme review remains required:

1. Announce transcription status changes with a concise status live region. Avoid announcing the entire transcript on each update.
2. Expose caption-grounded provisional note status and authoritative replacement as concise status text without stealing focus.
3. Hide the duplicate PDF visual canvas from assistive technology when a selectable text layer is available; retain an honest extracted-text fallback for unavailable page text.
4. Honor `prefers-reduced-motion` for PDF smooth scrolling and any capture animation.
5. Return focus to the reference opener after closing a reference pane, or provide a stable reachable control when the opener disappears.
6. Verify visible focus indication, contrast and reflow in the active theme. Source labels alone cannot establish these results.

## Manual acceptance procedure

Record OS, browser/app build, AT version, theme, font/zoom level and pass/failure for every run. Complete setup using keyboard/AT; toggle consent; deny permission; retry and record; pause/resume; mark; stop; retry offline upload; navigate back to notes without restarting capture. Confirm recording state is announced once per transition and errors remain reachable.

Navigate Notes, Materials, Practice and Revision; open a citation; navigate PDF pages, zoom and search; close the pane and confirm focus location; inspect caption-grounded notes and their later authoritative replacement. Check that expired/unmatched evidence is labeled and that updates preserve the learner's reading position.

On iOS/Android, repeat with VoiceOver/TalkBack, large text, app background/foreground, phone call, revoked microphone permission, OS kill/restart, network loss and explicit sign out. Confirm Stop/logout releases microphone resources and restored capture never starts itself. Record OS battery/background restrictions rather than treating them as successful continuous recording.

## Operational acceptance runner

```powershell
python -m backend.scripts.in_class_acceptance --output work/in-class-acceptance.json
```

Default creates a fresh isolated SQLite database/evidence directory under `work` and makes no external calls. It never consumes the application `DATABASE_URL`. For PostgreSQL, explicitly set `OPENLEARN_ACCEPTANCE_DATABASE_URL` to a new empty database named `openlearn_acceptance_*`; an existing schema or differently named database is refused before migrations. Remote hosts additionally require `--allow-remote-test-db`. PostgreSQL was not exercised here. Evidence files and the isolated database remain available for inspection; they are synthetic and do not contain learner data.

The 5 October SQLite sample reported coordination run p50/p90 of 6.1/12.2 ms and end-to-end p50/p90 of 54.1/164.8 ms across five local coordination events. These measure deterministic local processing of two synthetic slices and 205 segments, not speech provider latency, long-class load, production capacity or device behavior.
