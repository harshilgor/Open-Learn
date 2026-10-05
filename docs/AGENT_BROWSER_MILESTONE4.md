# Milestone 4: browser integration and takeover

Implementation and local verification, 4 October 2026. Authoritative scope: `Open Learn 2.0/26_agent_execution_platform.md`, section 7.3 and slice 4. This is not a hosted release or full live-provider acceptance.

## Delivered

The existing browser task card now exposes read-only retained observations, Take control, Open browser, Return control, and a responsive full-screen dialog. Observation never returns an input URL. Local connections explicitly require the paired desktop; public-fetch connections reject interactive takeover. Cloud human views are owner-authorized, private-login-gated, restricted to the expected provider hostname, and requested with a 60-second provider lifetime. Responses are not cached. Account changes clear private views.

`backend/app/browser_assistant/control.py` persists control owner/generation and the in-flight operation reference in the existing run aggregate. Takeover pauses task dispatch and cancels outstanding step receipts. A cloud handoff waits for its active executor to finish. A local handoff waits for the paired companion to finish its serialized input, detach its debugger and acknowledge the exact generation. Old device results are rejected. Ordinary resume cannot bypass human ownership.

Return control rotates the generation, clears stale observations and queues a fresh observation before another action. Cloud return closes and verifies termination of the human session before re-enabling automation; saved owner-approved contexts can restore login, but unsaved page state may be lost. Failed provider termination leaves the task paused and retryable. Worker mutations cannot override human ownership.

Password/OTP login pages return empty observations. Cloud screenshot capture masks inputs and rechecks login state. The local screenshot path also rechecks login state before retaining an image. The constrained reader's existing write restrictions remain in force for automation. Human browser interaction is separate from automation authority.

No schema migration was added: control metadata lives in the existing assistant aggregate, using its revision lock, event stream and account lifecycle. Browser legacy runtime dispatch remains authoritative; this slice does not migrate it to the agent-v2 worker. A fully unified admission decision remains a separate integration gap.

## Local verification

- Initial browser control plus existing browser service suite: 29 passed, including six new handoff tests at that point. A seventh preview test was added for the final combined regression run.
- Agent/browser frontend suite: 17 passed, including four new handoff UI cases.
- Controlled real Chrome adapter tests: 3 passed, including withheld login text/screenshots. Playwright 1.63.0 was installed from the repository's optional dependency range; installed Chrome was used without downloading a browser.
- TypeScript, targeted ESLint and all five production build stages passed. Router construction confirms the view, preview and companion handoff routes register.
- Final combined backend run: 87 passed in 199.38 seconds; two identity cases could not start because the command disabled their `tmp_path` fixture. Reran those two with the fixture enabled outside the Windows ACL restriction: 2 passed in 8.77 seconds. All 89 selected cases therefore passed across the final runs. Python compilation and companion JavaScript syntax checks also passed. Fixed a missing `json` import in the new HTTP view routes during continuation review.

Commands from repository root: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_browser_control.py backend/tests/test_browser_assistant.py backend/tests/test_agent_execution.py backend/tests/test_agent_research.py backend/tests/test_agent_sandbox_learning.py backend/tests/test_local_identity_boundary.py -q --tb=short -p no:cacheprovider -p no:tmpdir`; controlled browser suite `backend/tests/test_browser_assistant_browser.py`. From web: `npm run test:agent`, `npx tsc --noEmit`, targeted ESLint, `npm run build`.

## Remaining acceptance gates and limitations

Browserbase credentials/project, hosted PostgreSQL and S3 are still absent from server configuration. Live provider egress, actual recording/logging privacy, human-link expiration/revocation, mobile keyboard/full-screen input on real devices, hosted concurrency and lifecycle are unverified. A complete browser UI journey against the full local application and companion still needs verification; component tests and controlled adapter tests do not establish that journey.

If a cloud worker crashes while marked in flight, takeover intentionally remains requesting rather than granting concurrent human access. Recovery needs an operator/provider reconciliation path; automatic crash handoff recovery is not complete. Local reconnect can acknowledge after the companion resumes; an offline desktop cannot grant control. Physical phone testing and a signed native client remain later release work.

Daytona live adapter acceptance and Exa search/open acceptance are recorded in `AGENT_LIVE_ACCEPTANCE.md`. PostgreSQL/S3 verification remains open. Milestone 4 must not be reported fully accepted until the above boundaries and live journey are evidenced.
