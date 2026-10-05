# Milestone 7 implementation record

Date: 2026-10-04. Source: [general-purpose agent execution and learner integration](../Open%20Learn%202.0/26_agent_execution_platform.md). [Build plan](AGENT_MILESTONE7_PLAN.md). Status: local implementation and verification; hosted and signed-device acceptance pending. Milestone 7's release acceptance is not complete.

## Implemented

`mobile/` is a locked Expo SDK 57 React Native application with generated backend schema types, external-browser OIDC PKCE, SecureStore credentials, verified backend owner identity and account-fenced requests. Durable SQLite journals retain pending messages, revisions, attachments and recording identities. Reconnect reads server snapshots. Conflicts remain reviewable rather than silently rebasing intent.

The native chat supports course/conversation selection, Ask/Learn, research, CSV analysis using attached material, task clarification and pause/resume/stop, source inspection, authenticated files, explanations and quiz continuation. Connected actions show the full reviewed mail/event payload, attachments and previous event, and submit the server revision/hash. Cloud takeover is generation-scoped and expires; paired local browser work requires its desktop. Inbox supports responsibility controls and optional Expo notifications with generic lock-screen content and authenticated cold/warm conversation links.

Android foreground AudioRecord and iOS AVAudioEngine capture implementations write independently playable 30-second WAV segments, durable native journals and recoverable active files. Phone documents and queues are owner-scoped. Recovery exposes interruptions; pause/resume and stopped upload are separate. The upload protocol preserves recording ID, sequence and checksum, checks acknowledgment and missing segments, and finalizes only sealed acknowledged recordings. The lecture view exposes processing state, transcript, timestamped notes and authenticated audio. Short voice clips are separately reviewed, transcribed through bounded idempotent backend receipts, corrected and explicitly sent. A provider request with unknown outcome is retained instead of blindly charged again.

`deploy/` supplies an API plus learning/lecture, agent and browser worker image/Render definitions. Hosted configuration rejects local identity, SQLite and local object storage. A single migration command precedes release; other processes require the current schema. `/ready` verifies database/schema readiness. Signal handling and worker leases use existing orchestration. No new orchestration platform was added.

Material content, CSV sandbox input, lecture audio, account material export/import/deletion and browser evidence use configured shared object storage. Hosted notes reconstruct local read caches from durable PostgreSQL content; hosted edits lock and check revisions, and local-cache reindexing cannot erase shared rows. Push token reassignment revokes earlier owner registrations. Mobile voice receipts participate in owner deletion/export and are excluded from identity import.

## Verification

- Mobile protocol: nine cases passed, covering lost acknowledgments, stable retries, mutated/oversized audio, missing segments, premature finalize, owner isolation, revision conflicts and safe links.
- TypeScript passed and both Android/iOS Hermes JavaScript exports succeeded after final fixes.
- Android prebuild and Expo autolinking discover the custom capture module. These checks do not compile Kotlin/Swift or prove background capture.
- Focused backend run: 42 passed, one skipped, one failed across mobile release, materials, workspace notes and lecture pipeline. The remaining material fixture's graph lacked its authenticated owner's resource registration; after correcting that fixture, its targeted rerun passed. Together these establish 43 passing cases and one skip, rather than a claim that the original full invocation was green. Earlier fixtures also lacked IdentityMiddleware; they now mount the existing middleware with their store, including the secondary provider application. Production authentication was not relaxed. Logs: `work/m7-merged-results.txt` and `work/m7-owned-provider-results.txt`.
- Migration upgrade/downgrade roundtrip: one case passed (`work/m7-roundtrip-results.txt`). Concurrent worker compatibility and flashcard branches were joined by the additive `0051_mobile_flashcards_merge` migration, preserving both schemas.
- API schemas regenerated from the current composed OpenAPI using a disposable database; concurrent additive migrations are preserved.

## Release gates and limits

No services were provisioned, deployed or signed. Java/Android device tools and an active Docker daemon were unavailable in this environment; Swift compilation and physical devices were unavailable. Native capture source therefore remains subject to compilation and device acceptance, including interruption, lock/background, crash recovery, storage exhaustion and long recording. Expo Go cannot run the custom module.

The actual hosted PostgreSQL/S3 multi-worker acceptance, paid-provider live journey, OIDC native registration, EAS ownership, package/bundle identifiers, signing, push receipts and phone takeover journey remain required. Legacy non-segment local-file lecture recordings need migration or the supported local profile. The first release supplies existing task learning continuation; it does not add a separate realtime voice tutor. Material creation lacks an idempotent backend receipt, so losing that creation response can leave an orphan material even though subsequent content upload is immutable. Store submission and phone-only end-to-end release acceptance are pending.

Use [the concrete setup and acceptance guide](HOSTED_MOBILE_SETUP.md) to complete the outstanding account choices and retain release evidence. No credential values are included here.
