# Visual model routing: technical plan

Status: proposal, not implemented. Written 12 October 2026.

## 1. Goal and non-goal

**Goal.** Choose the visual model for each request *before* generation starts. A small, cheap model such as Claude Haiku 5.5 handles most visuals. Requests that need a stronger model, such as Claude Sonnet 5.5, go straight to it.

**Non-goal: escalation after failure.** The router will not send a request to Haiku, wait for it to fail verification, and then retry on Sonnet. Each run uses one model from start to finish. Repair and polish attempts continue on the same model and the same thread, as they do today.

Reasons for routing up front rather than escalating:

- **Latency.** Escalation adds a full failed Haiku run (about 40–70 s) before the Sonnet run starts, for exactly the requests that are already slowest.
- **Cost.** The failed attempts are still paid for.
- **Predictability.** One model per run keeps the learner's progressive preview, the ledger reservation and the audit trail simple.

## 2. What exists today

| Concern | Today | File |
| --- | --- | --- |
| Model choice | One global `OPENLEARN_VISUAL_MODEL` | `backend/app/openintelligentui.py` `readiness()`, `integrations/openintelligentui/agent.py` |
| Model enforcement | The proxy rejects any `payload.model` other than the configured model (`visual_model_denied`) | `openintelligentui.py` `model_proxy` |
| Tool-choice mode | Global `OPENLEARN_VISUAL_TOOL_CHOICE=named\|auto`; Sonnet needs `auto` | `agent.py` |
| Provider flag | Global `OPENLEARN_VISUAL_REQUIRE_PROVIDER_PARAMETERS`; must be `false` for Anthropic | `openintelligentui.py` |
| Pricing | `approved_visual_tariff(model, role)` accepts only the one configured producer model | `backend/app/visual_pricing.py` |
| Run admission | `VisualRuns.admit(...)` builds the brief and edit target, then queues a job | `backend/app/visual_runs.py` |
| Per-run authority | HMAC ticket `{owner, generationId, lease, exp}` | `openintelligentui.py` `issue_ticket` |
| Outcome signals | Every artifact stores a verification report, science check results and the model in the usage ledger | `visual_verification.py`, `visual_science.py`, usage ledger |

The outcome signals already exist. The missing pieces are per-request model selection and a policy that decides it.

## 3. Design

```
question + brief + edit target + learner plan + budget headroom
        │
        ▼
 classify()  ──►  TaskProfile {category, signals}
        │
        ▼
 route()     ──►  RouteDecision {tier, model, toolChoice, reason, policyVersion}
        │            (stored on the job; signed into the ticket)
        ▼
 generate()  ──►  one model for every attempt in this run
        │
        ▼
 verification outcome + cost  ──►  routing metrics per (category, tier)
                                    └─► offline report proposes the next policy version
```

### 3.1 Model tiers (configuration)

Replace the single model setting with a tier registry. Keep the old variable as a one-tier fallback.

```json
OPENLEARN_VISUAL_MODEL_TIERS = {
  "standard": {"model": "anthropic/claude-haiku-5.5",  "toolChoice": "named", "requireProviderParameters": false},
  "advanced": {"model": "anthropic/claude-sonnet-5.5", "toolChoice": "auto",  "requireProviderParameters": false}
}
OPENLEARN_VISUAL_ROUTING_POLICY = "rules-v1"   # or "single" to disable routing
```

- Every tier model must have a reviewed entry in `OPENLEARN_VISUAL_MODEL_TARIFFS`.
- `readiness()` reports a missing tariff for any tier, not just one.
- `approved_visual_tariff()` accepts any model in the registry for the producer role.

### 3.2 Classifier: `classify(question, brief, edit_target) -> TaskProfile`

New module `backend/app/visual_routing.py`. Version 1 is deterministic: rules only, no model call, so it adds no cost and no latency.

