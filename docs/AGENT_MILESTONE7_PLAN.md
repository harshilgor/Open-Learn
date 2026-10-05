# Milestone 7 build plan

Source: `Open Learn 2.0/26_agent_execution_platform.md`, milestone 7 and sections 10–11, 16–20. Milestone 6 is being implemented in a separate chat; preserve its contracts and changes.

1. Build a message-first Expo application using the existing verified OIDC owner, FastAPI and task/lecture services. Generate mobile API schema types from backend OpenAPI. Store account credentials in SecureStore and scope durable queues and files by verified owner.
2. Support conversation/course selection, persistent message retries, reconnect snapshots, task/input controls, source and artifact review, learning continuation, reviewed connected actions, notifications and browser takeover. Clear visible account data on logout/account changes.
3. Implement native durable lecture capture as a local Expo module: independently playable WAV segments below the existing 4 MB limit, documents-directory files, native segment journals, explicit gaps/interruption recovery, repeated same recording/sequence/checksum uploads, finalize only after acknowledgment. Add short voice review/transcription without merging microphone intents.
4. Integrate optional Expo permission/token registration and cold/warm deep links; private authenticated downloads. Preserve local-dependent task waiting states.
5. Add Docker/Render API, learning/lecture worker, agent worker and browser worker definitions sharing PostgreSQL and private S3. Validate hosted configuration, health and worker supervision; single migration release command. Retain local profiles, without changing orchestration frameworks.
6. Verify mobile protocol/retry/account isolation and backend integration, Expo TypeScript/bundle and existing relevant regressions. Document exact commands and gates. Hosting, OIDC app registrations, EAS/signing identifiers, physical iOS/Android recording/push/takeover tests and live PostgreSQL/S3 evidence are release inputs; do not call a scaffold or simulator a released native application.

End-to-end story: a phone user signs in, starts hosted work, closes the app, returns to an authoritative task snapshot and private files, and captures/uploads a lecture with recoverable local segments. Workers own execution while the phone is absent.
