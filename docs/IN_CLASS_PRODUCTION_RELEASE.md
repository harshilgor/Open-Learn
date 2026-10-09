# In-Class production release — 5 October 2026

Prepared from `origin/codex/free-render-backend` in an isolated checkout. Voice tutor modules, migration 0072 and UI/runtime integrations are excluded. The original development checkout is preserved. Existing production authentication, private object storage and free Render compute settings remain the deployment foundation.

Release includes In-Class and its required shared capture/material/job/reminder components, migrations through 0071, web workspace/branding updates, native client source and acceptance documentation. Shipping native source does not publish signed desktop/mobile binaries.

Validation: 36 focused backend tests passed; 19 web class/authentication/transport tests passed; isolated deterministic operational acceptance probe passed. Production deployment and post-release health checks are recorded below after release.

Provider requirement: class batch transcription follows `AI_TUTOR_TRANSCRIPTION_PROVIDER` (or the selected text provider when set to `auto`) and requires that provider's server key plus a verified usage rate. OpenRouter Whisper and OpenAI transcription are supported. Live captions still require OpenAI credentials and `OPENLEARN_CLASS_LIVE_TRANSCRIPTION_ENABLED`. These credentials are not included in Git. YouTube search remains optional behind its server key. Free Render can sleep; background completion while sleeping is not guaranteed.

## Production deployment result

- Release commits: `b6f9dcd` (isolated feature) and `8b4ee93` (Linux optional dependency lock repair).
- Vercel production: https://open-learn-eta.vercel.app — READY, deployment `dpl_EgJDs93fwttFJ8YZvDV3k1JSSyoj`, running `8b4ee93`.
- Render API: https://openlearn-api-saku.onrender.com — Live, deployment `dep-db225uh7lnhs73db88vg`, running `b6f9dcd`. PostgreSQL migrations through 0071 completed.
- Post-release HTTP checks: web 200 with Open Learn title; bundled PDF worker 200; API readiness 200; PostgreSQL/schema health successful with no missing tables or indexes.
- Authenticated browser: existing conversation loads, sidebar search absent, In-Class setup opens, live caption availability correctly disabled.
- Production environment variable names were inspected without exposing values. OPENAI_API_KEY and OPENLEARN_CLASS_LIVE_TRANSCRIPTION_ENABLED are absent. Uploaded class audio therefore needs the configured OpenRouter transcription provider and a verified `OPENLEARN_OPENROUTER_STT_USD_PER_MINUTE` rate; live captions remain unavailable without OpenAI credentials and the live transcription flag.
- Real microphone/provider acceptance and signed native distribution remain unverified/unpublished. Deployment is complete; complete end-to-end feature acceptance is pending the provider configuration and recording test.
- Unfinished voice tutor stays in the original development checkout and is excluded from this release.
