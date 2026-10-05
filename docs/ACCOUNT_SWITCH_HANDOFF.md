# Open Learn account-switch handoff

Saved 4 October 2026 at the user's request to stop work and conserve account usage. The milestone 3 subagent was interrupted. Resume from the files on disk in `C:\Projects\AI Tutor harness`; do not rely on the old account's subagent session being recoverable.

Checkout at save time: branch `codex/openlearn-2-local-checkpoint-20261003`, HEAD `b71458c32e6985027df53659e6253678c59694e5`. Progress is in the working tree, including untracked source files, and was not committed or pushed. Keep this local project directory intact across the account switch.

## User objective and current scope

Implement `Open Learn 2.0/26_agent_execution_platform.md` incrementally. Functionality comes before a full Grok/iMessage UI redesign. The user authorized milestones 1, 2 and 3 and explicitly requested subagent delegation. No commit, push or deployment is authorized for these current implementation changes. Preserve unrelated pre-existing modifications. The workspace contains extensive uncommitted and untracked work; do not reset, clean, overwrite, or assume everything belongs to milestone 3.

## Completed baseline

Milestone 1 backend/web foundation and milestone 2 research are implemented. Read `docs/AGENT_EXECUTION_FOUNDATION.md` and `docs/AGENT_RESEARCH_IMPLEMENTATION.md`.

Final baseline checks: 9 foundation cases and 19 research cases passed after the last cleanup fixes. Broader backend previously passed 50 cases with one skip; affected frontend 14 cases, TypeScript, production build and deterministic real-browser flows passed. Browser reload restored task history. Downloads returned HTTP 200 and HTTP file validation passed, but the browser saved-download bridge timed out. Those results precede milestone 3 changes and are not proof that the present milestone 3 tree is fully validated.

Migrations: 0041 browser, 0042 foundation, 0043 research. Existing Python/FastAPI/SQLAlchemy architecture is deliberate; extend it rather than switching to eve. The foundation and research live in `backend/app/agent_execution/` and share the existing `assistant_runs`, owner boundaries, WorkflowStore and ObjectStore.

## Milestone 3 progress at interruption

Subagent: `/root/daytona_teaching_milestone`. Its final messages report:

- Implemented `sandbox_lab` capability, lazy resource leases, bounded remote code and data transfer, independently checked CSV/chart/workbook/report outputs, durable cache, cleanup and restart reconciliation.
- Added `learning.py` teaching/quiz continuation using existing JourneyService, AssessmentService and QuizService. Agent work must never generate learner mastery or assessment performance evidence.
- Added migration `backend/migrations/versions/0044_agent_sandbox_learning.py`.
- New modules include `daytona_adapter.py`, `sandbox.py`, `sandbox_config.py`, `sandbox_inputs.py` and `learning.py` under `backend/app/agent_execution/`.
- Edited shared contracts/coordinator/config/routes/worker/artifacts and account/material lifecycle integration. Inspect their actual diffs before further changes.
- Added `backend/requirements-daytona.txt`, `backend/scripts/agent_sandbox_preview.py` and `backend/tests/test_agent_sandbox_learning.py`.
- Reported installed Daytona SDK 0.220. Server process did not have `DAYTONA_API_KEY`; no live Daytona acceptance was performed. Never reuse or copy the historical credential in this chat. Obtain configuration through the normal server-only environment.
- Reported 12 sandbox cases plus foundation 9 and research 19 passed together (40 total). Later reported 20 sandbox/learning cases passed, including HTTP, Journey preparation/commit, learner evidence watermark fences, existing quiz learner-answer path, account erasure and daily creation budgets.
- Last task was adding owned CSV `materialVersionId` intake and source deletion invalidation. Two additional tests are now on disk: `test_owned_material_csv_lineage_and_source_deletion` and `test_assessment_source_cannot_enter_sandbox`. Their final result has NOT been reported; verify before claiming success.
- Frontend files currently show `sandbox_lab` selection and a learning-continuation panel. Inspect `web/components/assistant/execution-panel.tsx`, `learning-continuation.tsx`, `web/lib/assistant-client.ts` and `web/tests/agent-learning.test.tsx`. Their milestone 3 verification status is not established by this handoff.

