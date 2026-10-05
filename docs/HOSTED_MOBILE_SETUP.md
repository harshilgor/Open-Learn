# Hosted and phone setup

The milestone 7 code is available locally. No API deployment or signed phone release has been created. This guide turns the missing account choices into a concrete setup path.

## Proposed first deployment

Use the prepared Render API and three supervised workers, retain the existing web hosting, and reuse the configured PostgreSQL and private S3 services after disposable-account acceptance. The blueprint is `deploy/render.yaml`; select that path when creating a Blueprint. Render supports service and shared environment-group definitions in its [Blueprint format](https://render.com/docs/blueprint-spec). Service creation can incur charges; this repository does not provision accounts automatically.

Create an `openlearn-production` environment group from `deploy/hosted.env.example` and the applicable provider settings in `backend/.env.example`. Put backend credentials only in this group. Use the same database and private object buckets for all four services. API performs the single pre-deploy migration; workers require the current schema and do not race to migrate. Worker restart is controlled by the hosting supervisor. Validate configuration with `python -m backend.app.hosted_runtime check`; this checks shape, not connectivity.

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
