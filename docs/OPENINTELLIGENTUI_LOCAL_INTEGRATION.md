# OpenIntelligentUI local integration

Updated October 10, 2026. Local provider generation and durable visual runs are implemented. Production deployment remains pending container and broader acceptance validation.

## Implemented

- Upstream cloned at `work/research/openintelligentui-20261009`, pinned to `f6e4388b26a64b9a0714943b08a1ce622b924eec`. Its declared pnpm 9 and frozen Python dependencies are installed separately from Open Learn.
- Open Learn invokes the pinned CopilotKit runtime and LangGraph/Deep Agents visual graph through loopback services. JEV presentation selection and generation both use OpenRouter. JEV uses the structured Decisions endpoint with `typesafe/jev-1.13`.
- Both provider transports pass through the Open Learn backend. Provider keys stay there. Short-lived signed grants bind requests to a learner and active generation; existing usage reservations meter calls.
- Visual generation runs as an independent, durable child job after the explanation commits. Bounded previews and stable artifact references persist in the workflow store. Readers replay stored artifacts rather than regenerating them.
- The MIT upstream progressive Websandbox renderer is imported with attribution. Three, OrbitControls, GSAP, D3 and Chart.js assets are bundled locally. Preview and final frames block network connections and form submission.
- Tables use the upstream A2UI tool/catalog and a validated accessible host table renderer. This is not a general-purpose A2UI catalog renderer.
- Sandbox follow-up questions require an explicit host click and fill only the originating chat draft. HTTPS links have a host-owned affordance. Visual failures preserve the tutor explanation and show a scoped status.
- Graph execution has a recursion limit, a deadline, restricted tools and bounded local memory checkpoints. Durable jobs recover saved final candidates without another provider call. Interrupted in-flight generation requires explicit retry; token-level graph continuation is not implemented.
- Numeric control manifests, owner-scoped revision checks and immutable revision history support voice parameter edits. The host supplies focused visual context without sending executable generated code to the voice coordinator.
- Leaflet joins the locally bundled renderer libraries. Map/image network access is limited to approved tile and Wikimedia hosts; arbitrary connections remain blocked.

## Local setup

Run from the repository root:

```powershell
.\setup-openintelligentui.ps1
.\start-openintelligentui.ps1
.\start-local.ps1
```

The setup script imports the pinned renderer, builds visual assets and creates a local internal signing secret. It does not copy production keys into the upstream repository. The startup script verifies service readiness; logs are under `work/local-runtime`.

Reuse `OPENROUTER_API_KEY` in ignored `backend/.env` for both generation and JEV. No `TYPESAFE_API_KEY` is required. The visual proxy shares the existing `OPENLEARN_JEV_USD_PER_REQUEST` usage tariff. Local testing uses a $0.01 reservation ceiling per request and settles the actual OpenRouter cost receipt; uncertain calls retain their ceiling. Presentation routing defaults to `OPENLEARN_VISUAL_JEV_MODEL=typesafe/jev-1.13`; `~typesafe/jev-latest` is also supported. Legacy bare model names are normalized. Optionally select an approved model with `OPENLEARN_VISUAL_MODEL`; otherwise `OPENROUTER_MODEL` is used. Do not paste secrets into chat.

For local acceptance testing, set `OPENLEARN_VISUAL_ENGINE=openintelligentui` in `backend/.env` and restart the local backend. Restart the visual agent if its model selection or signing secret changes. Until activation, legacy visual generation remains selected. Rollback is `OPENLEARN_VISUAL_ENGINE=legacy` and an API restart. Existing legacy visuals remain readable.

Endpoints:

- Open Learn: `http://localhost:3000`
- Backend: `http://127.0.0.1:8000`
- Visual graph health: `http://127.0.0.1:8123/health`
- CopilotKit runtime health: `http://127.0.0.1:8130/health`
- Authenticated backend readiness: `/v1/visual-pipeline/capability`

Sidecar health confirms the process is running; only backend capability checks provider configuration. Neither is proof of successful paid generation.

The upstream standalone chat demo is not the Open Learn integration entry point. Its original BYOK transport expects different credentials. Use Open Learn to exercise the authorized provider proxy.

## Verified and remaining

Verified: 46 targeted Python tests and 3 frontend artifact/policy tests pass. Local API, frontend and both visual sidecars respond. Targeted lint has no errors; two existing LearnChat hook warnings remain. The full TypeScript check previously reported existing generated route and test typing errors, so repository-wide type validation is not clean.

An isolated Chrome renderer fixture verified local D3 imports, slider interaction updating the displayed calculation, and the Websandbox follow-up API producing an editable host review question. This exposed and fixed literal import-map URLs; public module assets also received an opaque-origin CORS header. The running Open Learn development server returned HTTP 200 and `Access-Control-Allow-Origin: *` for its D3 module after restart. Evidence: `outputs/openintelligentui-renderer-smoke.png`. The fixture is synthetic and does not prove model generation quality.

A live OpenRouter JEV decision request returned HTTP 200, selected `interactive_diagram`, and reported cost $0.000031332. The authenticated proxy is covered by mocked success/failure and receipt-settlement tests. This confirms provider connectivity, not full graph acceptance.

