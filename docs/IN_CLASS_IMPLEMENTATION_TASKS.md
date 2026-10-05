# In-Class implementation tasks

Source: [In-Class architecture](IN_CLASS_MODE_ARCHITECTURE.md) and the Buddy behavior/recovery contract.
Implementation details and acceptance limits: [IN_CLASS_IMPLEMENTATION.md](IN_CLASS_IMPLEMENTATION.md).

- [x] Owner-scoped class envelope linked to recording, Buddy, course and one stable conversation.
- [x] Explicit setup/consent/start, microphone/material selection and output preferences; retryable local manifest.
- [x] Atomic transcript/finalization/correction handoffs into the existing agent worker.
- [x] Contiguous coverage, bounded settled windows with prior context, deduplicated leased work and revision/attempt fences.
- [x] Source-backed live notes, authorized supporting passages and prepared QuizService continuation.
- [x] One private class draft deck, summary and active recall with independent readiness and retry.
- [x] Snapshot/cursor feed; class canvas with transcript evidence, sources, practice and revision package.
- [x] Persistent recording/level controls, immediate Stop, owner-safe offline/recovery behavior.
- [x] Export/import/delete integration and correction preservation of authored notes and quiz answers.
- [x] Ownership, HTTP device fence, retry, correction, duplicate/gap/lease/failure/partial tests; frontend/type checks.
- [x] Desktop/mobile browser verification with a labelled sample class and prepared quiz.
- [ ] Hosted PostgreSQL locking and simultaneous-device acceptance with the configured hosting environment.
- [ ] Long real-microphone recordings, tab termination, storage pressure, source indexing quality and provider latency measurements.
- [ ] Native background/lock-screen capture through a separately validated platform adapter.

The last three items require external environments/devices. The web implementation deliberately does not promise native background capture or a hosted synchronization service before these are configured.
