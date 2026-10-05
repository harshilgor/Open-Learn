# Shared flashcard implementation gap audit

Audit date: 4 October 2026. Compared `FLASHCARD_AGENT_ARCHITECTURE.md` with the current working tree, including uncommitted implementation. This is a code and targeted-test audit, not hosted deployment or browser acceptance. No product implementation changes are included.

## Conclusion

The checkout contains an In-Class-only QA draft feature. It does not yet contain the shared flashcard capability, editable/publishable deck product, or card-level review system described in the architecture. Reuse the current runtime and class source pipeline; extend the small draft-storage service deliberately rather than treating it as the completed deck service.

## What exists

| Area | Evidence | Scope and limits |
| --- | --- | --- |
| Explicit class opt-in | `web/components/class-recorder.tsx`, `backend/app/in_class_models.py` | Draft flashcards checkbox, disabled by default. No equivalent Ask/Learn/Quiz create action. |
| Bounded transcript generation | `backend/app/in_class_service.py` | Settles windows at 30 seconds or 2,000 characters, caps normal batch context at 7,500 characters and 200 windows; uses the existing provider. This is time/size batching, not meaningful-topic selection. |
| Existing worker ownership | `backend/app/agent_execution/worker.py:30`, `backend/app/in_class_service.py` | AgentWorker ticks the class service; class jobs use WorkflowStore, outbox handoffs, leases, heartbeat, retries, processing epochs, and source-revision checks. These are reusable class-job mechanisms, not a shared flashcard agent task contract. |
| Basic output validation | `backend/app/in_class_models.py:33`, `backend/app/in_class_service.py:215` | QA prompt/answer lengths, 1–12 items, nonempty cited segment lists, and membership in supplied evidence IDs. Passage IDs existing does not prove an answer is supported. |
| One draft deck per class | `backend/app/flashcard_service.py:8` | Stable class-derived deck ID; owner-scoped `practice_records` payload with windows and flattened cards; status draft, scheduled false. No stable individual card IDs or immutable card content versions. |
| Correction handling | `backend/app/in_class_service.py`, `backend/app/flashcard_service.py` | Recomputed window identities, stale-result fencing, and active-window filtering on subsequent saves. Old windows remain in the payload. No suggested card revisions, user-edit preservation policy, or explicit stale-card state. |
| Inline card display | `web/components/in-class-workspace.tsx:33` | Prompt, local reveal/hide answer, lecture evidence and timestamps in the class Practice view. Answers are already in the snapshot; reveal is not persisted. Cards use plain text JSX rather than RichContent. |
| Basic portability and cleanup | `backend/app/identity_data.py:10`, `backend/app/identity_import.py:155`, `backend/app/lecture_service.py:389` | Generic owner export includes draft records; import remaps window keys and pauses copied class sessions; recording deletion removes class draft decks. Card review/version portability does not exist. |

## Remaining implementation

