# Shared flashcards implementation

Implemented against `FLASHCARD_AGENT_ARCHITECTURE.md`, following the six stages in `FLASHCARD_IMPLEMENTATION_GAP_AUDIT.md`. The audit describes the pre-implementation checkout; this document describes the delivered implementation.

## 1. Shared draft foundation

The existing Python agent coordinator and worker admit and execute the typed `flashcards` capability. No separate generation queue or assistant is introduced. Requests freeze authorized note/lesson revisions and selections, attached material versions/passages, committed quiz feedback, or lecture segment revisions. Owner, conversation and course relationships are checked before generation. Coverage is bounded and truncation is reported.

`backend/app/flashcards/skill.json` and `instructions.txt` version the writing instructions and validation contract. Batches contain at most 12 cards, requests at most 60. QA and single-deletion cloze cards receive structural and quote/citation validation, an independent model quality check, and duplicate checks. Uncertain and duplicate results remain visible candidates. Model checks are fallible; quotation matching does not independently establish factual truth. Provider, model, prompt, skill and validator metadata are retained.

Dedicated owner-scoped tables store decks, cards, immutable content versions, candidates, reviews, immutable attempts, schedules, preferences and command receipts. Revision checks, idempotency, cancellation/lease guards and final source checks prevent duplicate or obsolete task publication. Old class draft blobs migrate into unchecked candidates. Selected card versions must be published explicitly.

## 2. Product flow

Web has task progress/results, a Flashcards workspace tab, source inspection, draft creation, manual authoring, editing, selected publication, suspension, removal, archive/restore, deletion and source revalidation. Notes and delivered lesson pages expose Make flashcards; the create picker also accepts uploaded reference materials and attaches them to the selected conversation. Workspace/deck/review navigation is restorable.

Native mobile has a deck library, source creation, draft editor, selected publication, candidates, source revalidation and persistent review. Both clients render math; native KaTeX resources and fonts are bundled for offline use with the upstream license. Desktop packaging includes the generation manifest and instructions.

## 3. Scheduled recall

The server pins content version IDs and stable attempt IDs when selecting a review. Initial review responses withhold answers; explicit reveal precedes rating. Skip, close and practice mode do not change schedules. Again/Hard/Good/Easy map deterministically onto the existing review scheduler through a versioned card adapter. Card schedules remain separate from concept mastery; self-rating creates no verified mastery evidence.

Schedule revisions and transactional locks reject competing review sessions after another session has rated the same card. Review progress and reveals survive reload. Source corrections and deleted notes/materials mark dependent current and published versions stale; suggested revisions preserve user edits and require acceptance/publication. Due counts feed Review and course libraries.

## 4. Recovery and portability

Web pending writes and native owner-scoped journals retain exact command identities and pinned attempts for retries. Conflicts preserve edits and offer reconciliation. Account export/import includes flashcard entities, remaps pending attempt references and version IDs, omits old command receipts, and does not restart imported generation. Imported preferences do not enroll the new account in reminders or proactive preparation. Deletion tombstones stop future review while retaining historical attempts until account erasure.

## 5. Broader entry points

Conversational flashcard intent opens the shared creation flow; missing sources are explicitly selected. Committed quiz mistakes can request cards. In-Class generation uses the shared writer/checker and authoritative deck storage, retaining its existing worker ownership and transcript publication fences. Class completion consolidates cards; transcript and note corrections invalidate dependencies.

Preference-controlled maintenance creates draft preparation tasks for upcoming assessments and daily due-card inbox reminders. Both preferences default off. Draft preparation never publishes cards; reminders use a stable owner/day delivery identity and the existing inbox acknowledgement flow.

## 6. Visual cards

Manual image-label and image-occlusion authoring is supported on web and mobile. Assets must belong to the account, be course compatible, and use supported PNG/JPEG/WebP formats within the 20 MB bound. Alt text and an explicit source-use confirmation are required. Occlusion masks use bounded normalized coordinates. Authenticated image endpoints return private, uncached bytes. Models generate QA/cloze; visual masks are explicitly authored by the user.

## Running

Apply the repository's normal Alembic migration path, including `0050_flashcards` and the existing merge revision that joins it with worker compatibility changes. Enable shared admission with `OPENLEARN_AGENT_ADMISSION_ENABLED=true`; use the existing configured text provider and AgentWorker. Local development uses the existing embedded-worker mode; deployed environments use the existing external-worker setup. No new provider account or scheduler is required. Generation remains unavailable until the existing provider/admission configuration is ready.

The API surface includes `/v1/flashcard-generations` (and task retry), `/v1/flashcard-decks` (get/list, commands, publish, revalidate), `/v1/flashcard-review-sessions` (get/create/commands), `/v1/flashcard-due-summary`, `/v1/flashcard-preferences`, `/v1/flashcard-notifications`, and authenticated `/v1/flashcard-images/{version_id}`.

## Verification and remaining environment checks

Backend regression coverage exercises generation/publication/review through services and FastAPI, account isolation, malformed citations, cancellation/source fencing, immutable pinned versions, competing review sessions, replay, cloze answer withholding, practice/skip, source corrections, uncertain candidates, import identity remapping, opt-in reminder idempotency and owned visual assets. Material-source coverage verifies attachment and revision requirements. Assessment preparation coverage verifies opt-in admission, idempotency and draft-only results. Existing class, agent-execution and workspace-note regressions are included.

The web regression suite covers explicit publication, reveal-before-rating, close without rating, stable retry commands, keyboard handling and owner-scoped offline attempts, along with existing class/workspace/agent components. Web and native mobile TypeScript checks pass.

The combined regression run passed **67 backend tests**, with **1 environment-dependent skip**; the final affected-suite rerun passed **37 tests**, with the same environment-dependent skip, covering the retry/deletion fixes. The web suite passed **14 tests**. Both client type checks, the production web build and `git diff --check` passed.

These checks use SQLite and deterministic provider fixtures. Live provider quality, PostgreSQL contention, packaged desktop startup, browser acceptance and native device interaction still require environment acceptance. No deployment or live-provider calls were performed during this implementation.
