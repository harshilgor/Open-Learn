# Talk to Buddy provider setup and release

Updated 5 October 2026. Provider setup is complete. LiveKit Cloud project `OpenLearn` (`p_2i4h00eoq1h`) has a running production worker named `openlearn-voice` (`CA_j6BxK5go2DKr`) in `us-east`. Deepgram and ElevenLabs credentials are stored in LiveKit agent secrets and Render's `openlearn-api` environment; the dedicated LiveKit backend key is stored in Render. The Render environment values were saved without triggering a deployment. Its current production commit (`b6f9dcd`) does not contain the voice routes or voice migrations, so keep `OPENLEARN_VOICE_ENABLED=false` until the voice backend release and acceptance checks are complete.

## Services and secret locations

| Service | Secret/configuration | Where it belongs |
| --- | --- | --- |
| OpenRouter | Existing server key; model stays `openrouter/free` | Render `openlearn-api` only |
| Supabase | Existing production `DATABASE_URL` | Render `openlearn-api` only |
| LiveKit Cloud | Project URL, API key, API secret | Render `openlearn-api`; Cloud injects its own values into the agent container |
| Deepgram | API key | Render `openlearn-api` and LiveKit agent secrets |
| ElevenLabs | API key, selected voice ID, pinned model | Render `openlearn-api` and LiveKit agent secrets |
| Open Learn backend | Public HTTPS origin | LiveKit agent secrets as `OPENLEARN_API_URL` |

The browser receives only a short-lived, room-scoped LiveKit token. It never receives the LiveKit API secret, provider keys, OpenRouter key, or agent capability. Store secrets in Render or LiveKit Cloud; do not paste them into chat or commit them.

## Provisioned accounts and current costs

| Provider | Provisioning status |
| --- | --- |
| LiveKit Cloud | Project `OpenLearn`, URL `wss://openlearn-mv9dsu3o.livekit.cloud`; dedicated service key `Open Learn Backend (Render)` is in Render. Production agent `openlearn-voice` (`CA_j6BxK5go2DKr`) is running in `us-east`. The dashboard showed the Build plan and `$0.00` next invoice when checked. |
| Deepgram | Final key `Open Learn Voice Agent 2026-10 rotation 2`, default project role, created for Flux STT, expires 3 January 2027. The console showed $200 in trial credit when checked. |
| ElevenLabs | Key `Open Learn Voice Agent`, restricted to Text-to-Speech; voice `Adam` (`pNInz6obpgDQGcFmaJgB`), model `eleven_flash_v2_5`. The console showed the Free plan and 10,000 credits when checked. |
| OpenRouter | Existing key remains server-side in Render; model remains `openrouter/free`. The worker calls the Open Learn backend and does not call OpenRouter directly. |

These are account snapshots, not a promise that future usage will remain free. Check each provider's live usage and pricing before inviting learners. Speech generation and transcription can consume provider credits as soon as real sessions run. [LiveKit pricing](https://livekit.io/pricing), [Deepgram pricing](https://deepgram.com/pricing), [ElevenLabs pricing](https://elevenlabs.io/pricing/api)

Rotation note: the first Deepgram key and its first replacement were revoked after their one-time values appeared in dashboard accessibility snapshots. A final replacement was created and saved only in Render and LiveKit secrets. The first LiveKit backend key was also revoked after a one-time dashboard value appeared in a snapshot; its replacement is the key currently stored in Render.

## Configure the backend

In Render → `openlearn-api` → Environment, confirm or add the following. Save the real values directly in Render's secret fields.

```text
OPENLEARN_VOICE_ENABLED=false
OPENROUTER_MODEL=openrouter/free
LIVEKIT_URL=wss://YOUR_PROJECT.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
ELEVENLABS_MODEL=eleven_flash_v2_5
```

The provider credentials are saved in Render. At the time of this release candidate, the deployed service is still on commit `b6f9dcd`; this commit must be merged and deployed before the voice endpoints and migrations `0072_voice.py` through `0077_usage_estimate_references.py` are available. Keep `OPENLEARN_VOICE_ENABLED=false` until the backend migration and real provider/browser acceptance checks pass. Keep the existing Supabase `DATABASE_URL` and OpenRouter key in Render. The backend calls `openrouter/free` directly; the voice worker does not call OpenRouter itself. Keep the public API HTTPS and its execution worker available throughout a session. Render's sleeping free web service is not a dependable live voice API.

## Create and deploy the LiveKit agent

Install the LiveKit CLI, authenticate, and select the same Cloud project:

```powershell
winget install LiveKit.LiveKitCLI
lk cloud auth
lk project list
lk project set-default "YOUR PROJECT NAME"
Set-Location .\voice-agent
```

The production agent secrets are configured in LiveKit Cloud; do not create a local file with production credentials. For local development only, use separate test keys in an ignored `.env.local` file.

The existing worker was deployed from `voice-agent/`. The CLI created the agent record; after fixing the base-image `voice` group collision in `Dockerfile`, the corrected image was deployed to that same agent ID. `livekit.toml` records its ID for subsequent deployments:

```powershell
lk agent deploy --region us-east .
lk agent status
lk agent logs
```

The agent dispatch name is `openlearn-voice`; keep it aligned with both the decorator in `voice-agent/agent.py` and the backend dispatch call. The initial `create` reserves the project's agent slot, so update/deploy this agent rather than creating a second one. LiveKit CLI templates use `lk agent init`; this repository already has a custom worker, so no disconnected starter project was created. [LiveKit CLI](https://docs.livekit.io/reference/developer-tools/livekit-cli/agent/)

## Acceptance before enabling learners

Use an authenticated test account and a real browser with microphone permission. The `/dev/voice-fixtures` page is a visual-only development fixture and does not validate providers.

1. Confirm `/v1/voice/capabilities` is disabled before setup and returns enabled only after all backend credentials exist and the flag is deliberately changed.
2. Start a call, reject microphone permission, and confirm typing remains available. Then allow permission and confirm the dock shows live captions and spoken responses.
3. Disconnect the browser network briefly, reconnect within 60 seconds, and verify the session resumes muted; explicitly unmute to continue. A longer outage should end cleanly.
4. Ask Buddy to explain a concept from the current course, create and take a quiz, request a diagram, save a lesson note, list reminders, and create a reminder. Confirm each artifact appears in the existing workspace and its receipt reflects the saved result.
5. Say “tomorrow at 7” and confirm Buddy asks AM/PM instead of guessing. Cancel a pending reminder and verify the confirmation names the reminder/time or says that all future recurring occurrences will be cancelled.
6. Interrupt speech, mute/unmute, switch microphone, use hold-to-talk, end the call, and check that the session settles usage and stops the LiveKit room. Verify account export removes the internal agent capability and account deletion cascades through voice rows.
7. Verify browser refresh/reopen behavior, mobile Safari/Chrome, keyboard/screen-reader controls, server restart/replay, worker failure, usage caps, and the backend kill switch. Measure connection and first-audio latency with the actual accounts; a local fixture or mocked provider is not evidence of production acceptance.

Only after these checks pass should `OPENLEARN_VOICE_ENABLED` be set to `true` in Render. Setting it back to `false` blocks new sessions and causes connected agents to end on their next poll. Keep OpenRouter routed to `openrouter/free` throughout.
