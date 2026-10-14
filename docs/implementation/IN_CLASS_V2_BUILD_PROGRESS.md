# In-Class V2 implementation progress

Started: 2026-10-13. Specification: `IN_CLASS_EXPERIENCE_V2_SPEC.md`.

## Source baseline

- Original branch: `codex/memory-shadow-platform-billing`, commit `4566301`.
- Fetched origin and fast-forwarded to latest `origin/main`, `ece4912`.
- Preserved pre-existing assessment changes and the untracked specification/performance report.
- No repository `AGENTS.md` was found during inventory.
- Existing stack remains FastAPI + durable workflow/outbox and current web/native clients.

## Requirement checklist

| Specification area | State | Evidence / next work |
| --- | --- | --- |
| Phase 0: latest source and baseline inventory | Implemented | Current source and worker/chat/native/visual contracts inspected; migration and release head are additive; real accuracy corpus remains external acceptance work |
| Phase 0: recognition benchmark | Foundation implemented | `backend/scripts/class_transcription_benchmark.py`; offline WER, error counts, occurrence-based term recall and subgroup reports |
| Phase 1: AssemblyAI prerecorded transport | Implemented | Current Universal-3.5 Pro model, async transport and delete; new-class opt-in flag, existing providers preserved |
| Phase 1: durable external request tracking | Implemented | `class_verification.py`, migration 0089, worker planning/recovery; persisted submitting fence prevents blind duplicate billing |
| Phase 1: context windows, glossary/add-on pricing | Implemented; tuning pending acceptance | Independently decoded context WAVs, 30-second target, bounded pause/final flush, verified course glossary and separately metered add-ons |
| Phase 1: streaming and correction/reconciliation | Implemented; real acceptance pending | Authenticated backend relay, 60-second rotations, wall-time billing, persisted captions and existing human-correction/reconciliation contracts |
| Phase 1: settings/desktop key integration | Backend implemented; UI integrated in workspace phase | Local-only speech settings router, backend configuration helper and desktop credential injection; no general text-provider change |
| Phase 2: pairing/ownership/mobile integration | Implemented; native acceptance pending | Expiring QR/code, authenticated consent claim, secure phone capability, durable commands/acks, acknowledged epoch handoff, historical uploads, phone PCM relay and local journals |
| Phase 3: Buddy anchored context/doubts | Implemented core; full acceptance pending | Accepted generation freezes bounded class evidence; retry keeps original anchor and stale warning; source corrections flag old answers; desktop/web and native phone question panels; last 20 persisted answers reload in web panel; durable revisioned doubts |
| Phase 4: document/workspace | Implemented; physical acceptance separate | Stable topic sections, rename/merge/reorder, note moves, paginated notebook, protected edits/suggestions, transcript replay/correction/undo and responsive Buddy panel |
| Phase 4: interval practice first fire | Implemented | First interval waits for 10/20 minutes; end-only/off semantics retained |
| Phase 5: visual note blocks/rendering | Implemented; representative course acceptance pending | Six bounded declarative kinds, friendly editing, protected regeneration suggestions, capped opt-in automatic visuals, numeric evidence checks, source fencing and SVG/Markdown exports |
| Phase 6: integrated acceptance and rollout | Software/provider smoke verified; external acceptance deferred | 97-test backend regression, focused follow-ups, web/mobile checks, browser flow and real synthetic provider calls; Android build setup deferred by user, held-out lecture corpus and production load measurements unavailable |

## Configuration and usage

Store `ASSEMBLYAI_API_KEY` in local `backend/.env` or the hosted backend secret store. Also provide a verified `OPENLEARN_CLASS_VERIFICATION_MODEL` and `OPENLEARN_ASSEMBLYAI_STT_USD_PER_MINUTE`. Existing enforced paid-route accounting and a pinned provider rate version remain required.

The adapter is deliberately not wired into the legacy `AI_TUTOR_TRANSCRIPTION_PROVIDER`. New classes use `OPENLEARN_CLASS_VERIFICATION_ENABLED` with their pinned speech settings. The worker now persists upload/request IDs and uses asynchronous status jobs. Submission never auto-retries after ambiguity; `provider_submission_unknown` requires reconciliation. Polling does not create another charge. Vocabulary and speaker add-ons require their separately configured rate ceilings.

