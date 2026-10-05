# Daytona sandbox and learning implementation

Live adapter acceptance update (4 October 2026): bounded Daytona create/stage/execute/download/delete now passed with independently validated four-file output and provider absence verified. Server configuration uses the tested `openlearn-csv-v1-20261004` snapshot. See [live acceptance evidence](AGENT_LIVE_ACCEPTANCE.md) for the command, earlier failures, retained image definition and remaining hosted PostgreSQL/S3/full-task gates. Historical local-only verification statements below describe the initial implementation run.

Implemented locally on 4 October 2026. This delivers slice 3's bounded CSV analysis and explicit teaching/quiz continuation on the existing FastAPI, SQLAlchemy, WorkflowStore, JourneyService and QuizService stack. Live Daytona and hosted PostgreSQL remain release gates. General arbitrary-code agents and the later native recording/UI milestones are outside this slice.

## Runtime and ownership

`backend/migrations/versions/0044_agent_sandbox_learning.py` follows 0043 and adds durable sandbox leases, account-erasure provider cleanup obligations, daily creation reservations and learning continuations. `backend/app/agent_execution/sandbox.py`, `daytona_adapter.py`, `sandbox_config.py` and `sandbox_inputs.py` implement lazy acquisition after clarification, immutable input revisions, owner-scoped CSV material intake, pinned runtime manifests, code/input hashes and execution receipts. Owned materials accept at most 50,000 UTF-8 bytes; answer keys and sample papers are denied. Course association, byte hash and ownership are checked. Source deletion invalidates derived downloads and clears retained CSV task content.

The adapter uses optional Daytona Python SDK 0.220.0 (`backend/requirements-daytona.txt`). It creates private, network-blocked sandboxes from a configured snapshot, stages data separately from trusted application code, runs a fixed bounded command remotely, checks fixed-path outputs and deletes compute. No generated arbitrary code executes on the API host. Policy limits default to 60 seconds execution, 900 seconds lease lifetime, 5 MB total output, two active resources per owner and 10 owner/100 global creations per UTC day. Atomic reservation receipts bound retries. Ambiguous creation is reconciled using a stable provider label; absence does not permit blind duplicate creation. Confirmed compute deletion can admit at most three numbered generations for a paused/restarted input.

Remote CSV, PNG, XLSX and JSON report are independently recomputed and checked before publication. Workbook archive expansion, entries and XML are bounded; chart bytes, CSV values/units/exclusions, worksheet data and report checks must match. Outputs are copied to the existing immutable ObjectStore before compute release; crash recovery reuses checked cached bytes. Immutable output keys are reserved before writes. Cancellation/account deletion during a late upload renews cleanup obligations. Cleanup, expiration, pause and deletion survive worker restarts; published artifact copies survive sandbox deletion.

