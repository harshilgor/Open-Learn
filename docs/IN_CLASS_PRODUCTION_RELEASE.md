# In-Class production release — 5 October 2026

Prepared from `origin/codex/free-render-backend` in an isolated checkout. Voice tutor modules, migration 0072 and UI/runtime integrations are excluded. The original development checkout is preserved. Existing production authentication, private object storage and free Render compute settings remain the deployment foundation.

Release includes In-Class and its required shared capture/material/job/reminder components, migrations through 0071, web workspace/branding updates, native client source and acceptance documentation. Shipping native source does not publish signed desktop/mobile binaries.

Validation: 36 focused backend tests passed; 19 web class/authentication/transport tests passed; isolated deterministic operational acceptance probe passed. Production deployment and post-release health checks are recorded below after release.

Provider requirement: class batch/live transcription requires configured OpenAI credentials. Live captions also require `OPENLEARN_CLASS_LIVE_TRANSCRIPTION_ENABLED`. These credentials are not included in Git. YouTube search remains optional behind its server key. Free Render can sleep; background completion while sleeping is not guaranteed.
