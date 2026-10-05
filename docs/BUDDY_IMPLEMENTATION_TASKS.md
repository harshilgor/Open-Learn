# Personalized Buddies implementation tasks

Implementation begins from BUDDY_HOME_COURSES_AND_CHATS.md. Preserve existing working-tree edits. This checklist tracks delivered behavior and dependencies rather than treating documented future services as shipped.

- [x] Owner-scoped profiles, preset avatars/colors, validated communication preferences, revisions, default selection and archive/reassignment.
- [x] Course assignments with account-default fallback and historical chat attribution.
- [x] Persistent session attribution/backfill without changing conversation IDs.
- [x] Buddy rail, mobile switcher sheet and live-preview profile editor.
- [x] Companion home/Today with real academic dates, useful empty states and composer.
- [x] Multiple-chat filtering, search, All chats, course/Buddy labels and paginated older history.
- [x] Text drafts per chat, per-Buddy new-chat drafts, local attachment preservation during this visit, and loading/error states.
- [x] Course companion controls and course-scoped new chat actions.
- [x] Classes/materials/study navigation; reuse notes, course material library and saved quiz IDs.
- [x] Class-session setup/override linkage and existing capture controls/history.
- [x] Companion identity in shared views and bounded prompt personalization.
- [x] Buddy/Courses/Review/More mobile navigation and responsive controls.
- [x] Export/import/delete reconciliation and active-account isolation, including stale network responses.
- [x] Reminder/task attribution and reassignment without recreating responsibilities; notification deep links and inbox badges.
- [x] Backend ownership/revision/history tests, UI tests, type/lint checks and browser flow verification. See the implementation report for the wider-suite exceptions.

## Follow-on dependencies

- [ ] Complete live In-Class worker orchestration, class chat envelope and live Notes/Materials/Practice canvas.
- [ ] Class revision quiz, active recall and flashcard output readiness links after finalization.
- [ ] Shared flashcard agent/deck renderer and deck-based due reviews.
- [ ] Proactive preparation execution, course opt-in controls, and account-wide delivery/quiet-hours reconciliation for those new jobs.
- [ ] Next-class schedule ingestion: existing academic entities currently support assessments/assignments, not recurring class meetings. Class setup remains directly available from courses and the mode menu.
- [ ] Cross-device unsent draft/file synchronization after the shared account backend is configured. Profile identity and last-chat navigation already persist through the owner-scoped API.

Details and verification evidence: [Buddy implementation report](BUDDY_IMPLEMENTATION.md).

Dependencies: the complete live-agent In-Class pipeline, flashcard service and proactive scheduling are separately specified features. Their integration points must be tracked and unavailable states labelled; the first feature must not fabricate their outputs. Supabase setup remains deferred by the user.