| Architecture requirement | Status | Work required |
| --- | --- | --- |
| Shared typed invocation | Missing | Add flashcards to agent Message capability, typed request/source variants, admission and dispatch, stable command identity, target-deck revision checks, Buddy/session/course attribution and result references. Current contract allows only lab_analysis, research and sandbox_lab. |
| Authorized multi-source resolution | Partial: lecture only | Resolve and freeze note revisions/selections, material versions/spans, lesson deliveries, committed quiz feedback and lecture revisions; validate owner/course/session relationships and produce bounded coverage manifests. |
| Versioned application skill | Missing | Add runtime instruction manifest and output schema; record skill, prompt, validator and provider/model versions. Current generation is an inline instruction and RecallOutput model. |
| QA and cloze generation | Partial: QA only | Typed card-kind/payload schema, cloze rules, concept selection and links, requested-count limits and source coverage reporting. |
| Quality and deduplication | Partial: structural checks only | Answer grounding, ambiguity, answer leakage, contradiction checks, exact duplicate filtering, semantic duplicate candidates and visible uncertainty. Cross-window repeated cards currently remain possible. |
| Durable deck/card lifecycle | Partial: draft blob only | Deck/card/version/candidate storage, stable IDs, revision checks and idempotent mutation commands; draft/published/archived lifecycle, suspension/deletion, atomic selected-version publication and append without overwriting edits. Decide migration of existing class draft records. |
| Deck APIs | Missing | Owner-scoped list/get pagination, deck/card mutations, publish and due summaries. No flashcard routes were found in route modules or main registration. Current class snapshots expose output items rather than fetching an authoritative deck by ID. |
| Shared task delivery | Missing | Preparation phases, needs-input/partial/failure/cancel states, compact conversation task card and deck reference; retry/replay without duplicate deck/message publication. Existing class output status is only a partial foundation. |
| Flashcards canvas/editor | Missing | Client API, workspace renderer/editor/source links, typed open event, tab union/names/layout validator/state/panel integration, conflict UX and restorable deck/view identity. Existing class view cannot edit or publish. |
| Review and course libraries | Missing | Draft/published deck listing, filters, due counts and launch/resume actions. Course Study currently explicitly displays a flashcard placeholder. Existing Review is concept-based. |
| Card review sessions | Missing | Pinned card/version selection, persistent cursor, optional response, server reveal command if required, reveal-before-rating, skip, attempt IDs and exactly-once schedule application. Local reveal buttons do not implement review sessions. |
| Scheduling and evidence | Missing for cards | Separate owner/card state, explicit Again/Hard/Good/Easy mapping, scheduler version and timezone policy; concurrency protection. Existing scheduler accepts correct/partial/incorrect/skip with confidence and produces concept mastery fields, so it needs an explicit adapter. Self-rating must not automatically become verified learner evidence. |
| Offline and cross-device reconciliation | Missing for cards | Extend pending writes (currently only note PATCH and quiz commands), preserve pinned versions and attempt IDs, reject stale ratings, resolve edits and independently opened review sessions, add deletion tombstones. |
| Rich rendering/mobile/accessibility | Partial class display | Render card math through RichContent, accessible focus and shortcuts, long content layouts, full-screen/sheet editor and review, persisted progress. Native mobile generated contracts include the class toggle but no dedicated flashcard implementation was found. |
| Conversational and quiz invocation | Missing | Route requests and ambiguous-source clarification into the shared capability; turn committed quiz mistakes into linked draft candidates with deduplication. |
| Class consolidation | Partial windows only | Route class card generation through the shared capability; preserve edited/published cards, mark stale dependencies, consolidate concepts/citations/duplicates at class end. Current end-of-class jobs generate summary, recall and revision_quiz, not flashcard consolidation. |
| Proactive drafts/reminders | Missing for cards | Explicit preference policy, assessment-driven draft preparation, due-card reminder integration without implicit publication or notification enrollment. |
| Image/occlusion cards | Deferred | Asset ownership/storage, supported payload, accessible renderer and rights/coverage policy after text-card delivery. |

## Recommended build order

1. **Shared draft foundation.** Implement typed capability/source resolution, versioned generation and QA/cloze validation, stable deck/card/candidate/version storage, list/get/edit/publish APIs. Reuse the existing worker/job ownership. Define how existing class draft blobs migrate or are imported into the new model.
2. **First complete product flow.** Add explicit notes/lesson actions in Ask/Learn, task result card, Flashcards canvas editor, source inspection, publication and persistent navigation. Acceptance: create → background completion → reload → edit → publish, with owner isolation, malformed-output rejection, duplicate-command handling, cancel fencing and revision conflicts.
3. **Scheduled recall.** Add card review sessions, reveal/rating/skip, separate deterministic card scheduling, due counts and Review/course deck libraries. Acceptance: review version remains pinned after an edit; reveal precedes rating; closing the panel does not rate; retry/two devices apply one scheduling outcome; self-rating grants no automatic mastery.
4. **Recovery and portability.** Extend offline commands, reconcile simultaneous sessions and edits, export/import/delete all new entities and test PostgreSQL contention. Basic online resume should ship with each earlier slice; full offline reconciliation is a separate milestone.
5. **Broaden entry points.** Conversational routing, quiz-mistake cards, shared In-Class integration and final consolidation, then preference-controlled proactive drafts and reminders. Reuse the existing class pipeline rather than rebuilding transcription and job delivery.
6. **Optional visual cards.** Image-label/occlusion only after text flows and asset design are complete.

## Architecture document corrections

- Its opening statement that no flashcard implementation exists is now stale: the working tree contains class draft generation, persistence and inline reveal.
- Conversation and In-Class now have runtime integrations; scope claims should be reconciled with the current Buddy and class implementations.
- The canvas tab union and persisted-layout validator now accept notes, quiz, sources **and class**. Flashcards still require the proposed coordinated extension.
- Account portability has a real draft-deck foundation; describe card-version/review portability as the remaining gap rather than treating all flashcard export/import/delete work as absent.
- Add the current draft-blob migration decision and an explicit transition from class_specialist generation to the shared flashcard capability.

## Verification

Inspected the architecture, flashcard/class services and schemas, agent admission/worker boundaries, workspace events/layout/rendering, course placeholder, concept review scheduler/service, offline queue, identity portability and existing tests. `python -m pytest backend/tests/test_in_class.py -q -p no:cacheprovider`: **15 passed** in 43.65 seconds, with 109 SQLite datetime-adapter deprecation warnings. Existing tests cover class output generation, source correction, ownership, retry/lease/cancellation, export/delete and imported draft-window remapping. They do not demonstrate a dedicated flashcard editor, cloze cards, answer-grounding validator, review scheduler or cross-device rating flow.

Hosted PostgreSQL concurrency, real provider output quality, mobile interaction and notification delivery were not exercised. No new tests were added for this audit.