## Current API and configuration

The backend contract reported by the agent: `POST /v1/assistant/tasks/{id}/continuations`, body `{kind: 'teach' | 'quiz', expectedRevision: number}`, stable `Idempotency-Key`, returns a continuation containing id/kind/status and optional lesson/quizId/errorCode. `GET` at the same path returns `{items: []}`. Confirm exact code and real quiz navigation before UI changes.

Sandbox setup uses `OPENLEARN_SANDBOX_ENABLED`, `OPENLEARN_DAYTONA_SNAPSHOT` and server-only `DAYTONA_API_KEY`. Configuration also includes timeout/lifetime and per-owner/global daily creation limits. The trusted remote generator uploads data separately, blocks sandbox network, records code/input hashes and snapshot/runtime receipts, and copies outputs before resource release. Review actual adapter compatibility against official Daytona documentation before live use. Offline adapters must be visibly labeled and rejected in production.

## Resume checklist

1. Read applicable AGENTS.md, main architecture brief and both completed evidence documents. Inspect the uncommitted milestone 3 files and migration; do not reimplement the completed baseline.
2. Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_agent_sandbox_learning.py backend/tests/test_agent_execution.py backend/tests/test_agent_research.py -q --tb=short -p no:cacheprovider -p no:tmpdir`. Investigate failures and complete owned-material transfer/deletion checks. Do not claim the latest suite passed based on the earlier 20-case report.
3. Verify continuation idempotence, owner access, source/assessment revocation, no agent-created mastery, crash recovery, ambiguous-create reconciliation without a duplicate resource, output validation, pause/cancel and cleanup after late writes. Check migration upgrade/rollback, account export/delete/import exclusions and remote cleanup obligations.
4. Finish and verify the minimal frontend integration: setup readiness, sandbox CSV request, clarification replies, teach/quiz controls, actual existing quiz route, reconnect and source/file controls. Run affected Vitest cases, TypeScript, targeted lint and production build. Existing `npm run test:agent` does not necessarily include the new learning suite; inspect/update it appropriately.
5. Use the isolated offline preview script for real browser acceptance, visibly label synthetic evidence and stop all temporary services afterward. Check whether a previous preview process is still running before starting another; no final process-cleanup report was received from the interrupted milestone 3 agent.
6. Run live Daytona only with valid configured credentials, a pinned compatible snapshot, explicit bounded cost and guaranteed resource cleanup. Do not execute arbitrary generated code locally. If unavailable, record live acceptance as a release gate. PostgreSQL concurrency and hosted deployment remain unverified gates.
7. Create `docs/AGENT_DAYTONA_IMPLEMENTATION.md` with exact implementation, actual test outcomes, configuration and remaining gates. Update the main brief's milestone 3 status only after verified work. No milestone 3 completion report was issued before this pause.

## Environment notes

Windows PowerShell; repository Python is `backend/.venv/Scripts/python.exe`. Existing pytest temporary folders can hit Windows ACL errors; earlier deterministic fixtures use unique writable workspace directories, and existing tmpdir/Vite helper restrictions needed approved escalation. These are setup failures, not passes. Do not erase unrelated test directories or user data to work around them. No provider secrets are included in this handoff.

Suggested resume request: “Read docs/ACCOUNT_SWITCH_HANDOFF.md and resume milestone 3 from the saved working tree. Complete and verify the unfinished Daytona/teaching work without reverting existing changes.”

## Resume outcome (4 October 2026)

Milestone 3 resumed from disk and implemented locally. Read `docs/AGENT_DAYTONA_IMPLEMENTATION.md` for actual code/contracts/tests and precise remaining live-provider/PostgreSQL/hosted gates. The earlier interrupted test counts above are historical; final sandbox suite has 24 passing cases including owned-material and late-upload cleanup. Frontend suite has 13 passing cases; TypeScript, targeted lint and production build passed. Migration0044 upgrade/rollback/re-upgrade passed. No commit/push/deploy or historical credential reuse occurred.
