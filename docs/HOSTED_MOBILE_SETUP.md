# Hosted and phone setup

The first hosting target is a **free Render API with Supabase PostgreSQL**, while development continues. The API is configured on Render and hosted web authentication uses Supabase email links. Signed phone releases remain separate. Paid compute is deferred until the owner chooses to upgrade.

## Free development deployment

Use `deploy/render.yaml`: it defines only `openlearn-api`, explicitly on `plan: free`, with no paid workers, database, disk, or pre-deploy command. The command `python -m backend.app.hosted_runtime api-free` completes migrations under a PostgreSQL advisory lock before starting one Uvicorn process. `OPENLEARN_MIGRATE_ON_START=false` prevents Store instances from independently migrating. Set `OPENLEARN_WORKER_MODE=embedded`; the API runs its existing learning worker while awake.

Keep `AI_TUTOR_PROVIDER=openrouter` and `OPENROUTER_MODEL=openrouter/free`. The free Blueprint pins both values. Supply the existing private OpenRouter key only in Render's environment group. Remote sandbox execution, browser assistant execution, and general agent admission are disabled in this profile. They can be enabled after provider setup and cost review.

Render sleeps a free service after 15 minutes without inbound traffic; the next request wakes it. Jobs cannot reliably finish while the service sleeps. Its local filesystem is ephemeral, so retain the hosted PostgreSQL and private object-storage requirements. Free instance hours are shared with existing free services in the workspace, including InsiderInfo. See [Render free-service limits](https://render.com/docs/free). Do not add a payment method or upgrade compute as part of this setup.

Create an `openlearn-production` environment group from `deploy/hosted.env.example` and the applicable provider settings in `backend/.env.example`. Supply production identity, database, object-storage, and provider credentials there. Never copy the whole local `.env` into production. The free service's embedded-worker and provider settings override the shared group. Validate shape with `python -m backend.app.hosted_runtime check`; this does not prove connectivity.

## Supabase PostgreSQL

Create a dedicated **Open Learn** project on a free plan. Use the exact session-pooler URI (port 5432) from its Connect dialog. Replace its scheme with `postgresql+psycopg`, percent-encode reserved characters in the password, and require TLS with `sslmode=require`. Store the resulting `DATABASE_URL` only in Render's environment group. Do not use the transaction pooler for this bootstrap profile. See [Supabase connection guidance](https://supabase.com/docs/guides/database/connecting-to-postgres).

Disable the Supabase Data API and automatic exposure of new tables for this backend-only database; Open Learn serves its data through the authenticated Python API. Supabase database selection alone does not configure the existing native OIDC flow or private S3 storage. Configure those separately; do not weaken authentication or use ephemeral local files to bypass missing setup.

## Hosted account configuration - 4 October 2026

Render uses **Harshil's workspace** (`tea-d4j0f6h5pdvs7386n2r0`), service **openlearn-api** (`srv-db1jh5c9v7es73fseqv0`), Free Docker compute in Oregon. API URL: `https://openlearn-api-saku.onrender.com`. Its deployment branch is `codex/free-render-backend`; auto-deploy is off. InsiderInfo is unrelated and was left untouched.

Supabase **Open Learn** (`apxwjejimdzcvyosejzy`) is a dedicated Free project in US East. The owner authorized pausing **our dates** to free a project slot. Data API is disabled. Private storage bucket `openlearn-private` uses the Supabase S3 endpoint, with its approved server credentials stored only in Render. The database password is percent-encoded within Render's `DATABASE_URL`.

The production web origin is `https://open-learn-eta.vercel.app`. Vercel production has `NEXT_PUBLIC_LEARNING_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, and the browser-safe `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`. Supabase Site URL is that origin and the exact redirect allow-list entry is `/auth/callback`. Web sign-in supports Google OAuth and email links with PKCE; tokens are verified by the backend against Supabase's issuer, authenticated audience, and public JWKS. Native mobile OIDC configuration still requires its own provider/client integration.

The organization reports existing storage over its free quota and a potential restriction date of 27 October 2026. Resolve unrelated storage usage before then without automatically upgrading or deleting data. Supabase's default email sender is suitable for initial project-team testing; configure a sender before broad public sign-up.

## Live verification

Render deployment `06c50af` completed successfully. `/ready` returned HTTP 200 with `status=ready`; `/health` reported PostgreSQL/schema checks passing and `lesson_provider=openrouter/openrouter/free`. An unauthenticated `/v1/account` returned 401, CORS allowed the production web origin, and Supabase JWKS advertised ES256. Vercel production deployment `dpl_4qDLwD5WW3tH5ynpZLLdGFsp2zVJ` is READY and serves `/auth/sign-in`. Seven backend migration/runtime tests passed; five web account tests passed before deployment. A post-deployment Vercel error-log scan found no entries.

Google OAuth completed successfully in Chrome and the hosted account and Buddy loaded. Repeated same-account Supabase sign-in/refresh notifications are deduplicated to keep the UI stable. Seven web authentication/transport tests pass. A live authenticated tutor request completed through openrouter/free after typing nullable PostgreSQL course filters. Conversation history loaded from the hosted account. The context regression suite passed 23 tests. Private upload/download and cross-owner isolation still require live acceptance. Health checks prove configuration and database readiness, not a completed AI request or storage write. Free service sleeping and native phone acceptance remain subject to the limits above.

## Deploy and verify

1. Resolve the Supabase free-project slot, create Open Learn, and supply its session-pooler database URL through Render secrets.
2. Supply private object-storage credentials, OIDC issuer/audience/JWKS, and the web origin in `openlearn-production`.
3. Publish the free Blueprint and bootstrap runtime to the Git repository. Apply `deploy/render.yaml` only after the review shows one **Free** web service and zero paid resources.
4. Check migration/startup logs, `/ready`, authenticated owner isolation, an OpenRouter free-model lesson, and embedded learning work.
5. Verify wake-up, restart recovery, PostgreSQL persistence and private object storage with disposable accounts before connecting signed mobile builds.

## Later paid deployment

`deploy/render-paid.yaml` preserves the proposed API plus three supervised workers for a later explicit upgrade. Use external worker mode then, let only the API pre-deploy step migrate, and verify all workers share the same PostgreSQL and object storage. Do not apply the paid Blueprint now. Closed-app completion and always-on background acceptance remain deferred until this upgrade and live verification.

Use an OIDC provider supporting native public clients, authorization code with PKCE, refresh tokens, API audience and JWT verification. Reuse the existing provider if possible. Register a separate native public client, without a client secret, and the exact redirect produced by `AuthSession.makeRedirectUri({scheme:'openlearn',path:'auth'})` in the signed build (normally `openlearn://auth`). Register the HTTPS web origin separately. Backend needs issuer, JWKS URL and API audience; mobile needs issuer, public client ID and that audience. Never put client secrets or database/S3 keys into `EXPO_PUBLIC_*`.

Create one Expo project under the account that will own the application. Set its UUID plus final Android package and iOS bundle ID in `mobile/.env`; replace the development identifiers before signing. EAS can create installable Android/iOS binaries and manage signing credentials; see [EAS Build](https://docs.expo.dev/build/introduction/). The custom capture module requires a development or standalone native build; Expo Go cannot load it.

From `mobile/`, after configuration:

```powershell
npm ci
npm run check:release
npx eas-cli login
npx eas-cli build --profile development --platform android
npx eas-cli build --profile development --platform ios
```

The first builds are for physical-device acceptance. Production builds and store submission follow acceptance, with developer-account signing and distribution choices supplied by the owner. None of these account or signing steps has been performed here.

## Acceptance evidence required before release

| Check | Evidence to retain |
| --- | --- |
| Hosted database | Disposable owner migration, concurrent API/worker leases, restart recovery, revision conflicts and isolation on PostgreSQL |
| Private S3 | API uploads material/lecture/artifact; another worker reads it; authenticated download, account export and deletion succeed; anonymous read denied |
| Closed-app work | Phone starts research/analysis, app closes, worker completes, reopen shows verified authoritative results and downloadable files |
| Native capture on each OS | Long lecture, lock/background, pause/resume, calls/interruption, process kill, restart recovery, low storage and offline upload; no fabricated continuity |
| Upload retries | Disconnect after acknowledgment, retry same IDs/hash, verify no duplicate transcript or premature finalize |
| Account switch | Queues/audio/files never dispatch or display under another owner; token reassignment and sign-out unlink prevent previous-owner notifications |
| Notifications | Permission refusal, ticket/receipt/revocation, quiet hours, cold and repeated warm links on signed devices |
| Browser | Cloud takeover, return control, expiration and reconnect; paired local tasks remain waiting without their desktop |
| Learning/actions | Lesson and quiz lifecycle plus full mail/calendar review, stale approval rejection and uncertain-outcome handling |

Legacy pre-segment lecture recordings using old local-file storage need migration or a supported local profile. The segmented lecture and material paths use shared object storage. A successful JavaScript export does not establish native compilation, background microphone behavior or store readiness.