User authorized model selection. On 2026-10-13 current official pricing and SDK documentation superseded the original Universal-3 Pro example: prerecorded uses Universal-3.5 Pro, live uses Universal-3.6 Pro. Reviewed defaults were saved locally without displaying credentials. Features remain disabled until the integrated acceptance pass. Rates/configuration can be reproduced with `python -m backend.scripts.configure_class_speech`; use `--enable` after acceptance and restart the backend.

Phase 1 automated verification: **29 foundation/verification tests passed**, and **1 authenticated websocket relay test passed**. These prove bounded assembly, service-restart recovery, submission fencing, timed evidence, caption persistence, usage accounting and ticket replay rejection. Real provider recognition, physical-device capture, hosting websocket behavior and accuracy/latency targets remain Phase 6 acceptance items, not claimed as verified.

Phase 2 backend verification: **5 tests passed** covering idempotent drafts, consent and owner checks, challenge replay, persistent rate budgets, unacknowledged Stop, command expiry, and acknowledged handoff preserving source offsets. Mobile TypeScript and the existing **15 protocol tests passed** before the new handoff test was added; the updated protocol suite is included in the final regression pass. Native modules now emit bounded PCM events with at most two unacknowledged bridge frames, and use monotonic run clocks. Physical Android/iOS microphone, interruption, background and kill/recovery behavior remains unverified until device acceptance.

Device switching waits for the old device's sealed manifest acknowledgment. An unreachable recording device is never automatically replaced; the UI truthfully retains Stop requested and prevents starting a second microphone in that class. This is a deliberate safety choice until a forced-switch implementation can retain arbitrarily overlapping offline runs without colliding with the existing contiguous recording manifest.

## Recognition evaluation

Create a private JSON corpus with `samples`, each containing unique `id`, `group`, manually checked `reference`, provider `hypothesis`, optional `terms`, and optional measured `latencyMs` / `costUsd`. Do not commit lecture audio or private transcript text.

```powershell
backend/.venv/Scripts/python.exe -m backend.scripts.class_transcription_benchmark private-corpus.json --output private-report.json
```

Run the identical reference corpus for existing and candidate providers. The tool does not make provider requests, report fake accuracy measurements, or interpret mathematical correctness. Term recall is phrase occurrence-based; check context, numeric/equation meaning, and speaker attribution separately. Held-out groups and real sample results are still required before selecting a default.

## Verification

Verified on 2026-10-13:

- Combined foundation + existing class + existing lecture pipeline regression run: **61 passed** in 200.13 seconds. This includes the simulated one-hour, 450-slice recovery/processing scenario.
- After adding explicit reviewed-model validation and its two cases, the current foundation suite: **25 passed** in 9.17 seconds. The existing class suite has 18 cases and the lecture suite has 20 cases (including parameterized cases).
- `git diff --check`: passed. Benchmark CLI help entry point: passed.
- Existing warnings: Python 3.12 SQLite datetime adapter deprecation and reflection of an expression-based memory index. No new test failures remain.
- Sandbox-specific issues encountered and resolved for verification: default pytest temporary-directory creation was denied, and Windows asyncio local socket-pair initialization hung under the sandbox. The completed combined run used a fresh workspace test directory and execution outside that socket restriction. Earlier incomplete sandbox runs are not counted as passing verification.

At this earlier checkpoint, real AssemblyAI calls and completed V2 flows had not been verified. Later connectivity and browser results below supersede that checkpoint; real lecture accuracy improvements and native behavior remain unverified. The new speech flags remain disabled pending integrated acceptance. Update this section with exact results after each completed phase.

### Continuation: Buddy, notebook and visuals

The Buddy suite passed **3 tests** for time fencing, ownership, selection revision validation, frozen retries, correction warnings and doubt revision conflicts. Notebook regeneration passed **1 test**: student text remains intact, a separate suggestion appears, stale acceptance fails, and explicit acceptance replaces it. Visual validation/worker coverage passed **6 tests**, including malformed tables, missing graph nodes, nonfinite coordinates, empty equations, unknown executable fields, idempotent requests and queued publication.