Live acceptance now verifies OpenRouter JEV selection and generation through the private runtime and graph, durable publication of an interactive force calculator, real rendered input interaction, a saved numeric revision restored after reload, and rejection of a stale update with HTTP 409. The local engine is enabled. The latest focused backend suite passed 22 tests covering persistence, lease fencing, recovery, provider boundaries and activity reduction. This supplements earlier checks; it is not a clean repository-wide validation.

Remaining acceptance includes real-stream cancellation, live microphone-driven voice edits, mobile behavior, provider receipt reconciliation and production rollout. The main browser chat now persists trusted numeric slider changes. Generated styling still needs quality review. Object-store artifact limits and token-level graph checkpoints remain future migration work.

## Completing the upstream integration

The full design guidance is vendored as `integrations/openintelligentui/design-skill.md` and inserted into the graph's system context. Visual child jobs freeze recent owned conversation, committed explanation and exact prior table/control data using `backend/app/visual_context.py`; they do not persist provider credentials or feed executable prior code back to the model. The visual input envelope remains bounded.

Generated cards offer **Download** and **Copy HTML**. Required reviewed library modules are embedded as data modules; the exported document renders inside an opaque sandbox and does not connect back to Open Learn. Maps/photos still require approved public image hosts. Host-only follow-ups explain that the snapshot is disconnected. Tested output: `outputs/openintelligentui-map-export.html` and `outputs/openintelligentui-map-export.png`.

Trusted numeric change events persist through the existing owned visualization PATCH endpoint. Requests serialize using the latest revision, and voice focus updates after each save. Revision history stores the initial code once and bounded numeric deltas for subsequent changes (maximum 500 revisions). The main chat browser test persisted mass 7 at revision 5 and restored it after reload; screenshot `outputs/openintelligentui-chat-saved-controls.png`.

The producer validates JavaScript with `node --check` without executing it, normalizes valid multiline literal JSON and repairs only an exact unique CSS-class/DOM-ID mismatch. Other invalid code is rejected. Unsupported generated fetch/XHR/WebSocket calls are rejected; image/tile loading remains governed by CSP. Tool validation can return a bounded correction request inside the same accounted run; it is not a restart-based automatic regeneration.

Optional MCP:

```powershell
cd integrations/openintelligentui
npm ci --ignore-scripts
npm run mcp       # stdio, suitable for a configured external MCP client
npm run mcp:http  # loopback only, http://127.0.0.1:8142/mcp
node --test mcp.test.mjs
```

MCP exposes skill resources/prompts, design guidance and `assemble_document`; it exposes no learner data, provider credentials or application mutation tools. HTTP rejects unexpected Host/Origin values and bounds request size/concurrency. External hosts must render returned HTML in an isolated sandbox; assembly itself neither displays nor deploys anything.

Verification includes 30 focused Python checks, followed by 20 passing checks in the updated pricing/planning suite, 13 frontend tests, an MCP protocol test, live A2UI table generation, chart/3D browser rendering, independent map export, and saved controls in the actual localhost chat. These overlapping backend counts are not additive. Mobile layout and cancellation have live evidence. Global type-check failures remain in pre-existing route/test types. Live correction-loop and microphone-driven voice acceptance and production rollout are outstanding. The latest live map retry reached named photo/render tools, then ran into bounded-input and local-account allowance limits; focused prompt guidance was reduced and still needs live acceptance.

An optional paid visual model must be explicitly selected in `OPENLEARN_VISUAL_MODEL`, with `OPENLEARN_VISUAL_RATE_VERSION` and a matching `OPENLEARN_VISUAL_MODEL_TARIFFS` JSON entry. The entry must name provider `openrouter` and provide positive finite `usd_per_million_input`, `usd_per_million_output` and `usd_per_million_cache_read`; optional cache-write rates receive the same validation. Account allowances, paid-route enablement and platform spending caps continue to apply. This does not activate a paid model automatically.

The production gate is `OPENLEARN_VISUAL_HOSTED_ENABLED=true`, set only after rollout checks. The supervisor preserves `hosted_runtime` authentication/storage/migration checks, and the image retains Playwright/Daytona dependencies with a non-root runtime user. The current Render service uses `deploy/Dockerfile` and an explicit `hosted_runtime api-free` command; changing environment variables alone does not deploy this candidate supervisor. A release must explicitly change the service image/start configuration and validate `/ready`, authenticated capability and a real visual job.

## Container acceptance

The production candidate is `integrations/openintelligentui/Dockerfile`, with a supervisor starting private graph/runtime services and the public API. Its build context excludes environment files, local databases and research checkouts. The pinned upstream sources and lockfiles are vendored under `integrations/openintelligentui/upstream`; provider credentials stay in the API process.

On this Windows machine Docker failed on a stale `dockerInference` runtime socket. Preserving the runtime socket folders under timestamped backup names restored engine 29.4.1 without deleting Docker data. The source-only build context is approximately 195 KB. Image `openlearn-visual-api:acceptance` built successfully; an isolated container without production credentials or databases returned HTTP 200 from graph (8123), runtime (8130) and API (8000), and the public local test port returned `status: ok`. This is packaging/startup acceptance, not live container provider or production acceptance. Four frontend artifact boundary tests passed. No production release has been completed.
