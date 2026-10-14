# In-Class V2 implementation and acceptance report

Updated 2026-10-13. Implements [the specification](IN_CLASS_EXPERIENCE_V2_SPEC.md) on the FastAPI/workflow, web/desktop and native foundations. Source baseline was fast-forwarded to `origin/main` at `ece4912`; unrelated assessment changes were preserved. Changes are recorded locally in Git; no remote publication is included.

## Delivered behavior

| Phase | Implementation | Acceptance status |
| --- | --- | --- |
| 0 | Baseline inventory and offline recognition benchmark CLI | Software verified; no held-out consented lecture corpus available |
| 1 | AssemblyAI asynchronous verification and authenticated live relay, pinned speech configuration, timed word evidence, durable external requests and usage reservations | Automated recovery/contracts and real synthetic connectivity checks passed; lecture accuracy comparison pending |
| 2 | Authenticated expiring QR/code pairing, explicit recording consent, scoped secure phone capability, acknowledged commands, epoch handoff, immutable direct uploads and native local recovery journal | Backend/protocol verified; physical Android/iOS acceptance pending; build setup deferred by user |
| 3 | Quiet Buddy panel and phone questions, frozen lecture/selected-note context, topic outline, prior doubts, citations, saved doubt resolution, replayable answer history and corrected-source warnings | Backend and mocked browser flow verified |
| 4 | Topic notebook, outline, rename/merge/move, protected edits with explicit suggestions, bounded pagination, transcript replay/correction/speaker identification/undo, settings and responsive panel layout | Backend, TypeScript, component checks and mocked browser flow verified |
| 5 | Six safe declarative visual types, friendly authoring fields, regeneration suggestions, source checks, capped automatic creation, SVG and Markdown exports | Contracts/component/browser checked; scientific usefulness on representative real courses pending |
| 6 | Independent rollout gates, additive migrations, benchmark/smoke/browser fixtures, recovery checks and device test instructions | Software checks completed as listed below; native, held-out quality and production load acceptance remain external work |

AssemblyAI does not replace the general text/vision provider or legacy lecture provider. Economical mode disables live speech and uses a 90-second verification target; balanced mode uses 30 seconds, with bounded pause/end flushes. A better microphone placement can help recognition; neither preflight nor provider connectivity proves lecture accuracy.

The laptop preflight analyses five seconds locally without saving audio. Phone preflight explicitly requests permission, measures a short local cache sample, and deletes it afterward without journaling/uploading it. The native permission/metering implementation still needs device evidence.

## Architecture and decisions

- Recorded audio remains authoritative. Live captions create provisional material; verification and append-only human corrections update source revisions. Student text survives regeneration as a separate proposed replacement.
- Verification persists upload URL, submission fence and provider receipt independently of worker leases. An ambiguous paid submission requires reconciliation; polling/recovery cannot silently create a second paid request. Receipt association verifies the original audio URL exactly.
- Phone capture owns one acknowledged run/epoch. Remote Stop is only a request until the phone acknowledges its sealed manifest. Offline audio stays in the native journal and uploads directly after reconnect. An unreachable recording device is not forcibly replaced: the current contiguous manifest cannot safely admit arbitrary overlapping runs. This deliberate restriction prevents hidden audio collisions.
- Buddy receives bounded, time-fenced source text, selected student notes, topic outline and prior doubts. General chat freezes context before enqueue, so offline retries retain the question moment. Corrections flag prior answers without rewriting their frozen evidence. Transcript/material text never gains instruction or tool authority.
- Note IDs survive near-identical source resegmentation (at least 95% time-range overlap with one unambiguous stale candidate). Ambiguous split/merge matches remain explicit review work; they are not silently combined.
- Visuals are validated data, never generated HTML, scripts or executable code. Tables/graphs/steps/plots have hard size bounds. Plot points require an exact supporting note quote containing both values. Simple supported numeric equalities are checked safely; symbolic mathematical correctness is not certified.
- Illustration means an accessible labeled schematic with optional coordinates/shapes. Raster generation is not added as an unmetered dependency. SVG exports preserve the diagram; Markdown uses an explicit validated-data fallback and labels retained stale figures.
- Workers retain the existing interactive/batch queues. Automatic visuals default off and have a per-class budget; generation is capped at 12/class/hour. Notebook pages are 50 blocks, visual pages 20, topic pages 200; refreshes preserve loaded pages and active drafts. A 300-block/2.5-hour synthetic notebook pagination case is covered.
- Scope/graph resources created during class setup are explicitly assigned to the owner; worker accounting does not weaken access checks. The web proxy forwards only approved capture/chunk headers. Arbitrary loopback development API ports are allowed only in development, never production.