After adding persisted answer history and the corrected-source retry assertion, the current Buddy suite passed **4 tests** in 24.54 seconds. Notes/visual worker checks after binding owner-scoped provider accounting passed **7 tests** in 16.48 seconds. Web TypeScript passed again after history hydration and export fallback changes. Browser layout/interaction acceptance has not run yet.

Web and mobile TypeScript checks passed. The updated mobile protocol suite passed **16 tests**, including phone handoff sequence/time offsets without prematurely finalizing the whole class. Integrated backend regression passed **83 tests** in 303.99 seconds. The final setup-validation, correction-invalidation and relay-cleanup changes passed **36 focused tests** in 31.50 seconds; the final Buddy retry check also passed **3 tests** in 17.46 seconds. `git diff --check` passed.

Visuals use generated structured data with strict size bounds, never generated code or HTML. Numeric plot values must occur in the source note. This check prevents fabricated values but does not certify that plotted pairs have the correct scientific meaning; representative course acceptance is still needed. Illustration currently means a labeled schematic. Export includes validated JSON as an explicit fallback; native bitmap illustration is intentionally represented by a labeled schematic; standalone SVG export is now implemented (see final continuation below).

The Windows host currently exposes no `adb`, `java`, `gradle` or `xcodebuild` command. Android/iOS compilation and physical capture verification remain external acceptance work. Existing source tests do not establish native microphone, lock-screen, call interruption or OS-kill guarantees.

User confirmed an Android phone is available. See [Android acceptance](IN_CLASS_ANDROID_ACCEPTANCE.md) for the existing development build path and concrete device checks.

Real provider smoke checks passed using locally generated synthetic speech, with an isolated enforced usage ledger and without changing application feature flags. Universal-3.5 Pro transcribed **9.597 seconds**, returning **22 timed words** in **3.17 seconds** at **$0.000559825 estimated cost**, then its provider transcript was deleted. Universal-3.6 Pro through the actual authenticated relay produced **9 caption events and 3 persisted final captions**, **0 relay errors**, **12.45 seconds elapsed**, at **$0.001625 estimated cost**. The first streaming script attempt missed the required idempotency header and was rejected locally with 422 before any provider connection; the script was corrected. These are connectivity/model/metering checks, not a lecture WER comparison, physical-device test or provider billing receipt.


## Final continuation — 2026-10-13

Current implementation and rollout details: [implementation report](IN_CLASS_V2_IMPLEMENTATION_REPORT.md). This section supersedes older status snapshots above.

- Phase 3: selected student notes, bounded topic outline and prior doubts are frozen alongside transcript evidence. General-chat outbox freezes class context at enqueue; retries retain the original lecture moment. Local recording time and phone heartbeat time prevent transcription lag from changing the question anchor. Class creation now explicitly grants its scope/graph to the owner before worker admission.
- Phase 4: stable topic sections support rename, merge and reordering; notes can move between topics. Loaded notebook pages refresh without resetting the active student draft or discarding the loaded tail. Transcript passages support owned audio replay, wording/speaker correction and append-only undo. Near-identical resegmented source coverage retains the same edited note block; stale suggestions cannot be accepted.
- Phase 5: friendly visual fields cover labels, tables, steps and numeric points; JSON remains optional advanced editing. Edited diagrams survive regeneration. Strict schema and numeric/source checks reject malformed output. Automatic creation is opt-in with a per-class budget; all generations use the existing fair batch queue. SVG export works, and Markdown contains an explicit declarative fallback, with review labels for previous stale visuals.
- Recovery: unknown provider submissions accept only an exact original-audio receipt; they never blindly resubmit. Empty abandoned phone drafts expire after 24 hours without deleting recordings. Expired pairings and old rate records receive bounded maintenance. Runtime gates independently control pairing, Buddy, topic notes and visuals.
- Input checks: laptop uses a five-second local analyser; phone uses an explicitly requested five-second metered cache sample, deletes it afterward, and never journals/uploads it. Permission and physical metering behavior still require native acceptance.

Verification recorded in this continuation:

