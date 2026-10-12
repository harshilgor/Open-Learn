# Changelog

All notable changes are recorded here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses semantic version tags for published releases.

## [Unreleased]

### Added

- Generated visuals are runtime-verified before learners see them: a headless sandbox mounts each candidate exactly like the chat card at desktop and mobile widths, checks for errors, blank or empty renders, invalid readouts, clipped layouts and dead controls, and feeds specific findings back to the model for bounded repair.
- Conversational visual editing: follow-ups such as "add air resistance to this" revise the existing visual from its exact source, carry over saved control values, and record lineage ("Version 2") while leaving the earlier version untouched.
- Visual progress shows sandbox testing and repair attempts; generated visuals can be opened full screen.
- `backend/scripts/visual_benchmark.py`: a live generative-visual benchmark with task-specific scientific and interaction checks.

- Persistent chat history in the sidebar with time grouping, search, rename, delete, and per-learner isolation.
- Living study notes: each Learn chat owns a linked note; the tutor proposes concise sections (turns, side explorations, quiz checklists) with accept/edit/reject and tutor/user/shared ownership plus revision protection.
- Fullscreen Settings with General, API keys, Notifications, Data & privacy, and About; browser clients can save provider keys to the local service configuration.
- On-device usage analytics (tokens, generations, cost) with trend and top-session views.

- Learn workflow with Ask/Learn mode, teaching gears, resumable learner journeys, inline assessment, and a direct path into Quiz.
- Quiz workspace with generated question sets, answer evaluation, repair guidance, and evidence admission through the canonical learner-state service.
- Local privacy controls to export learner records as JSON or permanently remove locally stored learner data and imported materials.
- Desktop provider setup backed by the operating system credential store, a first-run setup screen, native workspace settings menu, and optional due-review notifications.
- Electron desktop packaging for a bundled web interface and FastAPI sidecar, per-user application-data directories, dynamic loopback ports, loopback-token protection, sidecar recovery, and GitHub Actions packaging workflows.
- Signed-beta release automation for Windows x64 and macOS Intel/Apple Silicon, with signing/notarization gates, release checksums, beta release notes, and an upgrade-validation runbook.

### Changed

- Visual generation limits are configurable (`OPENLEARN_VISUAL_MAX_OUTPUT_TOKENS`, default 16000; `OPENLEARN_VISUAL_DEADLINE_SECONDS`, default 600; `OPENLEARN_VISUAL_MAX_ATTEMPTS`, default 3; `OPENLEARN_VISUAL_MAX_INPUT_BYTES`, default 160000).
- Turns where no visual is useful end without a visual-model call.

### Fixed

- Visual code validation crashed on Windows for any visual containing non-ASCII text (Greek letters, arrows, emoji).
- Valid visuals that create elements in JavaScript were rejected as missing DOM targets.
- `(await import('three')).default`, `d3` defaults and the `three/examples/jsm` OrbitControls path now resolve in visual frames.

- Updated the repository README and installation guide around the local desktop beta and GitHub Releases distribution.

### Known limitations

- `v0.1.0-beta` is publishable only after the repository signing and notarization secrets are configured; no public installer exists until that release workflow passes.
- Silent Squirrel uninstall needs final verification through a normal interactive Windows installation; learner data is intentionally preserved across uninstall/reinstall.
- Hosted accounts, synchronization, automatic updates, calibrated mastery, and retrieval-backed source verification are not included.
