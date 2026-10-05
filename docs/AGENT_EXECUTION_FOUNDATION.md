# Agent execution foundation — implementation and evidence

4 October 2026. This records the selected first backend/web milestone. It does not certify the complete agent platform, native mobile capture, live Daytona or hosted release.

## Delivered vertical flow

- [x] Explicit capability admission into shared `assistant_runs`; ordinary tutor messages remain on their existing pathways.
- [x] Durable task, input question, reply plus steering, checkpoint and single final result.
- [x] Stable message/command identities, conflicting-content rejection and revision checks.
- [x] Pause, resume, cancel, cross-device answer, cursor replay and server-authoritative activity.
- [x] Exact lab fixture retains trials 1–2 and computes 5 cm/s after “centimeters; ignore trial 3.”
- [x] Readable immutable XLSX, labelled PNG and CSV saved separately from compute.
- [x] Crash after object write/reclaimed lease publishes one operation/output set/final item.
- [x] Stale worker, two claimants and concurrent input changes cannot publish an obsolete result.
- [x] Linked correction to meters preserves the old downloadable version.
- [x] Existing chat and compact tutor surfaces have minimal shared task controls; source inspection uses the research extension.
- [x] Authenticated HTTP ownership/old browser contract compatibility and SQLite migration roundtrip.
- [ ] Live Daytona execution and teaching/quiz continuation (slice 3).
- [ ] Native Expo, voice input and physical-device lecture capture (separate early mobile work).
- [ ] PostgreSQL two-process concurrency, hosted identity/storage and release rollout evidence.

## Runtime inventory and ownership

`assistant_runs.runtime_owner='browser_legacy'` is the additive default for existing rows; `agent_v2` identifies new runs. Legacy browser workers claim only existing browser job kinds; their stranded-task recovery explicitly excludes new runs. New worker jobs use `agent_step`, `WorkflowStore` claims, explicit job/input lease fencing and transactional `ExecutionOutbox` topic `agent.step`. Existing learning `execution.Outbox`/worker paths retain ownership; the same new obligation never enters both outboxes.

The v2 writer lock order is session → task → job; SQLite acquires a writer before aggregate reads and PostgreSQL uses session/task locks plus task CAS. Task and conversation event counters are atomic. Commands are applied at a database boundary and fence queued/running jobs before new scheduling. Providers and object writes run outside short transactions. Prepared artifact rows track orphan obligations before upload; stale/cancelled writers reset cleanup tombstones if an upload finishes after cleanup. Published immutable outputs are never overwritten.

`main.py` starts agent workers only in embedded mode, alongside the existing learning/browser owners. External mode uses `python -m backend.app.agent_execution.worker`; API processes do not start the legacy class-recording recovery threads. Legacy class-recording processing still requires its established owner; this milestone does not migrate that legacy subsystem to a new queue.

## Paths and schema

- Backend: `backend/app/agent_execution/{contracts,config,repository,coordinator,worker,tools,artifacts,routes}.py`.
- Migration: `0042_agent_execution_foundation`, following `0041_browser_assistant`; research migration `0043_agent_research` follows it.
- Shared storage: existing task IDs/events; new `agent_messages`, `agent_commands`, `agent_input_requests`, `agent_checkpoints`, `agent_operations`, `agent_artifacts`, `agent_activity`, `agent_activity_cursors`.
- Web: `web/lib/assistant-client.ts`, `web/components/assistant/execution-panel.tsx`, scoped CSS, integration in existing `learn-chat.tsx` and `compact-tutor-chat.tsx`.
- Tests: `backend/tests/test_agent_execution.py`, `web/tests/agent-execution.test.tsx`; existing browser/control-plane/recording/identity suites remain regression owners.
- Account export/delete includes artifact objects through the existing owner collector; import excludes runnable records/outbox state. Research source erasure and dependent output cleanup are documented separately.

The deterministic lab adapter is deliberately bounded: inline CSV `trial,distance,time`, unique integer trial IDs, finite nonnegative distances, positive seconds, at most 1000 rows. It recognizes centimeters/meters and explicit trial exclusions. It cannot run arbitrary generated code or handle arbitrary attachment formats. No external model/provider/sandbox call is required for this flow. Large or unsupported inputs fail clearly; file intake and Daytona are subsequent capabilities.