- Full combined backend regression: **97 passed in 288.80 seconds**. Subsequent correction/cleanup checks: **21 passed in 57.35 seconds**; two added preservation/expiry cases: **2 passed in 10.10 seconds**. Final prior-doubt/context/expiry follow-up: **18 passed in 82.05 seconds**.
- Web class editing/layout/outbox/proxy and existing tutor component checks: **17 passed** (latest run 5.74 seconds). Web TypeScript passed after page refresh changes.
- Mobile TypeScript passed after regenerating **312 API schemas**, disambiguating schema names and adding phone preflight. Mobile protocol: **16 passed**.
- Browser against the actual local API/proxy with isolated mocked lecture/provider data: completed Buddy answer and citation; selected student note evidence; corrected-source review warning; retained edited notebook text; friendly diagram edit persisted through reload; regeneration retains old diagram; SVG and Markdown downloads produced usable files. This fixture is not a real lecture or a physical capture test.
- `git diff --check` passed after trimming accidental trailing blank lines. Existing SQLite datetime/reflection warnings remain.

User explicitly deferred Expo login/public mobile environment/build setup: “Continue code; build setup later.” Android microphone, screen lock, interruption, process death and wireless installed-build checks remain **deferred**, not passed. No consented lecture benchmark corpus exists yet. Recognition improvement and production p95/fairness targets remain unmeasured. Features are independently off by default; do not enable a broad production rollout on the strength of synthetic smoke tests.

Mocked browser proof: ![Preserved student note, edited diagram and corrected-source Buddy warning](../../work/in-class-v2-final.png)

Final explicit document-acceptance and verification suite: **7 passed in 31.11 seconds**. Final web/mobile TypeScript, mobile protocol (16 tests), desktop main-process syntax, and `git diff --check` all passed.

## Original-spec completion follow-up

1. **Live classroom navigation — implemented.** A collapsible topic/bookmark sidebar, remembered panel choices, mounted-but-hidden Buddy panel and notebook across view switches, protected reading/editing position, incoming-note notice and explicit Return to live navigation are in place. Navigation loads missing notebook pages within the existing 1,000-block bound. Web TypeScript and 12 focused classroom tests passed; the initial sandbox test attempt failed before running tests, then passed outside the temporary-file restriction.
2. **Phone pairing preview — implemented.** Authenticated, rate-limited preview is separate from claiming or microphone permission. The phone displays the account, class and requesting laptop before explicit recording confirmation. Preview cancellation creates no run. Seven device-service tests and mobile TypeScript passed; physical permission/start checks remain part of Android acceptance.
3. **Semantic topic organization — implemented.** Note generation receives up to 20 existing topics with two bounded source-note excerpts each and can reuse a semantic section or consolidate up to four generated duplicates. Publication checks topic revisions, protects manual organization and student edits, and retains stable note IDs/text. Merged headings redirect future mentions to the retained section. Eleven topic/document checks passed, including actual worker/provider-prompt integration; a broader regression follows below. Semantic grouping follows the existing pinned topic-notes flag and runtime gate.
4. **Complete phone telemetry — implemented and software verified.** Native battery readers feed the capture heartbeat through a bounded, cached adapter. Unsupported readings remain unavailable, zero percent is retained, and sensor failure cannot block status. Phone/laptop show captured duration; laptop displays backlog and report age, detects staleness locally even during failed polling, and warns on low battery. Twenty mobile protocol/telemetry tests and 18 web classroom checks passed. Native compilation and sensor behavior remain Android/iOS acceptance items.

Android build setup and physical-device acceptance remain deferred until these four implementation gaps are complete, as requested by the user.

Final follow-up verification: **52 backend tests passed in 207.61 seconds**, covering topic organization, device pairing/telemetry, notebook edits, Buddy, visuals and existing classroom behavior. **18 web tests**, **20 mobile tests**, web/mobile TypeScript and `git diff --check` passed. The additional semantic source-revision checks passed in the 11-case topic suite. The interrupted sandbox backend attempt is not counted as passed; the completed run used execution outside the Windows asyncio socket restriction. Existing SQLite datetime/reflection warnings remain.

The actual isolated API preview returned account/class/laptop details and created no recording run. Browser verified topic/Buddy collapse/reopen, retained question draft and expanded classroom layout through the current web proxy/API. Preview data/provider responses were mocked. Temporary web environment changes were restored and the backup removed. Native permission, startup and battery behavior still need Android acceptance.

![Verified classroom navigation and retained Buddy draft](../../work/in-class-four-gaps.png)
