# Agent execution platform release evidence

Updated 2026-10-09. This record separates implemented and locally verified behavior from code gaps and live acceptance. A passing local test does not establish a hosted provider, PostgreSQL, S3, or device result.

## Build identity

- Repository HEAD at review: `4bf41db`.
- Working tree: dirty with the implementation in this task and other pre-existing workspace changes. No commit, push, or deployment was made.
- Production flags and secrets were not changed. Browser private-profile verification and browser writes remain disabled. Identity restore remains disabled by default.
- No real Google, Browserbase, Exa, Daytona, PostgreSQL, or S3 calls were made for this review. Provider adapters were tested with fakes where stated.

## Package status

| Package | Status | Local evidence | Remaining work or acceptance gate |
| --- | --- | --- | --- |
| Shared admission, bounded kernel, generic inputs | `local_verified` | Scoped platform suite: 137 passed, 1 skipped, 10 deselected before the later A–G additions. Generic request/revision and browser UI tests also pass in focused runs. | Re-run the selected suite after all later changes. HTTP/TestClient cases that need an asyncio socketpair are blocked on this Windows runner. |
| Execution context, compaction, output verification | `local_verified` | Focused context/compiler and generated artifact checks passed; CSV analysis checks CSV/XLSX/PDF/JSON independently and preserves the Daytona-specific lab route. | Research paraphrase meaning and full live coverage remain unknown; see package B. |
| Cross-capability research and learner workflows | `local_verified` | Research parent → bounded CSV analysis child test passed; explicit acceptance of partial research is required before caveated teaching. Quiz and mastery evidence remain gated. | Complete live authenticated research and learning journey acceptance. |
| Operations, retention, and rollout | `local_verified` | Retention/responsibility selection: 12 passed, 3 deselected; usage admin: 11 passed; execution panel: 5 passed. Retention is disabled unless explicitly configured, preserves unresolved-effect receipts, and requests a resnapshot below its cursor floor. Operations output is aggregate and read-only; responsibility rollout is separate and defaults off. | Hosted monitoring/alert delivery and configured retention policy need operational acceptance. Usage rates and TTLs must come from approved configuration. |
| A. Google workflows | `partly_local_verified` / `live_blocked` | Conversational Calendar read is routed through the ordinary message admission into a queued `agent_v2` task. It asks durable questions for a missing time range or connected account, uses the existing read-only `calendar.events.readonly` grant, timezone-aware bounded ranges (31 days maximum), and no more than 100 events. Results are a private JSON artifact with explicit complete/partial coverage; revocation tombstones the artifact and prevents downloads. Six focused read/range/paging/OAuth tests pass, including mocked full task execution, user answer/resume, partial results, account-selection waiting, and disconnect behavior. | Calendar discovery and broader Gmail/Drive source orchestration; provider-grant revocation; real OAuth, Drive/Gmail, and controlled Calendar acceptance. The current `calendar.events.readonly` grant does not authorize CalendarList discovery; the conversational reader uses `primary` unless the user supplies an ID. Do not widen OAuth consent without a separate decision. Calendar write actions were not run against a live account. |
| B. Live research | `partly_local_verified` / `code_pending` | Claim evidence: 3 focused tests passed. Ownership/source checks, citation IDs, exact quote matching and numeric-literal checks are enforced. Unsupported numeric claims remain unknown and force partial results. | Semantic support/disagreement, coverage verification and a complete hosted acceptance runner remain code pending. Real Exa acceptance was not run. |
| C. Hosted Daytona | `partly_local_verified` / `code_pending` | Daytona continuation: 2 passed. Existing adapter, bounded task lifecycle, cleanup obligations and output checks are present; object storage: 3 passed, 1 skipped. | Resource sizing and safe dollar reservation/settlement for reserved CPU/RAM/disk remain code pending. A complete authenticated hosted journey and provider cleanup acceptance were not run. |
| D. Browserbase takeover/recovery | `local_verified` / `live_blocked` | Browser crash/handoff regression tests: 6 passed in focused runs; the complete browser backend file excluding its Windows-hanging HTTP test passed 37/37. The worker now claims a durable, expiring recovery lease, confirms the provider session is terminal and settles its usage hold before it resumes. A crash during ordinary agent work causes a fresh observation without replaying the ambiguous action. A takeover request interrupted by a crash does not grant a live view; after confirmed shutdown it asks the learner to explicitly continue in a fresh session. Unconfirmed provider state remains paused and retryable. Acknowledgement rejects an in-flight cloud session. | Real Browserbase two-profile recovery and physical companion/device continuity remain unverified. Orphan sessions created before a durable lease exists need provider-level cleanup evidence. Private profiles and writes stay off. |
| E. PostgreSQL | `code_pending` / `live_blocked` | Existing durable stores, leases, row locks/CAS and migrations are present; SQLite-focused deterministic tests pass. | Dedicated multi-process PostgreSQL races, migration-forward repair, restart recovery and restore acceptance are absent. No live PostgreSQL run was made. |
| F. Private S3 lifecycle | `code_pending` / `live_blocked` | Immutable object storage tests: 3 passed, 1 skipped. Windows object publication now uses same-directory rename while preserving no-overwrite semantics. Revocation journal adapter fake tests pass. | Versioned-object deletion/purge and hosted private-bucket lifecycle, backup and restore acceptance remain absent. No real bucket was used. |
| G. Export, restore, deletion, revocation | `partly_local_verified` / `code_pending` | Revocation unit tests: 8 passed; restore guard integration: 1 passed. A dedicated-bucket S3 journal uses domain-separated hashed identifiers; `BackupService.restore` fails closed on missing configuration, incomplete reads, invalid coverage or unreconciled revocations. | Restore stays disabled by default. Hosted journal setup, independently retained coverage attestation, cloud restore runner, restore UI, remaining browser/device revoke call sites, Google grant revocation, and real PostgreSQL/S3 restore tests remain. Portable import is content-only; it is not infrastructure restore. |
| H. Milestone 7 device work | `live_blocked` | The implementation plan assigns this package to milestone 7. | Physical iOS/Android recording, push, reconnect, takeover and signed-build tests remain device/release gates. |

