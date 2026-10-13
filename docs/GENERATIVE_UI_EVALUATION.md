# Generative UI engine: evaluation report

Measured 12 October 2026 on branch `claude/generative-ui-engine`, Windows 11, local stack (API, CopilotKit runtime, LangGraph visual graph) against OpenRouter free models. Architecture and decisions: [GENERATIVE_UI_ENGINE.md](GENERATIVE_UI_ENGINE.md).

Every number below was measured by running the real pipeline; nothing is estimated or simulated. Where a result could not be measured, it says so.

## 1. Method

`backend/scripts/visual_benchmark.py` seeds a lesson (a short tutor explanation plus the learner's question) for each task in the running API's database and requests a visual through the authenticated `POST /v1/lessons/{id}/visual-runs` endpoint. That is the same durable child job, sidecars, provider proxy, metering and persistence that chat uses. The harness polls the run, reads per-run tokens and cost from the usage ledger, fetches the published artifact, and measures it with the headless runtime verifier plus task-specific checks executed inside the rendered frame.

Tasks (spec section 11): gradient descent, pendulum with adjustable gravity, voltage/current circuit, neural network forward/backward propagation, binary search tree insert/delete, 3D scene with camera controls, transmission-line impedance, coordinated multi-chart dashboard, a previously unseen request (heat pump refrigeration cycle), a conversational modification (add damping to an existing pendulum), plus a simple chart (common-path latency) and an acknowledgement that needs no visual.

Objective measures:

- **Published:** the run completed with an artifact.
- **Runtime verification:** no uncaught error, console error, script timeout, empty/blank render, blank main canvas, collapsed or frame-clipped drawing surface, NaN/undefined/Infinity readout (including with every numeric control at its minimum and maximum), or desktop clipping at 720 px; plus mobile (360 px) and dark-theme passes.
- **Task checks:** scientific or behavioral assertions executed in the frame, for example period = 2π√(L/g) within 8%, I = V/R within 5%, |Γ| = |(ZL − Z0)/(ZL + Z0)| within 0.03, BST insert then delete changes the rendered tree, a dashboard filter changes at least two charts, the edited pendulum keeps gravity and length and adds damping. A check that finds nothing to measure (for example no period readout) is reported as n/a, not as a pass.
- **Interaction correctness:** each probed control's effect on visible output (responsive, unresponsive, or inconclusive when the scene animates on its own).
- **Latency:** time to first visible snapshot and total time from request to publication, including verification and repairs.
- **Cost and repair frequency:** model calls, tokens and settled cost from the usage ledger.
- **Browser resources:** main-thread busy fraction and JS heap during one idle second after the visual settles.

Subjective visual quality is assessed separately, from saved desktop/mobile/dark screenshots, and is labeled as subjective.

All runs were re-scored from their stored artifacts with the final verifier and checks (`--rescore`), so every configuration is measured identically. Check definitions were corrected during evaluation where they were too narrow (normalized Smith-chart inputs, a slider used as a dashboard filter, a JavaScript truthiness bug); those corrections apply to every run.

## 2. Configurations

| Label | Pipeline | Visual model |
| --- | --- | --- |
| A. Original | `main` (plus only the Windows UTF-8 validation fix) | `nvidia/nemotron-3-ultra-550b-a55b:free` (configured) |
| B. Original, working model | `main` (plus only the UTF-8 fix) | `nvidia/nemotron-3-super-120b-a12b:free` |
| C. Improved | this branch | `nvidia/nemotron-3-super-120b-a12b:free` |
| D. Improved, alternative model | this branch | `cohere/north-mini-code:free` |

A vs. B isolates the model; B vs. C isolates the architecture.

## 3. Results

Run directories (local, ignored by git): A `work/visual-benchmark/20261012-012452-baseline`, B `20261012-104846-B-original-super`, C `20261012-101136-C-frozen-super`, D `20261012-103012-D-frozen-cohere`. Configuration A predates the no-visual and edit tasks (10 visual tasks); B–D ran all 12.

| Measure | A. Original, configured model | B. Original, same model as C | **C. Improved** | D. Improved, Cohere |
| --- | --- | --- | --- | --- |
| Visual tasks published | 1 / 10 | 7 / 10 | **9 / 10** | 4 / 10 |
| Published visuals that are broken (fail runtime verification) | 1 (blank) | **3** (runtime exception and blank canvas; console errors ×2) | **0** | 0 |
| Tasks passing every objective check | 0 | 2 / 12 | **7 / 12** | 4 / 12 |
| Human review of published visuals (good / fair / poor) | – | not reviewed | 2 / 3 / 4 | not reviewed |
| Task checks (pass / fail) | 0 / 2 | 6 / 6 | **10 / 4** | 3 / 1 |
| Probed controls that visibly respond | – | 1 / 10 | **16 / 18** | 2 / 6 |
| Conversational edit (lineage, controls kept) | not run | not possible (base failed; no edit support) | **passed** | not run (base failed) |
| No-visual turn | – | 1 wasted model call (5,855 in / 271 out tokens) | **0 model calls**, 2.1 s | 0 model calls |
| Median total time, published (s) | 12.2 | 21.4 | 59.8 | 61.0 |
| Median time to first visible preview (s) | – | not observed | 30.5 | 43.2 |
| Runs that needed repair | 0 (no repair possible) | 0 (no repair possible) | 6 | 9 |
| Model calls / input tokens / output tokens | 10 / 74K / 11K | 10 / 74K / 31K | 20 / 193K / 72K | 30 / 186K / 88K |
| Largest single generation (output tokens) | 1,475 | **8,192 (cap hit; truncated)** | 9,153 | 10,607 |
| Largest published artifact (characters) | – | 4,817 | 20,171 | – |
| Settled cost (USD, free models; JEV routing only) | 0.00041 | 0.00041 | 0.00053 | 0.00041 |
| Median runtime verification per candidate (s) | – | – | 8.5 (max 13.1) | – |
| Idle main-thread busy fraction / max JS heap | – | 0.2% / 6.2 MB | 0.2% / 6.4 MB | 0.1% / 6.3 MB |

### Repeated samples (B vs. C, same model, final code)

To separate the architecture effect from run-to-run variation, B and C were each run three times, with identical code and checks within each configuration (B: `20261012-104846`, `-120051`, `-120746`; C: `20261012-101136`, `-111854`, `-114212`).

| Measure | B. Original pipeline | C. Improved pipeline |
| --- | --- | --- |
| Tasks passing every objective check (per run) | 2, 2, 3 (mean **2.3** / 12) | 7, 8, 6 (mean **7.0** / 12) |
| Broken visuals shown to learners (per run) | 3, 2, 2 (**7** total) | **0, 0, 0** |
| Visual tasks published (of 10, per run) | 7, 5, 8 | 9, 9, 11 |
| Conversational edit passed | 0 / 3 (no edit support; a new unrelated visual at best) | **3 / 3** |
| No-visual turn without a model call | 0 / 3 | 3 / 3 |
| Simple chart passed | 0 / 3 (console errors shown) | 3 / 3 |
| Pendulum period check passed | 1 / 3 | 3 / 3 |
| Median time to published visual (s, per run) | 21, 30, 31 | 60, 143, 71 |
| Input / output tokens per run | ~77K / ~29K | ~201K / ~65K |

Tasks that never passed in either configuration: the neural network (the step control or its labeling fails the check), the 3D scene (planets unlabeled), the dashboard and the heat pump (filter coordination, sample-data labeling and COP checks). These are model-quality limits, not pipeline failures: in C they publish as working visuals that miss part of the brief. One earlier, pre-freeze sample of C passed transmission line, dashboard and heat pump, so failures move between runs. C's 143 s median coincided with a period when the free provider was markedly slower for every task; latency comparisons are only meaningful within one session.

Earlier samples of the improved pipeline during development (re-scored with the final verifier and checks) passed 8, 7 and 6 of 12, consistent with the final-code samples.

### What the comparisons show

- **A vs. B (model only):** the configured Ultra endpoint truncates forced tool arguments at 1,024 characters, so nothing usable is produced. Switching to Super alone raises publication from 1 to 7 of 10 but still ships 3 broken visuals and passes only 2 tasks end to end.
- **B vs. C (architecture only, same model):** runtime verification removes every broken published visual (3 → 0); repair recovers failures that previously ended the run (invalid JavaScript, provider stalls, empty responses); tasks passing every check rise from 2 to 7; controls that actually work rise from 1/10 to 16/18; the larger output budget lets single generations exceed the old 8,192-token cap (B's binary search tree was truncated exactly at 8,192). The text-decision path saves a ~6K-token model call per non-visual turn.
- **C vs. D (model only, same architecture):** Cohere's code model streams arguments sooner but hit intermittent provider HTTP 400s on 7 calls (replaying the captured requests later succeeded) and produced fewer working visuals. Nemotron Super is the better free choice measured here.

### Costs of the improvements

- **Latency:** median time to a published visual rises from 21 s (B) to 60 s (C). The causes are verification (about 8.5 s per candidate), repair attempts (6 of 11 visual runs), and longer, more complete artifacts. The explanation is never delayed, because visuals run in a separate job. The preview appears when the model's arguments arrive: Nemotron Super sends them all at the end, so the median first preview is 30.5 s.
- **Tokens:** about 2.6× input and 2.3× output tokens versus B, mostly from repairs that replay the previous candidate. This is $0 on free models. On a paid model, budget about 3× the per-visual cost of the original pipeline.

## 4. Per-task results (configuration C)

| Task | Outcome | Notes |
| --- | --- | --- |
| Gradient descent | passed (objective) | learning-rate change changes the output; repaired once. **Human review: poor**: the loss curve is drawn inverted with oversized strokes (coordinate-scaling bug) |
| Pendulum | passed (objective) | displayed period within 8% of 2π√(L/g) at default and maximum gravity. **Human review: poor drawing**: the string is drawn about 20 px for 1 m |
| Circuit | passed (objective) | displayed current matches I = V/R. **Human review: poor**: the diagram is not recognizable as a battery and resistor |
| Neural network | published, task check failed | step-through diagram with weights; "next step" did not change visible state in the check; labels overlap (see section 5) |
| Binary search tree | passed | inserting then deleting a value changes the rendered tree |
| 3D scene | published, task check failed | real orbiting scene with camera controls (OrbitControls); planets unlabeled |
| Transmission line | not published | failed runtime verification on all three attempts (withheld rather than shown broken) |
| Dashboard | not published | failed runtime verification on all three attempts |
| Heat pump (unseen) | published, task check failed | all four stages labeled; COP not computed across the requested temperature range |
| Simple chart | passed | repaired once |
| No visual needed | passed | skipped without a model call |
| Conversational edit | passed (objective) | revised the existing pendulum from its source: damping added, gravity and length kept, lineage recorded, 60 s; inherits the parent's drawing-scale problem |

In the other improved samples, transmission line and dashboard did publish and pass their checks (Γ within 0.03; filter updating two charts), and the heat pump passed. Failures move between tasks from run to run; no task is consistently impossible.

## 5. Subjective quality, correctness limits and the screenshot-judge experiment

This is a human judgment from the saved desktop, mobile and dark screenshots of the nine visuals configuration C published.

| Rating | Visuals |
| --- | --- |
| Good | simple chart (title, explanation, labeled axes); binary search tree |
| Fair | neural network (structure correct; weight labels overlap each other and node names); 3D scene (real orbiting scene, planets unlabeled and too dark); heat pump (coherent cycle; COP 13.4 at 0 °C is physically bounded but near the Carnot limit, unrealistic for real devices) |
| Poor | gradient descent (loss curve inverted and drawn with oversized strokes); circuit (correct current, unrecognizable diagram); pendulum and its edited version (correct period, 1 m string drawn about 20 px long) |

What this means:

- **Reliability improved far more than craft.** The pipeline no longer shows broken visuals, and the numbers it is checked against are right. But 4 of 9 published visuals depict their concept badly, and headings and "what to notice" text are usually missing despite the quality contract. Text stays readable in the dark theme (contrast is checked); drawings carry the same problems in both themes. This is the ceiling of a free mid-size model.
- **Objective checks overstate quality.** All four "poor" visuals passed every automated check: controls respond, readouts change, values are numerically right. Drawing correctness (scale, orientation, recognizability) is not observable from the DOM.
- **Scientific semantics are only partly automatable.** The checks verify the formulas they target, and the verifier catches NaN or Infinity at control extremes. In an earlier run, though, a heat-pump visual passed its checks while stating that heat "cannot be pumped from colder to hotter", which is backwards. Topics that matter need domain checks or human review.

**Screenshot-judge experiment (spec section 7).** I tested whether a free multimodal model could flag the "poor" visuals from screenshots, using the nine reviewed images as ground truth. `google/gemma-4-31b-it:free` was rate-limited (HTTP 429) on every request, including a later retry. `thinkingmachines/inkling:free` refuses API use outside agentic harnesses (HTTP 403). `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` rated the broken gradient-descent plot and the mis-scaled pendulum 5/5 and acceptable, and took 244 s on one call. No judge was built into the pipeline: with the models available here it would add latency without catching the defects. The rubric and procedure are recorded in this section, so a paid multimodal model can be evaluated against the same labeled set before anyone adopts it.

**Recommended next steps, in order of expected impact:**

1. Try a stronger visual model; the benchmark measures the change.
2. Add a reviewed multimodal judge if one passes the labeled set.
3. ~~Add an overlapping-text check to the verifier.~~ Done after the measured runs: `overlapping_text` is a repairable warning (it flags the neural network's colliding labels, and none of the other eight published visuals).
4. Add domain checks for priority topics.

## 6. Automated tests

| Suite | Result |
| --- | --- |
| `backend/tests/test_visual_verification.py` (real Chromium: defects incl. collapsed and clipped graphics and edge-value readouts, idioms, network block, timeouts, contrast, overlapping text, state replay) | 22 passed |
| `backend/tests/test_visual_repair_loop.py` (scripted runtime: continuation, fallback, budgets, stalls, failures during polish, empty responses, usage finality) | 12 passed |
| `backend/tests/test_visual_editing.py` (edit targets, declared edits, carried state, lineage ownership) | 8 passed |
| `backend/tests/test_visual_science.py` (correct vs wrong physics for pendulum, Ohm's law, projectile, neuron; worked examples; formula text; empty readouts) | 9 passed |
| `backend/tests/test_visual_judge.py` (off by default, warning-only, bounded image billing, metered call, receipt settlement) | 8 passed |
| `backend/tests/test_visual_metering.py` (receipt drained after early disconnect, cancelled generations aborted, rejected requests settle at zero) | 4 passed |
| Existing visual suites (`test_openintelligentui`, `test_visual_runs`, `test_visual_code`, `test_visual_pricing`, `test_visual_media_boundary`, `test_visualization_models`) | all passed |
| Frontend visual tests (`web/tests/generated-visual*.test.tsx`, `generated-trip`) | 19 passed |
| Usage, voice and generation suites | 127 passed; 9 failures that fail identically on unmodified `main` (`test_usage_parsing` ×3, `test_usage_summary` ×5, `test_generation_web_search_events` ×1) |
| TypeScript (`tsc --noEmit`) on touched files | no errors |
| ESLint on touched files | no errors (one pre-existing upstream warning) |

## 7. Security validation

| Property | Evidence |
| --- | --- |
| Learner-facing isolation unchanged | Same opaque `allow-scripts` iframe and CSP (`connect-src 'none'`); frontend test asserts the CSP. |
| Verifier cannot reach the network | `test_network_is_blocked_and_reported`: a CSP-permitted image host is still aborted by the verifier's route block; disallowed hosts are refused by the frame CSP first. |
| Hostile scripts cannot hang the service | `test_blocking_script_times_out_without_hanging_the_verifier`: an infinite loop is reported as `script_timeout` within 15 s and the shared browser keeps working. |
| Verifier faults never publish or reject on their own | Unavailable/faulted verification returns `unavailable`; publication falls back to static validation and logs it (`test_unavailable_verifier_degrades_without_raising`). |
| Chromium OS sandbox | Launched with `chromium_sandbox=True` on this machine. Not verified inside the Linux container (Docker was not running); if user namespaces are unavailable there, verification reports `browser_unavailable` rather than silently running unsandboxed. |
| Edit source is owner-scoped | Edit targets come only from the learner's own journey; `editOf` is honored only for the offered id; commit re-checks the parent's owner and conversation (`test_commit_keeps_lineage_only_for_an_owned_parent_in_the_session`). |
| No new credentials or data in sidecars | Unchanged ticket model; verification and repair run in the API process. Persisted verification summaries contain only status, finding codes, digest and duration. |
| Debug artifacts | Candidate/event/request dumps require `OPENLEARN_VISUAL_DEBUG_DIR` and a development environment; disabled otherwise. |

## 8. What could not be verified here

- **Container image.** The Dockerfile now builds library modules and the verification kit from the web lockfile; Docker was not running on this machine, so the image build and in-container Chromium sandbox were not tested.
- **Paid models.** No paid visual model was enabled (requires an approved tariff and your decision on spend). Free models are rate-limited and vary between runs.
- **Hosted deployment, live microphone voice edits, and the web UI in a real browser session** were not exercised in this work; frontend behavior is covered by component tests.
- **Sample size.** B and C were each run three times (A and D once). Per-task outcomes vary between runs, so differences of one or two tasks within a configuration are noise; the B-to-C difference (2.3 to 7.0 tasks, 7 to 0 broken visuals) held in every run.

## 9. Follow-up: paid models, screenshot judge and science checks

Measured 12 October 2026 (afternoon). Real OpenRouter spend for everything in this section was about $0.30. The local ledger recorded more, because of the metering defect described below, and reached the configured $1/day platform cap, which ended live runs for the day.

### 9.1 Which models can produce visuals

Visual generation forces a named `generateSandboxedUi` tool call. Each candidate was probed with a forced call that needs a long string argument:

| Model | Price per M tokens (in / out) | Forced tool call | Notes |
| --- | --- | --- | --- |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | free | **broken**: empty or 1,024-character arguments | original configuration |
| `nvidia/nemotron-3-super-120b-a12b:free` | free | works (30 KB) | arguments arrive all at once (no progressive preview) |
| `anthropic/claude-haiku-5.5` | $0.10 / $0.50 | works (10 KB in 13 s, streamed from 1.4 s) | only without OpenRouter's `require_parameters` routing flag, which rejects every Anthropic endpoint |
| `anthropic/claude-sonnet-5.5` | $2 / $10 | **refused**: "tool_choice type tool/any not supported"; reasoning is mandatory and cannot be disabled | needs `OPENLEARN_VISUAL_TOOL_CHOICE=auto` (implemented) |

Changes made: `OPENLEARN_VISUAL_REQUIRE_PROVIDER_PARAMETERS` (default `true`; set `false` for Anthropic models) and `OPENLEARN_VISUAL_TOOL_CHOICE=named|auto` (default `named`; `auto` instructs the model to answer only with the tool, and the orchestrator retries a run without an artifact).

**Sonnet 5.5 was not benchmarked.** With a 16K output limit and ~50 KB inputs, the ledger reserves about $0.56 per Sonnet call before dispatch, which the $1/day platform cap does not allow alongside other use. Raising `OPENLEARN_PLATFORM_DAILY_BUDGET_USD` is your decision; the configuration is otherwise ready.

### 9.2 Haiku 5.5 results

| Run | Published | All checks passed | Median total (s) | Median first preview (s) | Real cost |
| --- | --- | --- | --- | --- | --- |
| E: Haiku producer | 9 / 12 | 3 / 12 | 38.8 | 9.2 | ≈ $0.07 |
| F: Haiku producer + Haiku judge, all new checks | 10 / 12 | 5 / 12 | 40.8 | 9.2 | ≈ $0.05 |
| C (reference): Nemotron Super, free | 9–11 / 12 | 6–8 / 12 | 60–143 | 28–85 | $0 |

Haiku is about 1.5× faster end to end and shows a progressive preview within ~9 s because it streams tool arguments. On objective checks it does **not** beat the free Nemotron Super model yet, for two measured reasons:

1. **Repair and polish continuations fail with HTTP 400 for Claude.** The first attempt works, but every follow-up request that carries Haiku's own previous tool call is rejected, so warnings are never polished and errors never repaired. The identical message shape built from a Nemotron history is accepted by Haiku (verified by replay), so the cause lies in how a streamed Claude tool call is recorded in the history. The proxy now logs the provider's error detail, so the next paid run will name the rejected field. Root cause not yet confirmed.
2. **Haiku did not declare the conversational edit** (`editOf`), so the edit task produced a new visual without lineage.

Recommendation: keep `nvidia/nemotron-3-super-120b-a12b:free` as the visual model for now. Re-evaluate Haiku once the continuation 400 is fixed, and Sonnet once the platform budget allows it.

### 9.3 Screenshot judge (paid models)

Against the nine human-labeled screenshots from section 5:

| Judge | Agreement with human labels | Poor visuals rejected | Cost per judgment | Latency |
| --- | --- | --- | --- | --- |
| `anthropic/claude-haiku-5.5` | 5 / 9 | 4 / 4 | ≈ $0.0002–0.001 | ≈ 3 s |
| `anthropic/claude-sonnet-5.5` | 5 / 9 | 4 / 4 | ≈ $0.003–0.004 | ≈ 3 s |

Both judges rejected every visual the human rated poor, with accurate reasons ("the parabola opens downward", "the string is a ~15 px stub for a 1 m pendulum", "no closed loop"). They also rejected the four visuals the human rated "fair", citing genuine defects the human had accepted: overprinted labels, an empty tree canvas, invisible planets, arrows ending in empty space. That is too strict for a publication gate (8 of 9 rejected), but precise feedback for repair. The judge is therefore integrated as a **repairable warning** (`visual_quality`) for the one polish attempt and never blocks publication. It is off unless `OPENLEARN_VISUAL_JUDGE_MODEL` is set with a reviewed tariff. Images are billed against an explicit bound: the screenshot is cropped to 720×1200 and reserved at 2,000 tokens. In run F the judge flagged 9 first attempts; the polish that should have used its feedback was blocked by the Claude continuation defect above, so judge-driven improvement is not yet measured.

### 9.4 Science checks

Topic validators (`backend/app/visual_science.py`) run inside the rendered visual for the product's priority topics, taken from the original approved simulations (gradient descent, projectile motion, Ohm's law) and the neural-network domain pack (neuron activation), plus pendulum and transmission-line reflection. A check fails only when it can read the visual's own labeled controls and readouts, and no labeled value matches the governing formula.

Validation over 44 stored artifacts from all benchmark runs: **24 pass, 18 unmeasured, 2 fail**. Both failures are genuine defects:

- an original-pipeline pendulum displayed a period of 0.03 s where 2π√(L/g) = 2.007 s;
- a Haiku transmission line whose value readouts were never populated, so the only Γ values on the page were explanatory examples.

Validation also exposed two false positives in the first version of the checks. Formula text (`e^(−j2βl)` read as Γ = 2) and worked examples (`so Γ = 0`) were mistaken for values. Both were fixed by requiring `label = value` readouts and by passing when any labeled value matches. Tests pin both cases.

A related generic check, **value displays still empty after setup** (`empty_readout`, a repairable warning), flagged exactly 1 of 101 stored artifacts, that same transmission line, with no false alarms.

### 9.5 Metering defects found and fixed

- **Lost receipts.** CopilotKit ends the agent's read at the tool call, before the provider's trailing usage chunk, so many calls settled at the full conservative reservation (about 10× their real cost; for run E, $0.39 recorded against about $0.07 spent). This over-charges learner allowances and the platform budget, and likely contributes to the finding that the free plan covers only about three visuals per window. The proxy now drains a *finished* generation for its receipt after the client leaves (bounded to 30 s), and aborts an unfinished one, so a cancelled visual is not completed or billed further.
- **Rejected requests.** A provider rejection before generation (HTTP 4xx/5xx) kept the reservation; it now settles at zero, matching what the provider bills.

Both are covered by `backend/tests/test_visual_metering.py`. Polish calls that end in an upstream error still settle conservatively, as designed.