## Database and compatibility

Apply the existing migration/release workflow through **`0091_class_evidence_indexes`**:

1. `0089_class_experience`: external verification, word evidence, pairings/runs/commands, Buddy contexts/doubts, document blocks and visual artifacts.
2. `0090_class_topics`: stable topics and block topic/position fields.
3. `0091_class_evidence_indexes`: note source-range index and immutable audio-chunk run/epoch provenance.

The release contract advertises the final head. Existing recording/session/output contracts remain usable. New default policy fields are omitted from the setup idempotency hash when at their defaults, preserving old setup retries. Source-range backfill runs in small batches. Empty abandoned phone drafts expire after 24 hours only if no run or audio chunk exists; the recording is retained. Pairing/rate cleanup is bounded.

Mobile types are generated from the composed OpenAPI schema in an isolated temporary workspace database. Invalid TypeScript punctuation is normalized and name collisions fail explicitly. Duplicate names use fully qualified backend schema identifiers in mobile imports.

## Configuration

The configured AssemblyAI key stays in local `backend/.env`, desktop backend secret injection or the hosted backend secret store. Never add it to `mobile/.env`, public web variables, QR links or source control.

Reviewed settings already selected with the user's authorization:

| Setting | Value |
| --- | --- |
| `OPENLEARN_CLASS_VERIFICATION_MODEL` | `universal-3-5-pro` |
| `OPENLEARN_CLASS_STREAMING_MODEL` | `universal-3-6-pro` |
| `OPENLEARN_ASSEMBLYAI_STT_USD_PER_MINUTE` | `0.0035` |
| `OPENLEARN_ASSEMBLYAI_STREAMING_USD_PER_MINUTE` | `0.0075` |
| `OPENLEARN_ASSEMBLYAI_KEYTERMS_USD_PER_MINUTE` | `0.000833334` |
| `OPENLEARN_ASSEMBLYAI_DIARIZATION_USD_PER_MINUTE` | `0.000333334` |

These reviewed ceilings were taken from official provider documentation/pricing during this session. Confirm account-specific billing before rollout; estimates are not invoices. Existing allowance enforcement and provider rate-version pinning remain mandatory. The helper writes a private streaming secret if absent and never prints credentials:

```powershell
backend/.venv/Scripts/python.exe -m backend.scripts.configure_class_speech
```

After acceptance, `--enable` also enables new-session verification/live routes; restart the backend. Local settings UI lives under Class → Processing preferences and requires `OPENLEARN_ALLOW_LOCAL_PROVIDER_KEYS=true` on a local backend. Hosted settings are managed by service secrets and reject local key writes. Desktop injects the backend key through its existing credential path; no mobile key is needed.

Independent default-off switches:

```dotenv
OPENLEARN_CLASS_VERIFICATION_ENABLED=false
OPENLEARN_CLASS_STREAMING_ENABLED=false
OPENLEARN_CLASS_PHONE_PAIRING_ENABLED=false
OPENLEARN_CLASS_BUDDY_ENABLED=false
OPENLEARN_CLASS_TOPIC_NOTES_ENABLED=false
OPENLEARN_CLASS_VISUAL_NOTES_ENABLED=false
OPENLEARN_CLASS_AUTO_VISUALS_ENABLED=false
```

Enable in an authenticated acceptance environment first. New sessions pin their feature/speech policy. Visual automation additionally requires the session's explicit opt-in and budget. The settings page does not bypass allowance admission. Hosted live capture requires the existing authenticated WebSocket route to remain reachable through hosting/proxy configuration.

