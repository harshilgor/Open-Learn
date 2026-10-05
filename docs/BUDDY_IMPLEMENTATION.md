# Personalized Buddies implementation

Implemented against `BUDDY_HOME_COURSES_AND_CHATS.md`; delivery status is tracked in `BUDDY_IMPLEMENTATION_TASKS.md`. This is the companion identity, navigation and course/class foundation. The live classroom agents, shared flashcards and automatic preparation are explicit subsequent dependencies.

## Delivered frontend

Desktop adds a companion rail beside the existing navigation sidebar. Create/customize offers a name, five avatar presets, five accent palettes, four communication styles, concise/exemplar preferences and a live greeting preview. Default selection and archival use the same profile IDs. Archival shows course/responsibility counts and requires a replacement; history stays attributed to the archived companion.

Home has the selected companion, real upcoming assessment/assignment dates where available, shared concept reviews, course/schedule setup and reminders. Quick prep drafts a course-scoped request for the student to review. Unknown events are never fabricated. Conversation is the default response presentation; Ask, Learn and Quiz retain the established workflow authority. In-Class opens recording setup and does not activate a microphone automatically.

History filters by companion, searches title/course/companion and offers All chats including archived profiles. Older pages remain reachable. Opening a chat restores its stable companion and course. Today preserves the last-chat pointer. Text drafts are stored under companion/chat IDs on this device; raw unsent attachments and note mentions survive switches during the current visit. Attachments are not durable across reloads, and drafts are not yet cloud-synced.

Courses offer companion assignment during creation and from their header, default fallback, an explicit companion-aware new conversation, and Overview/Classes/Materials/Study sections. Materials use the existing course filter. Notes and saved quizzes reuse their existing artifact IDs/renderers. Class setup shows the course and resolved companion, permits a session override, and retains the current capture/pause/stop/recovery pipeline. Session history opens its actual note and reports the recording status; live practice/deck outputs are labelled as forthcoming.

Phones use a companion switcher sheet and Buddy/Courses/Review/More navigation. The course list identifies preferred companions; chat history remains in the existing navigation drawer. Desktop and phone breakpoints were checked in the browser, along with preset contrast in light and dark themes.

## Backend and data contracts

Migrations `0045_buddy_profiles` and `0046_buddy_navigation` add owner-indexed companion profiles, account defaults, course assignments, immutable chat/class attribution, shared responsibility references and last-chat pointers. Existing chat/recording IDs stay unchanged and backfill to the original default companion. New identity resolves explicit override → course preference → account default, and is persisted on creation.

`/v1/buddies` supplies the profile/navigation snapshot. Profile creation supports idempotency keys; edits and archive require a profile revision. Names and preset preferences are validated, including when reading imported profiles. Only approved finite communication preferences enter teaching prompts. Personality is not learning evidence and does not change permissions or grading rules. Course assignments currently use serialized writes, without a client-facing compare-and-swap revision.

Companion identity is added to session creation and lecture creation. Recording retry cannot substitute a different companion. Deleting a conversation clears its attribution/navigation pointer; deleting a class note clears its recording attribution. Course deletion clears the preference and detaches responsibility references without deleting learning resources.

Reminders and study tasks keep existing IDs and deduplication rules. A single responsibility reference identifies their companion/course. Archival transfers these references rather than recreating reminders or tasks. Delivered inbox reminders produce real rail badges. Reading specific reminders marks only their owner-scoped inbox deliveries read. Notifications use internal reminder/course/companion deep links; no new notification permissions are requested automatically.

The existing ownership-aware export/import/erase infrastructure includes the new tables. Import remaps companion and chat references, preserves an existing pristine target account default, and excludes responsibility references for reminder schedules that the importer intentionally omits. Merely loading a default Buddy does not prevent importing into an otherwise empty account. Account changes clear UI state and transient file drafts; older profile responses are ignored.

Supabase provisioning remains deferred. These tables use the repository's current SQLAlchemy/Alembic persistence and existing authenticated owner boundary; a shared deployment can expose the same API to authorized devices. Provider and calendar account setup were not changed.

## Verification

- 14 Buddy backend tests: ownership, legacy/default stability, course fallback/override, historical identity, revisions, archival, export/import/erase, create retries, responsibility deduplication, last-chat restoration, bounded preferences, real schedule dates and class retry identity.
- 23 existing browser-assistant and 3 academic-planning tests pass with the new responsibility integration.
- 16 existing lecture pipeline tests pass after the final attribution/cleanup changes, using Windows access for pytest temporary directories.
- 11 frontend tests pass across Buddy state/account switching, the existing composer/rich-content tests and shared agent execution UI.
- Full TypeScript check and focused ESLint checks pass with no errors; existing unused-import and hook-dependency warnings remain in the workspace/chat components. Whitespace diff check is clean.
- Browser → API → database → UI verified with an isolated preview SQLite database: create Nova, assign Biology 101, inspect class setup, switch per-Buddy drafts, restore course chat/last chat, open mobile switcher and navigate Courses. No microphone capture or paid model generation was triggered during browser verification. Recording processing is covered with fake providers in the pipeline tests.

The broader legacy course suite has two failures: `test_create_course` and `test_update_roadmap_node` assume generated sample roadmap nodes, while the current course service creates an empty roadmap. The Buddy work does not add that sample roadmap behavior. The first recording test attempt hit Windows temporary-directory permissions; the subsequent permitted run passed all 16 tests.

## Remaining integration work

Implement the separate In-Class architecture to supply a class-linked conversation, streaming Notes/Materials/Practice canvas and final summary/revision quiz/active-recall/deck readiness links. Implement the shared flashcard agent and deck review renderer, then connect proactive preparation with course opt-ins and account-wide delivery preferences. Add real recurring class schedule ingestion before presenting a next-class card. Durable cross-device drafts/files require an explicit synchronization design; last-chat identity is already server-persisted.

No deployment, external account provisioning, new calendar connection or production database replacement was performed.