The restore journal must use a dedicated bucket, not `OPENLEARN_OBJECT_BUCKET` or `OPENLEARN_ASSISTANT_S3_BUCKET`. Restore requires `OPENLEARN_IDENTITY_RESTORE_ENABLED=true` plus `OPENLEARN_REVOCATION_JOURNAL_BUCKET`, `OPENLEARN_REVOCATION_JOURNAL_PREFIX`, and `OPENLEARN_REVOCATION_JOURNAL_COVERAGE_START`; all are unset or disabled in the production configuration. The coverage start is an operator attestation and requires prior tombstones to be seeded and reconciled.

## Focused commands and results

Commands below were run from the repository root unless a working directory is shown.

```text
python -m pytest backend/tests/test_browser_assistant.py -q -k "browser_input_request or shared_admission_routes_exact_browser_reply or takeover or write_intent or profile_cleanup" --tb=short --timeout=30
4 passed, 30 deselected

python -m pytest backend/tests/test_browser_assistant.py -q -k "cloud_worker_crash_stops_session_then_reobserves_without_replay or cloud_takeover_crash_requires_learner_resume_after_confirmed_stop or cloud_takeover_ack_cannot_grant_control_while_input_is_inflight or cloud_takeover_retries_reconciliation_and_never_grants_on_unknown_provider_state or browser_control_handoff_waits_for_the_inflight_action or cloud_takeover_return_waits_until_session_termination"
6 passed

python -m pytest backend/tests/test_browser_assistant.py -q -k "not api_owner_device_scope_and_event_replay" --tb=short --timeout=30
37 passed, 1 deselected (the excluded TestClient case hangs before request handling while Windows asyncio creates its socketpair)

python -m pytest backend/tests/test_identity_revocation.py -q --basetemp backend/.pytest-revocation-final3
8 passed

python -m pytest backend/tests/test_backup_and_evaluation.py -q -k identity_backup_restore_requires_independent_revocation_reconciliation --basetemp backend/.pytest-backup-revocation-final2
1 passed

python -m pytest backend/tests/test_object_storage.py -q --basetemp backend/.pytest-storage-final2
3 passed, 1 skipped

python -m pytest backend/tests/test_agent_connected_actions.py -q -k "conversational_calendar_read or calendar_read_asks_for_missing_range or calendar_read_retains_answered_range or calendar_read_stops_at_five_pages or calendar_reads_are_range_bounded_and_paginated or calendar_read_oauth_uses_readonly_events_scope" --basetemp=backend/.pytest-calendar-evidence
6 passed, 20 deselected

python -m pytest backend/tests/test_conversation_admission.py -q -k shared_routing --basetemp=backend/.pytest-admission-calendar
19 passed, 12 deselected

python -m pytest backend/tests/test_agent_connected_actions.py -q -k "not http_approval_identity_and_payload_validation" --basetemp=backend/.pytest-connected-final2
25 passed, 1 deselected (TestClient HTTP path excluded on Windows due the asyncio socketpair hang documented above)

python -m pytest backend/tests/test_browser_assistant.py -q -k "cloud_worker_crash_stops_session_then_reobserves_without_replay or cloud_takeover_crash_requires_learner_resume_after_confirmed_stop or cloud_takeover_ack_cannot_grant_control_while_input_is_inflight or cloud_takeover_retries_reconciliation_and_never_grants_on_unknown_provider_state or browser_control_handoff_waits_for_the_inflight_action or cloud_takeover_return_waits_until_session_termination" --basetemp=backend/.pytest-browser-continue
6 passed, 32 deselected

node node_modules/vitest/vitest.mjs run tests/generation-activity.test.tsx --pool=threads --maxWorkers=1  # run from web/
3 passed

node node_modules/vitest/vitest.mjs run tests/agent-connected-actions.test.tsx --pool=threads --maxWorkers=1  # run from web/
4 passed

node node_modules/eslint/bin/eslint.js components/assistant/connected-task-panel.tsx  # run from web/
Passed with no diagnostics

python -m pytest backend/tests/test_agent_research.py -q -k "unverified_semantic_synthesis or claim_evidence_checks_report_literal_match_without_claiming_semantic_proof or unknown_citation_is_rejected_and_no_final_output_is_persisted" --basetemp=backend/.pytest-final-research-evidence
3 passed, 19 deselected

python -m pytest backend/tests/test_agent_research.py -q [claim evidence focused selection]
3 passed, 19 deselected

python -m pytest tests/test_usage_admin.py -q --tb=short --timeout=30 --basetemp=.pytest-final-usage-1009
11 passed (run from backend/)

node node_modules/vitest/vitest.mjs run tests/agent-execution.test.tsx tests/browser-assistant.test.tsx tests/conversation-admission.test.tsx --pool=threads --maxWorkers=1  # run from web/
22 passed (run from web/)

node node_modules/vitest/vitest.mjs run tests/browser-assistant.test.tsx tests/conversation-admission.test.tsx --pool=threads --maxWorkers=1  # run from web/
17 passed (run from web/)

git diff --check
Passed; Git printed line-ending conversion notices only.
```

The full Windows HTTP/TestClient route tests can block before the assertion while AnyIO creates an asyncio socketpair. Playwright browser fixture startup also timed out before launching a browser. Those are recorded as harness limitations, not successful product tests. A whole-web TypeScript check encountered pre-existing generated `.next/types/validator.ts` and browser-test errors; the modified connected-task panel had no reported type error. ESLint for the main chat path had one hook dependency warning and no errors; a later ESLint run did not finish within 60 seconds.

## Release decision

This implementation is not release-accepted. The deterministic local slices are ready for review, while the live/hosted/device gates above remain open. Do not enable browser private profiles, browser writes, identity restore, or Daytona until their package-specific evidence is recorded against disposable accounts and resources. No credential, private content, or provider session URL belongs in this evidence file.
