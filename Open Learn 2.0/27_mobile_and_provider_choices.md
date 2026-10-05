# Phone experience and recommended provider stack

Design discussion updated 3 October 2026. The [research-backed agent architecture](26_agent_execution_platform.md) now governs integration details and supersedes earlier provider assumptions where noted. User direction: a message-first phone interface inspired by iMessage and Grok-style bot interactions, with audio recording from the phone. Daytona is the user's preferred sandbox candidate. Recommendations below are proposals for discussion, not completed integrations or purchased services.

## Phone product direction

Open on a conversation list and return to the last chat. The main conversation uses readable message bubbles, a keyboard-aware composer, an attachment button, a microphone, and streaming replies. Ask, Learn, and Quiz are available within the conversation, with clear teaching/quiz interactions and retained workflow context. A compact task card shows progress and offers Stop, approval, Resume, sources, and output files. Long explanations and quizzes can expand beyond a bubble rather than compressing every interaction into tiny messages.

Secondary destinations are Courses, Recordings, Files, and Tasks. Keep them available from conversation navigation; avoid making a dashboard the mandatory entry screen. This is an interface within the Open Learn native app; actual Apple Messages integration would be a separate scope and distribution decision.

Two microphone intents need distinct controls:

- Voice message: a short spoken prompt, review/playback before sending, transcript correction, and cancellation.
- Record lecture: course selection, persistent elapsed timer and recording indicator, Pause/Stop, explicit local-save/upload state, recovery after interruption, and access to transcript, audio, notes, and follow-up questions.

Recording persists on the device before upload. The native app keeps an upload manifest with recording ID, sequence, timing, checksum, and acknowledgement, reusing the existing lecture API's idempotent chunk/finalization contract. Do not assume a single recording file, native background recording, and independently playable short chunks are interchangeable. Prototype uninterrupted segmentation; use a native capture module if the chosen Expo API cannot produce recoverable chunks without gaps. Handle calls, Bluetooth disconnection, microphone denial, low storage, offline capture, app termination, and missing intervals visibly.

Expo documents background recording configuration, but support must pass real iOS/Android lock-screen and interruption tests in native builds. Record to the documents directory, not disposable cache. Transcription happens on the backend; audio capture does not require a transcription vendor account on the phone. Save the raw audio independently from transcripts and generated notes.

## Recommended products and API boundaries

| Capability | Recommendation | API/SDK and integration decision |
| --- | --- | --- |
| Phone application | React Native + Expo, Expo Router, EAS builds | Native client of the existing owner-scoped backend API; custom conversation UI, without a separate commercial chat backend |
| Phone recording | expo-audio + expo-file-system, with native capture fallback after prototype | Native microphone and durable file APIs; reuse lecture recording creation, chunk PUT, status, finalize, and playback routes |
| Transcription | Existing OpenAI transcription adapter initially | Audio Transcriptions endpoint; evaluate gpt-4o-mini-transcribe for ordinary audio, gpt-4o-transcribe for harder lectures, and diarization only when speaker labels are needed; benchmark actual course recordings |
| Reasoning models | Existing provider adapter | Keep model selection configurable; evaluate reasoning, tool use, lecture math, latency, and cost before choosing one default |
| Agent orchestration | Extend the Python kernel and existing durable jobs | Typed tools, checkpoints, permissions, sources, budgets; defer a LangGraph migration until a concrete gap justifies it |
| Code sandbox | Daytona as preferred initial candidate | Python daytona SDK behind SandboxService; task-scoped allocation, deadlines, private sessions, controlled networking, output collection, and deletion |
| Research | Reuse the existing Exa-backed WebEvidenceService first | Preserve its provider interface, tool policies, quotas and citation mapping; benchmark a Tavily adapter only against a demonstrated gap |
| Cloud browser | Browserbase + Playwright | Session/CDP and live-view APIs behind BrowserService; DOM first, visual fallback, authenticated takeover; test mobile keyboard interaction before committing |
| Course ingestion | Existing local Canvas reader | Preserve narrower read-only grants and academic reconciliation; cloud browsers do not replace this boundary automatically |
| Hosted durable workflows | Existing job/outbox system first; Temporal for the full durable-agent track | Python Temporal SDK and external workers when long waits/recovery justify the extra system; migrate through WorkflowService |
| Database/account infrastructure | Supabase PostgreSQL, with Auth as a candidate | Keep SQLAlchemy/migrations and reconcile existing verified identity/device sync; adopting Supabase must not create a second owner ID system |
| Audio and generated files | Supabase Storage if adopting Supabase | Private object storage with backend ownership checks; retain local filesystem adapter; compare S3-compatible storage against the existing object-store implementation |
| Connected apps | Direct Google APIs first; Composio for breadth | Google Drive/Gmail/Calendar OAuth with explicit scopes; provider connections behind ConnectedAppService; preview/approve writes |
| Notifications | expo-notifications + Expo Push | Backend sends task/approval notifications; handle receipts, invalid devices, preferences, deduplication and deep links |
| Tracing | Langfuse | Python instrumentation with task/tool/cost traces and strict secret/source redaction |
| Web hosting | Vercel | Deploy the web frontend using a verified Next.js build configuration; supply a hosted API origin for functional hosted workflows |
| Python API and workers | Render as the first hosting candidate | API service plus a supervised background worker sharing PostgreSQL and durable objects; evaluate requirements before provisioning |

This avoids adding a paid service for message bubbles, phone recording, or every individual tool. No provider credential belongs in the mobile app or browser bundle. A supplied Daytona key is a backend secret, not a NEXT_PUBLIC variable. The optional SDK requirements and smoke script do not expose an agent route or implement the complete sandbox service.

## Decisions to settle next

1. Message navigation and whether one default chat or course-scoped conversations is the primary entry.
2. First mobile delivery: short voice messages plus reliable lecture recording, or all task/takeover features at once.
3. Native recording segmentation, audio format, offline retention, upload policy, and supported device matrix.
4. Hosted identity, database, object storage, API, and worker provisioning before inviting real students.
5. Daytona region/runtime/network policy, per-task spend envelope, artifact persistence, and acceptance workloads.
6. Provider comparison using real lecture audio, research tasks, mobile takeover, and crash recovery.

## Official references checked for this discussion

- [Daytona Python SDK](https://www.daytona.io/docs/en/python-sdk/sync/daytona/) and [sandbox lifecycle](https://www.daytona.io/docs/en/sandboxes/).
- [Expo audio](https://docs.expo.dev/versions/latest/sdk/audio/), [filesystem](https://docs.expo.dev/versions/latest/sdk/filesystem/), and [push notifications](https://docs.expo.dev/push-notifications/overview/).
- [OpenAI transcription](https://developers.openai.com/api/docs/guides/speech-to-text).
- [Tavily search](https://docs.tavily.com/documentation/api-reference/endpoint/search).
- [Browserbase live view](https://docs.browserbase.com/platform/browser/observability/session-live-view).
- [Temporal Python API](https://python.temporal.io/).
- [Supabase](https://supabase.com/docs), [Render workers](https://render.com/docs/background-workers), [Composio](https://docs.composio.dev/docs), and [Langfuse](https://langfuse.com/docs).

Provider prices and quotas are intentionally unselected; compare current plans after expected usage is established.