| Category | Signals (question, brief title, visual type, sources) | Benchmark tasks |
| --- | --- | --- |
| `scene_3d` | 3D, three-dimensional, rotate or orbit the camera, solar system, molecule, lattice, `visualType` 3D | `scene_3d` |
| `coordinated_views` | dashboard, linked or coordinated charts, filter across views, compare several datasets | `dashboard` |
| `algorithm_stepper` | step through, insert or delete, traverse, forward or backward pass, sort, search tree | `neural_network`, `binary_search_tree`, `gradient_descent` |
| `science_simulation` | `visual_science.topics_for()` matches (pendulum, Ohm's law, projectile, reflection, neuron, gradient descent) or a named physical law | `pendulum`, `circuit`, `transmission_line`, `heat_pump` |
| `chart_or_diagram` | a single chart, a labelled diagram or a formula explorer | `simple_chart` |
| `edit` | an `editTarget` was offered (records the parent's tier and source size) | `edit_pendulum` |

`TaskProfile` also records the raw signals that fired, so each decision can be explained and audited. A cheap model-based classifier (Haiku with a JSON answer, about $0.0003 a call) is an option for later. It should be added only if the rules measurably misroute requests in the logs.

### 3.3 Policy: `route(profile, context) -> RouteDecision`

Rules are applied in order, and the first match wins:

1. **Routing disabled** (`policy = single`): use the standard tier.
2. **Plan gate:** a learner whose plan does not include advanced visuals gets the standard tier, with reason `plan`.
3. **Budget gate:** if the platform's remaining daily or monthly budget, or the learner's allowance, cannot cover the advanced tier's worst-case run (its reservation × `maxAttempts`), use the standard tier, with reason `budget`. Routing never raises a budget cap.
4. **Edits:** stay on the parent artifact's tier unless rule 5 sends the category higher. A model then revises code written in its own idiom.
5. **Category table:** look up `profile.category` in the policy table.
6. **Default:** use the standard tier.

The category table is data, not code. It ships as a versioned file, for example `backend/app/visual_routing_policy.json`, and has a `policyVersion`:

```json
{"policyVersion": "rules-v1-2026-10",
 "categories": {"scene_3d": "advanced", "coordinated_views": "advanced",
                "algorithm_stepper": "standard", "science_simulation": "standard",
                "chart_or_diagram": "standard", "edit": "inherit"}}
```

The values shown are placeholders. Section 5 explains why they cannot be filled in yet.

### 3.4 Carrying the decision to the model call

The sidecar should not choose the model itself. The decision is made in the API and enforced by the proxy:

1. `VisualRuns.admit()` calls `classify` and `route`, then stores `route` on the job payload and on the run record.
2. `issue_ticket()` adds `model` and `toolChoice` claims. The HMAC already prevents tampering.
3. The agent always sends a fixed alias, `openlearn-visual`, with named tool choice. Its system prompt always includes the auto-mode instruction "answer only with the tool", which does no harm in named mode.
4. `model_proxy` replaces the alias with the ticket's model. For an `auto` tier it rewrites `tool_choice` to `"auto"` and applies that tier's provider flag. A request for any other model is still denied (`visual_model_denied`).
5. The orchestrator already retries a run that ends without an artifact. That covers the rare case where a model in auto mode answers in text.

This keeps model authority in one place, the API. It needs no per-run model plumbing in the LangGraph sidecar and no CopilotKit changes.

### 3.5 Recording and observability

- Add `production: {tier, model, category, reason, policyVersion}` to `GeneratedVisual`, next to `lineage` and `verification`, so every artifact records why it was built the way it was.
- The usage ledger already records the model per call. Add `routeTier` and `category` to the visual usage context.
- Add a metrics query or report (`backend/scripts/visual_routing_report.py`) with one row per (category, tier). Columns:
  - runs;
  - published rate;
  - all-checks-passed rate;
  - mean repair attempts;
  - p50 and p90 time to first preview and to completion;
  - real cost per published visual;
  - cost per *passing* visual, the main efficiency number.

### 3.6 How the policy improves (measured, human-approved)

1. The report is computed from production verification outcomes, using the same checks as the benchmark. Results are measured, not guessed.
2. A category moves to `advanced` when the standard tier's all-checks rate is below a threshold, for example 60%, over at least N runs (for example 30), *and* the advanced tier's measured rate is meaningfully higher.
3. A category moves back to `standard` when the standard tier's rate catches up. That happens as models, prompts or the quality contract improve.
4. Version 1 does not change the policy automatically. The report proposes a new `policyVersion` and a person approves it, because each move changes spend.
5. **Optional exploration** (later, behind a flag, budget-capped): send a small share of requests, for example 5%, in a category to the other tier, so both tiers keep producing comparison data. Without it, an `advanced` category never collects fresh `standard` data.

## 4. Cost and budget implications

- Today's reservation for a Sonnet call is about **$0.56**, from 16K maximum output plus the conservative input estimate. Against the current $1/day platform cap, the budget gate (rule 3) would allow at most one advanced run per day, and only when nothing else has spent.
- Real Sonnet spend per run is probably far lower, based on Haiku's measured 5–7K output tokens per call. That has not been measured for Sonnet.
- Before advanced routing is useful, one of these is needed. Each is your decision; this plan does not change any cap.
  - Raise `OPENLEARN_PLATFORM_DAILY_BUDGET_USD` and `OPENLEARN_PLATFORM_MONTHLY_BUDGET_USD`.
  - Lower `OPENLEARN_VISUAL_MAX_OUTPUT_TOKENS` for the advanced tier only (a per-tier `maxOutputTokens`), which shrinks its reservation. This needs measured Sonnet output sizes first, so that real visuals are not truncated.
  - Limit advanced routing to paid plans (rule 2).

## 5. Rollout

**Phase 0: data, before any code.**

- Rerun the Haiku benchmark with the `jsExpressions` recovery fix (commit `ae52add`). All Haiku per-category numbers so far were measured *before* that fix. In those runs, Haiku's start-up code was dropped in most visuals, so its controls appeared dead. Its weak categories (3D, dashboard, algorithm steppers) may change substantially.
- Run Sonnet once on the benchmark, after a budget decision (section 4).
- Grow the benchmark from 12 tasks to about 4–5 tasks per category, so the per-category rates mean something.
- Output: the first real category table.

**Phase 1: plumbing, with routing off.**

- Add the tier registry, ticket claims, proxy alias rewrite, the `production` field and ledger tags.
- Ship with `OPENLEARN_VISUAL_ROUTING_POLICY=single`. Behavior stays identical; tests prove the proxy denies untiered models and that `auto` tiers get `tool_choice: auto`.

**Phase 2: rules-v1.**

- Add the classifier and policy with the Phase 0 table, plus the budget and plan gates.
- Run the benchmark in routed mode (`--route`).
- Acceptance: the routed configuration beats the best single model on *cost per passing visual*, and does not lose on the all-checks rate.

**Phase 3: feedback loop.**

- Add the production routing report, the human-approved policy versions and, optionally, exploration.

## 6. Tests

- **Classifier:** a table test over the benchmark prompts and real past questions. Each must map to the expected category, and negative cases must stay `chart_or_diagram` or the default.
- **Policy:**
  - the order of the gates;
  - the budget gate never selects a tier it cannot reserve;
  - edits inherit the parent's tier;
  - an unknown category falls back to the default.
- **Proxy:**
  - the alias is rewritten to the ticket model;
  - any explicit model is denied;
  - a tampered ticket is denied;
  - `auto` tiers send `tool_choice: auto`, and named tiers send the named tool.
- **End to end** (mock runtime, as in `test_visual_repair_loop.py`): every attempt in a run, including repair and polish, uses the same model. There is no escalation path.
- **Ledger:** usage rows carry `routeTier` and `category`, and reservations use the routed model's tariff.

## 7. Open decisions (yours)

1. **Budget:** raise the platform caps, cap advanced output per tier, or restrict advanced visuals to paid plans.
2. **Advanced model:** Sonnet 5.5, or a cheaper mid-size model if one passes the forced-tool probe in evaluation section 9.1.
3. **Policy changes:** whether policy changes stay human-approved, which this plan recommends for version 1, or may later apply automatically within a spend limit.