Official contracts reviewed: [Daytona SDK](https://www.daytona.io/docs/python-sdk/sync/daytona/), [process](https://www.daytona.io/docs/python-sdk/sync/process/), [file system](https://www.daytona.io/docs/python-sdk/sync/file-system/), and [sandbox](https://www.daytona.io/docs/python-sdk/sync/sandbox/). Adapter construction was tested against SDK-shaped clients; this is not provider acceptance.

## Learning and frontend

`backend/app/agent_execution/learning.py` adds POST/GET `/v1/assistant/tasks/{id}/continuations`; POST requires `{kind: 'teach' | 'quiz', expectedRevision}` and `Idempotency-Key`. Only completed, verified, currently readable outputs qualify. Active quizzes/reviews deny new continuation. Durable jobs separate learning failure/retry from completed files. Teaching prepares and journals the existing Journey, then validates its learner watermark, current revision and source availability at commit. Crash recovery reuses that prepared snapshot. Quiz creation uses the current canonical graph and existing QuizService with explicit agent-result study provenance; it creates no attempts, grades or mastery evidence. Actual learner answers continue through existing assessment presentation/grading/assistance rules.

Shared `contracts.py`, `coordinator.py`, `config.py`, `routes.py`, `worker.py` and `artifacts.py` integrate `sandbox_lab` while retaining foundation/research behavior. Material and account deletion/export/import exclusions are registered in `material_service.py`, `identity_data.py` and `identity_import.py`. Provider cleanup handles persist beyond erased account content until successfully reconciled/deleted.

`web/components/assistant/execution-panel.tsx` provides sandbox readiness, CSV input, clarification, files and controls. `learning-continuation.tsx` provides explicit explanation/practice actions, polling, stable retry keys and the existing QuizWorkspace. Account changes invalidate pending views. Offline previews visibly identify synthetic sandbox and teaching data; production rejects test adapters.

## Configuration and verification

Configure server-only `DAYTONA_API_KEY`, `OPENLEARN_SANDBOX_ENABLED=true`, and `OPENLEARN_DAYTONA_SNAPSHOT` for a reviewed snapshot containing Python 3 and compatible trusted-runner dependencies. Optional timeout/lifetime/daily quotas are documented in `backend/.env.example`. Credentials never enter tasks, frontend environment, uploaded sandbox environment or evidence documentation. No historical chat credential was reused.

Latest meaningful checks:

- 24 sandbox/learning cases passed, including cancellation/account-erasure late uploads, source deletion, owned input, assessment exclusion, owner fencing, budgets, pause/restart, ambiguous creation, output corruption, cached recovery, real Journey commit, watermark changes and the existing assisted learner-answer path.
- Combined sandbox/foundation/research run passed 50 cases before the two additional late-upload cases; final sandbox rerun passed all 24 and final foundation/research rerun passed all 28 after those fixes (52 current cases across the final runs).
- Existing learning, assessment quality, control-plane and identity regression suites passed 31 cases.
- Frontend agent suite passed 13 cases, including four learning-continuation cases. Targeted ESLint and TypeScript passed; full production Vinext build passed all five stages.
- SQLite migration 0044 upgrade, rollback to 0043 and re-upgrade passed in an isolated database.

Reproduce backend: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_agent_sandbox_learning.py backend/tests/test_agent_execution.py backend/tests/test_agent_research.py -q --tb=short -p no:cacheprovider -p no:tmpdir`. Frontend: `npm run test:agent`, targeted ESLint, `npx tsc --noEmit`, `npm run build` from `web`.

`backend/scripts/agent_sandbox_preview.py` is an isolated offline acceptance CLI, not a production fixture endpoint. Start it with a new `--data work/<isolated-directory>`, set frontend `NEXT_PUBLIC_LEARNING_API_URL=http://127.0.0.1:8007`, run local web preview and open `/s/sandbox-preview-session`. Browser checks use actual APIs/stores with visibly synthetic providers.

Remaining gates: configure a valid server credential and pinned compatible snapshot; run one bounded paid create/stage/execute/download/delete acceptance and prove cleanup at provider; validate PostgreSQL concurrent reservations/leases under deployed supervision, S3 lifecycle and hosted auth/reconnect. No paid/live Daytona calls or deployment occurred. Browser download bytes were verified by API tests; OS saved-download behavior is separate from HTTP content verification. Browser acceptance details are appended below after final verification.

## Browser acceptance outcome

Real Chrome acceptance against isolated offline FastAPI/Vinext fixtures passed: sandbox selected, missing units clarified and answered, four verified output controls appeared, explanation completed with synthetic teaching content, practice quiz created through QuizService, existing QuizWorkspace authored a question, learner selected Doubles and declared outside help, feedback displayed Correct/Answered with help, and reload restored the completed task and quiz. Preview graph ownership grants were corrected before the final fresh quiz run; no fixture bypass was added to application authorization. An earlier incomplete fixture run failed graph authorization and is not counted as a pass. HTTP downloads were independently verified in API tests.

Browser proof: `work/agent-sandbox-browser.png` captures restored completed files and assisted learner feedback. All temporary preview services were stopped after verification.
