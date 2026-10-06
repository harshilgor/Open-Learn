# Open Learn Desktop

This is the desktop shell for the Open Learn web interface and FastAPI learning service. It starts the local API sidecar, serves the built web UI through a loopback server, and runs the renderer with Electron isolation enabled.

## Development

From the repository root, start the web interface first:

```powershell
./start-local.ps1
```

Then, from `desktop/`, install the desktop dependencies and run:

```powershell
npm install
npm run dev
```

The shell uses the existing API on `127.0.0.1:8000` and opens the web interface on `127.0.0.1:3000`. Set `FORMA_WEB_URL` or `FORMA_API_PORT` when using different local ports.

GitHub Actions builds unsigned Windows and macOS artifacts for pull requests. The `v0.1.0-beta` release workflow builds signed Windows x64, macOS Intel, and macOS Apple Silicon artifacts only after all signing and notarization secrets are available. See [the release runbook](../docs/RELEASING.md) before creating that tag.

To build the sidecar locally after installing the backend requirements:

```powershell
python -m pip install -r ../backend/requirements.txt
npm run build:backend
```

The generated `backend/dist/forma-api/` directory is platform-specific and must be built on the target operating system. GitHub Actions performs this matrix build for releases.

Validate the bundled Windows sidecar against a fresh application-data directory, then restart it against the same directory:

```powershell
./scripts/smoke-local-runtime.ps1
```

The smoke test deliberately keeps the installation directory and application-data directory separate. An uninstall is expected to remove the application while preserving learner data for a later reinstall; users can delete that data from **Your workspace**.

The desktop sidebar's **Your workspace** panel configures provider keys through the OS credential store and exposes local data export/deletion. The application menu includes the same local-data settings entry.

## In-Class capture lifecycle

Capture starts only after recording consent and a user microphone/source selection. Pause finishes the current slice and releases microphone, loopback, mixer and screen wake lock. Resume requests sources again from the user's click and keeps the same chunk manifest. Explicit Stop and account changes release capture; upload recovery uses saved slices and never opens a microphone.

While capture is recording, paused or saving, closing the window keeps it in the tray when the native tray is available. Minimize continues capture. The tray offers Open and Stop and save. When capture finishes, the tray is removed. If tray creation is unavailable, closing exits normally, leaving the persisted manifest for recovery.

OS lock and suspend request Stop and save and release the display blocker. Resume reports the interruption and does not start capture. OS wake is unsupported: display-sleep prevention cannot wake a sleeping system. Quit waits for capture's saved-manifest acknowledgement for up to three seconds before exiting; shutdown/crash may interrupt the final slice, and the saved manifest is recovered on restart. No notification permission is requested for this flow.

Local lifecycle tests: `node tests/class-lifecycle.test.cjs` from `desktop`; capture release/resume tests: `node tests/lecture-capture.test.mjs` from `web`. These tests run directly because the Windows Node test runner's subprocess isolation may return `spawn EPERM`.

Packaged Windows acceptance remains required on supported OS versions: microphone/loopback indicators after Pause, Stop, logout and quit; minimize and tray; lock; sleep/wake; offline upload; forced termination and reopen. Electron power events are advisory during OS shutdown; no claim of final-slice survival or capture across sleep is made. No packaged executable or native device acceptance was exercised in this implementation environment.
