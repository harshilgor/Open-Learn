# Product connectivity and responsive UI repair

## Cause of the blocked hosted chat

The Vercel web app used `http://127.0.0.1:8000` whenever a public API URL was missing. That URL addresses the visitor's computer. Buddy loading then failed, and the composer combined missing Buddy state with its busy flag, disabling the textarea. Error text always prescribed starting the local developer API. The Today panel and chat also competed for the fixed viewport, pushing the composer off short screens.

## Delivered changes

- Public web uses same-origin `/v1` routes by default. A server-only `OPENLEARN_API_ORIGIN` supplies the actual HTTPS Python API origin. An optional direct `NEXT_PUBLIC_LEARNING_API_URL` remains supported. A hosted site rejects accidental HTTP loopback configuration.
- The proxy streams responses and request bodies, forwards learner bearer authentication and selected transport headers, excludes developer/desktop identity headers, rejects unsafe paths/redirects, and prevents caching of account data. Account verification and offline queues accept same-origin relative URLs.
- Draft typing stays enabled during outages and active generation. Sending remains disabled until a study partner is available; retry is explicit. Pending connection drafts survive reload/reconnection and are cleared on account changes. No fake Buddy or fabricated response is inserted.
- The header displays a compact connection status. Detailed connection notices appear beside the composer/history without prescribing local startup to public users.
- AI settings show included service status. They contain no key entry, provider account setup or billable connection-test button. Production key writes/deletes/tests are rejected. Local key tooling requires explicit development opt-in and cannot be enabled in production.
- The existing private backend OpenRouter configuration is selected and its server-side connection check passed. No provider key was copied into browser, mobile or desktop source/build configuration.
- Desktop release mode opens the shared hosted app and does not start a per-customer Python backend. Local mode remains available for development. The cloud credential bridge exposes only the existing device-grant slot to the trusted app origin, excluding local provider credentials. Minimum window dimensions allow compact layouts.
- Header, Today panel, chat scroll area and composer fit the viewport; tablets use compact navigation below 1024 pixels. Small-screen controls wrap, text inputs use a readable size, and safe-area padding is retained. Native mobile constrains reading width on tablets and improves keyboard avoidance on Android/iOS.
- About/settings no longer direct closed-source customers to source-repository setup pages.

## Deployment requirements

The web changes were deployed to **production** on October 4, 2026 at https://open-learn-eta.vercel.app from commit `756382c` (deployment `dpl_DReCeueVXtm8qN3rZGbUzfoRXSj1`, status READY). The source was pushed to `codex/openlearn-2-local-checkpoint-20261003`. No working hosted Python API origin was provided or found; Vercel production has no configured environment variables. Backend and native/desktop releases have not been deployed. The existing `deploy/render.yaml` defines an API and three workers; it does not prove those services already exist.

1. Provision the existing Render API/worker blueprint with PostgreSQL, private object storage and the account issuer settings in `deploy/hosted.env.example`. Keep production authentication enabled. API and workers must use the same database, object storage, account configuration and provider configuration.
2. Store the existing OpenRouter key in the backend hosting secret store as `OPENROUTER_API_KEY`, with `AI_TUTOR_PROVIDER=openrouter`. Select the existing approved model through `OPENROUTER_MODEL`. Never use a `NEXT_PUBLIC_` or `EXPO_PUBLIC_` variable for provider credentials.
3. In Vercel, set server-only `OPENLEARN_API_ORIGIN` to the actual HTTPS API origin, and configure the public OIDC issuer/client/audience variables shown in `web/.env.example`. The `/v1` proxy works for normal API requests and streaming responses. For uploads larger than the web host's request-body limit, configure direct `NEXT_PUBLIC_LEARNING_API_URL` to that API origin and allow the web origin in the backend's CORS configuration.
4. Build native mobile with the HTTPS API origin and the native OIDC client settings in `mobile/.env.example`. Configure the native callback scheme in the account issuer.
5. Desktop releases use `https://open-learn-eta.vercel.app` by default; set `FORMA_HOSTED_WEB_URL` for an alternative HTTPS app origin. Set `FORMA_SERVICE_MODE=local` only for an intentional local development build. Cloud mode requires the same working hosted account/API configuration as the web product.
6. Redeploy web and release native/desktop builds, then verify sign-in → Buddy load → send → response, upload, saved-work recovery and account isolation against the real production API.

The website/web application, native mobile app and Windows/macOS shell are separate client builds using one account/backend service. A marketing website is a separate presentation surface and should not carry provider secrets or replace the Python API.

## Verification

Six provider-settings tests pass, including production mutation denial and secret-free service status. Twenty-one web regression tests pass, covering the composer, API proxy, account transport, offline edits and existing workspace/flashcards. Browser checks confirm typing during an outage and composer bounds at phone, tablet and short-laptop sizes. Live OpenRouter connection is verified. The Next.js production build passes, including TypeScript and the dynamic `/v1` route. Native mobile TypeScript and desktop main/preload syntax checks pass. The production build was launched locally and its editable outage composer was verified. A missing hosted API origin returns a clean HTTP 503 from the production proxy. During generation, completion only clears the submitted draft if the learner has not edited it; a new draft is preserved.

Hosted end-to-end delivery, native device interaction and packaged desktop launch remain deployment/device acceptance checks; they are not claimed from local browser or unit tests.

Local production screenshot: `work/product-service-desktop.png`. Production-build chart sizing warnings come from existing prerendered charts; the build completed successfully.

## Production release verification

The public homepage returns HTTP 200. Browser verification confirms the composer accepts typing during the outage and no longer displays local startup instructions. `/v1/account` returns the expected clean HTTP 503 while `OPENLEARN_API_ORIGIN` is missing; live sign-in, chat responses and backend flashcard operations remain unavailable. A bounded Vercel error-level log query returned no entries; this does not establish backend availability. Screenshot: `work/product-service-live.png`. The deployment upload was checked to include only web source and exclude private environment files, backend data and build output.