## Manual development use

Normal development: set `OPENLEARN_AGENT_ADMISSION_ENABLED=true` and use the existing API/web startup with the correct `NEXT_PUBLIC_LEARNING_API_URL`. Open a conversation, expand **Agent workspace**, choose **Lab CSV analysis**, keep or replace the fixture CSV, and select **Start task**. Answer the question using quick replies or text. Pause/resume/stop controls appear from allowed server commands. After completion, download files or submit “Use meters instead” to create a linked corrected result. The ordinary chat composer, Ask/Learn/Quiz and attachment flow are preserved.

For reproducible acceptance without touching the user's database or calling paid services, from repository root:

```powershell
backend/.venv/Scripts/python.exe -m backend.scripts.agent_foundation_preview --port 8006 --data work/agent-preview
```

In a second terminal from `web/`:

```powershell
$env:NEXT_PUBLIC_LEARNING_API_URL='http://127.0.0.1:8006'
npm run dev
```

Open `http://localhost:5173/s/agent-preview-session`. The fixture uses the actual API/UI/worker/storage paths with a synthetic research provider labelled “Offline study-methods fixture.” It is only a CLI development helper, with no production fixture route. Research results are test data, not real research. Stop both terminals afterward. The isolated data path holds fixture outputs; no credentials are written.

External agent worker:

```powershell
$env:OPENLEARN_WORKER_MODE='external'
backend/.venv/Scripts/python.exe -m backend.app.agent_execution.worker
```

The external worker uses the existing configured model provider for optional research synthesis. Existing provider/cost settings apply; the lab adapter itself remains deterministic. Disabling admission prevents new tasks while preserving reads, answers and cancellation for existing work.

## Verification actually run

| Check | Result |
| --- | --- |
| Foundation tests, `python -m pytest backend/tests/test_agent_execution.py -q -p no:tmpdir` | 9 passed; includes HTTP flow, duplicates/stale replies, crash after storage, cancellation, two claimants, legacy recovery isolation and 0041→head→0041→head migration |
| Foundation + existing browser/backend reader tests | 28 passed, 2 provider-dependent skips (initial five foundation tests plus existing suites) |
| Broader regression: foundation, execution_foundation, migrations, local_identity_boundary, control_plane_integration, lecture_pipeline, object_storage | 50 passed, 1 environment/provider-dependent skip |
| Affected frontend: agent panel, research source list, browser card, tutor components | 14 passed across 4 files |
| `npx tsc --noEmit` | Passed |
| Targeted ESLint | 0 errors; one lifecycle-ref cleanup warning recorded before final cleanup |
| `npm run build` | Passed full Vinext production build |
| Real in-app browser, isolated fixture | Start → question → answer/steer → completed 5 cm/s files; research selector → completed report → retained source excerpt visibly shown |
| Actual PNG visual inspection | Labelled speed/unit/trial chart inspected |

The real browser workbook-download button triggered an authenticated HTTP 200. The browser automation bridge did not return a saved-download path before timing out; saved browser path is not claimed. HTTP tests download and parse the real XLSX bytes. Browser screenshot captured the completed tasks/source excerpt. Worker-crash and second-owner checks are API/storage tests; a physical second device was not used.

Initial sandbox pytest temporary-directory ACL and Vite helper-spawn restrictions were reproduced; the affected existing fixtures/tools passed under approved escalation. Remaining warnings are existing SQLite datetime/FastAPI startup deprecations. No paid/live provider tests, PostgreSQL test server, native build, commit, push or deployment were performed by this milestone.

## Exact deferrals

Messages use an explicit development capability selector; general natural-language admission/classification and arbitrary attachments are subsequent integration work. Required questions are durable and text answers work; voice and richer schemas are unbuilt. Responsibilities, triggers, approvals/external writes, sandbox leases, browser takeover, operational memory and delegated children retain the main brief's later gates. Slice 1's native capture gate is explicitly incomplete. The foundation provides reusable state and output hooks, not a claim of full platform completion.

Browser acceptance also verified reload restores both completed task histories. Screenshot: `work/agent-foundation-browser.jpg`. Temporary acceptance API and Vite processes were stopped after verification; the offline research fixture is isolated in the development preview script.