Rollback: disable the relevant switch and restart the backend. Pairing/new Buddy admission/visual generation stop without removing existing evidence or edited notes. Keep active phone recovery and saved audio uploads working. Disabling new generation is not a microphone Stop: request Stop and await the device acknowledgment. Keep additive migrations in place; do not downgrade/delete captured data to roll back a feature.

## Verification evidence

- Full backend combined run: **97 passed in 288.80 seconds**. Covers existing class/lecture pipeline plus V2 foundation, provider verification, phone, relay, Buddy, topics, visuals and final contracts. A setup ownership regression found in an earlier run was fixed; the passing full run includes that fix.
- Later source/cleanup follow-up: **21 passed in 57.35 seconds**. Two added expiry/resegmentation safeguards: **2 passed in 10.10 seconds**. Final prior-doubt/context/expiry run: **18 passed in 82.05 seconds**.
- Web focused suites: **17 passed**, latest 5.74 seconds. Meaningful checks cover diagram editing without altering relationships, directed layout, preserved outbox context, allowed proxy headers and existing tutor components. Web TypeScript passed.
- Mobile protocol: **16 passed**. Mobile TypeScript passed with 312 regenerated API schemas and phone preflight. These checks do not compile Kotlin/Swift or prove physical capture behavior.
- Browser through the real local web proxy/API using isolated mocked transcripts/providers: completed Buddy answer/citation, selected-note evidence, correction warning, editable topics/notebook, protected student text, persisted friendly diagram edit, retained diagram during regeneration, source-stale labeling, SVG download and Markdown export. SVG contains the actual edited labels and a standalone namespace. No private lecture or paid provider is used by this fixture.
- Real prerecorded provider smoke: **9.597 seconds** synthetic speech, **22 timed words**, **3.17 seconds** response elapsed, **$0.000559825** conservative local estimate; provider transcript deleted.
- Real authenticated streaming relay smoke: **12.45 seconds**, **9 caption events**, **3 persisted final captions**, **0 relay errors**, **$0.001625** conservative local estimate. The earlier missing idempotency header was rejected locally before a provider connection and corrected.
- `git diff --check` passed. Existing SQLite datetime adapter and expression-index reflection warnings remain.

Smoke latency measures one synthetic request; it is not p95, recognition improvement, a native recording test or a provider billing receipt. The offline benchmark reports WER, occurrence-based technical-term recall, subgroup errors and optional latency/cost from supplied records without making paid requests.

## External acceptance and owner actions

| Remaining check | Concrete action | Reason it is not marked passed |
| --- | --- | --- |
| Android APK/physical recording | Follow [wireless Android acceptance](IN_CLASS_ANDROID_ACCEPTANCE.md), configure Expo/project/public HTTPS/OIDC values, build preview APK and install from its link | User explicitly said build setup later; Expo login and mobile public environment were absent |
| Permission, preflight, lock screen, call, OS kill and offline upload | Run the documented device matrix and retain model/OS/build/network/ack timing evidence | Native guarantees require an installed build and actual phone |
| iOS native acceptance | Build/test on an iOS toolchain/device if iOS release is intended | No iOS build/device available here |
| Recognition improvement | Obtain a consented practice/lecture corpus with manually checked words, numbers, equations and speakers; compare both providers on identical held-out groups | No corpus or checked references available; consent prompt alone does not create benchmark evidence |
| Scientific visual usefulness | Review representative real subject notes/figures and plot pair meaning | Schema and numeric occurrence checks cannot certify pedagogy/scientific correctness |
| Production fairness, hosting and p95 | Run concurrent classes/questions on the intended deployment, verify WebSockets, inspect existing stage/queue/usage metrics and compare measured targets | Isolated tests establish bounded contracts, not production performance |

Do not record a real class merely to create acceptance evidence without the required permission. The application asks consent on laptop/phone; consented synthetic/practice speech can be used first. No additional user setup is required for the completed code work above.

Final explicit document-acceptance and verification suite: **7 passed in 31.11 seconds**. Final web/mobile TypeScript, mobile protocol (16 tests), desktop main-process syntax, and `git diff --check` all passed.
