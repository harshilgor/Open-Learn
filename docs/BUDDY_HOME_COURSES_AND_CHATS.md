# Personalized Buddies, home, courses, and class sessions

Product and integration specification — 4 October 2026. Records the agreed direction for the redesign. This document describes future implementation, not shipped multi-Buddy functionality. It extends the Complete UI Redesign, In-Class, and flashcard briefs.

## Product model

Follow the [behavior and recovery contract](BUDDY_BEHAVIOR_AND_RECOVERY_CONTRACT.md) for memory scope, proactive permission defaults, Conversation/Ask behavior, and interruption handling. Buddy denotes companion identity; Conversation denotes the default mode. Restore existing chats' saved response modes without restarting capture.

Students can personalize companions and assign preferred Buddies to their courses/classes. Each Buddy supports multiple chats. All companions use the same learning capabilities and account-owned resources.

| Entity | Meaning | Relationship |
| --- | --- | --- |
| Student account | Owner of learning data and preferences | Owns Buddies, courses, chats, materials, tasks, and progress |
| Buddy profile | Name, appearance, communication style, and selected responsibilities | Has many chats; can be preferred for several courses |
| Course | An ongoing subject such as Biology 101 | Contains materials, assignments, class sessions, and linked conversations |
| Class session | A particular lecture or meeting within a course | Links recording, notes, chat, practice, and revision outputs |
| Chat | A bounded conversation with one Buddy | Optionally linked to a course and class session |
| Mode | How the selected conversation is being used | Conversation, Ask, Learn, Quiz, or explicit In-Class activation |

The user's everyday term “class” often means a course. In implementation, distinguish the ongoing course from a dated class session. Assign a preferred Buddy at course level and allow an explicit override for a particular session. One Buddy can support several courses; creating a course must not force creation of another Buddy.

## Personalized Buddy profiles

Creation and customization offer a name, character/avatar, accent color, and communication style such as calm, playful, encouraging, or direct. Add study preferences such as concise explanations, examples, and proactive preparation. Students may use one companion for everything or create companions for different subjects.

Show a live visual preview and a short example greeting during customization. Offer accessible preset colors and avatars first; arbitrary avatar uploads can follow their own validation/storage design. Apply accent colors to selected controls, avatar treatments, and small highlights while preserving contrast in light and dark themes. Do not recolor dense learning content or rely on color alone to identify a Buddy.

The profile appears in chat headers, assistant avatars, course assignment chips, reminder attribution, and class-session headers. The personality influences communication but never changes factual standards, grading, source access, or tool permissions. Renaming or restyling a Buddy keeps the same profile ID, conversations, and responsibilities.

## Desktop home and navigation

The home page is the selected Buddy's study space. Use four progressive areas:

```text
Buddy rail | Chat and navigation sidebar | Conversation/home | Optional study canvas
```

The rail contains distinct avatar buttons, accessible names, selected state, meaningful unread indicators, Create Buddy, and account/settings access. Clicking an avatar restores that Buddy's last chat, or its home state if none exists. Keep a visible Home/Today control so the student can intentionally return to the greeting and daily overview without discarding a conversation.

The adjacent sidebar shows the selected Buddy's name/customization menu, New chat, searchable recent chats, Courses, Review, and Reminders. Recent chats are filtered by Buddy; course navigation remains account-wide, with assigned courses easy to identify. Offer an explicit All chats search/filter for users who cannot remember which Buddy handled a topic. Do not silently mix histories under a selected avatar.

The central home state contains the Buddy identity, a short greeting, at most a few actionable Today cards, and a prominent composer. Examples: next class with Start class/Quick prep, an approaching deadline, due flashcards, or a prepared study sheet. Only show real known information; use “Add a course” or “Set up your schedule” empty states rather than fabricated events. Explain missing calendar/material access with an actionable setup link.

Sending the first message creates a chat under the selected Buddy. The home greeting/cards give way to the message thread. An existing chat opens directly to its messages; do not insert a new daily dashboard into its history on every visit. Today cards remain reachable from Home. Use short readable previews, not a dense dashboard grid.

The composer shows the active course context and mode. New chats default to Conversation mode. The avatar/name identifies the companion; the mode selector is labelled Mode and shows Conversation by default. Ask uses developed responses, Learn opens a lesson, Quiz opens practice, and In-Class opens setup before microphone capture.

## Layout and visual treatment

At wide widths, the Buddy rail is narrow, the sidebar is modest, and the conversation has a comfortable reading width. Proposed initial sizing: rail around 64–72 px, sidebar around 240–280 px; tune these through prototypes. The canvas consumes the remaining useful space when opened. Collapse the chat sidebar or present the canvas as an expanded view when minimum reading widths cannot be maintained. Never squeeze four columns into a tablet viewport.

Use left-aligned assistant and right-aligned user bubbles for conversational content, with readable rich-content rendering for Ask. Keep current message actions, sources, streaming, retries, and attachments. The canvas has a clear content title, course/session context, and close/expand controls. Opening a lesson, deck, or quiz references the existing artifact; it does not generate a duplicate.

Keyboard users can navigate avatar buttons, chat lists, and workspace actions. Every icon has a name; changing companions or opening a canvas establishes predictable focus. Preserve drafts per chat, display loading/error states for unavailable history, and respect reduced-motion preferences.

## Multiple chats and shared context

Each chat has one stable Buddy assignment. New chat starts fresh conversation context under the selected Buddy and optional selected course. Opening a history item restores its actual Buddy and course context. Switching modes does not switch companions or create another conversation.

A course-linked chat appears both in the companion's history and on the course page as links to the same record. Search results show Buddy and course labels. Course materials and saved account preferences may be retrieved when relevant and authorized; other conversations are not automatically copied into a new chat. Any future cross-chat memory retrieval needs explicit scope and inspectable provenance.

Changing the preferred Buddy for a course affects future chats and sessions. Historical chats keep their original companion. If a student wants to continue a topic with another Buddy, initially create a new linked chat with an explicit selected summary rather than silently reassigning the old history. Full chat reassignment can be a later defined feature.

## Course page and assignment

The course header displays course name, preferred Buddy avatar/name, and Change Buddy. Course setup offers Use my default Buddy or Choose a Buddy, plus Create Buddy when desired. A course without a preference falls back to the student's default companion.

The course overview includes the next known class and Start class, Quick prep, recent class sessions, upcoming assignments/assessments, materials, linked chats, and review progress. Provide focused sections or tabs for Overview, Classes, Materials, and Study; avoid filling the overview with every artifact. Study gathers notes, quizzes, and decks. Each section opens existing resource renderers rather than separate copies.

Ask [Buddy name] about this course starts a course-scoped chat, while an existing course chat resumes its own historical Buddy. Course-linked reminders and proactive work use the preferred Buddy for new responsibilities. Changing an assignment must not duplicate existing reminders or preparation jobs.

When opening a course whose preferred Buddy differs from the currently selected companion, clearly show the preferred identity in the course header. Opening the course alone need not replace the active chat. Actions that start a new chat or class session select the course's Buddy and reveal that choice before the action begins.

## Class session journey

1. From Biology, press Start class. Setup is prefilled with Biology, its preferred Buddy, and available materials.
2. Optionally change the session title, Buddy for this session, or desired outputs. A one-session override does not change the course default.
3. Press Start listening to begin microphone capture. Reopening a running session joins its existing workspace and never starts a second recorder.
4. The class workspace shows Buddy chat and Live notes, Materials, and Practice views in the canvas. Recording controls remain accessible across view changes.
5. At Stop, the microphone closes and outputs finalize. The course's class-session history gains a dated entry with summary notes, revision quiz, active recall, and the draft flashcard deck, each with readiness status.
6. Opening the session later restores its linked context and artifacts. Follow-up learning and review reference those same outputs.

Persist the resolved Buddy on session creation so a course reassignment midway through a lecture does not change the active companion. Existing recording lifecycle, source grounding, and worker coordination follow the In-Class architecture brief. Buddy profiles are student-facing identities; the notes/materials/quiz/flashcard workers are shared internal capabilities, not additional selectable companions.

## Reminders, proactive work, and flashcards

Reminders and ongoing tasks belong to the account, with source Buddy, course, chat, and class references where relevant. They survive New chat and companion switching. A global Reminders view shows all reminders with filters and attribution. Notifications open the exact associated resource and select the corresponding companion/context when available.

Use one responsibility identity for a course/event/output type so two Buddies cannot independently create duplicate midterm-preparation jobs. Account-level quiet hours and delivery preferences apply across companions. Per-Buddy/course preferences can narrow proactive behavior; they must not override disabled account-wide notifications.

Flashcards are account/course resources created through the shared skill. A deck may record which Buddy requested it, but it can be reviewed from any authorized companion or the course Study view. Review attempts, due dates, and learning evidence remain single shared records.

## Mobile and tablet

Target bottom navigation: Buddy, Courses, Review, More. Notes remain accessible from course Study, the canvas, and More. This supersedes the initial proposed phone bar containing Notes as a primary tab; the existing implementation is not changed by this document.

On the Buddy screen, tap the avatar/name to open a companion switcher sheet with names, avatars, Create, and Customize. A separate Chats button opens the selected Buddy's history, search, and New chat. Do not expose two persistent sidebars on a phone. Preserve the last chat and unsent draft for each companion.

Course screens show the assigned Buddy and Start class near the header. Learn, Quiz, decks, and class work open as expanded views with Back to chat and appropriate recording status. Deep links restore resource identity and navigation rather than starting a new task. Tablets use available width to choose between a side canvas and expanded view, not device-name detection.

## Integration with the current code

Extend `learning-workspace.tsx` as the shell coordinator and `workspace-sidebar.tsx`/`chat-history.tsx` for companion-filtered conversations. Add proposed BuddyRail, BuddySwitcher, BuddyProfileEditor, and BuddyHome components. Reuse `course-home.tsx` for course assignments and class-session entry points. Reconcile `mobile-navigation.tsx` with the target mobile destinations. Continue using `workspace-split.tsx`, `workspace-panel.tsx`, and typed workspace events for artifacts.

Add an owner-scoped BuddyProfile service and profile/assignment API contracts. Resolve stable companion identity server-side; client-selected profile IDs must belong to the verified owner. Proposed schema extensions: buddy_profiles; preferred_buddy_id on courses; buddy_id on conversations and class-session envelopes; optional attribution references on tasks/reminders. Use repository-compatible migrations and revisions, and reconcile any existing assistant-profile concept before creating duplicate tables.

Existing users receive one default profile, and existing conversations are backfilled to it. Preserve conversation IDs and course links. Resolve new-session identity in this order: explicit valid session override, course preference, account default. Persist that choice. No provider provisioning is required for documenting or prototyping profiles; eventual Supabase hosting uses the same account ownership model.

Separate profile appearance, communication preferences, and proactive responsibility settings. Prompt/context compilation consumes bounded approved preferences rather than accepting unrestricted profile text as authority. Include Buddy/session identity in task context for delivery, while source access remains enforced by the existing account/course permissions. Shared tools are not duplicated per Buddy.

Account export/import/delete must include profiles and references. Prefer archive for companions with history; archived companions stop accepting new conversations and their histories remain reachable. Show affected future responsibilities and require a clear reassignment/cancellation choice before completing archival. Preserve account resources and existing task identity; do not delete courses or cancel reminders as a side effect of renaming or switching companions. A default companion must always resolve, with an explicit replacement when archiving it.

## Illustrative journey

Harsh opens Pip's home and sees an upcoming Biology class. Biology's assigned Buddy is Nova, identified on the class card. Start class opens setup with Nova selected. During the lecture, Nova's conversation sits beside live notes and materials. Afterward, the session's summary and draft deck appear in Biology. Later Harsh returns to Pip and asks what to review; Pip can open the same Biology deck and due schedule. Nova's class conversation remains in Nova's chat history and in Biology's session entry.

## Delivery and acceptance

Begin with one customizable Buddy plus multiple chats and the home/course context UI. Add multiple profiles, course assignments, and session overrides as an additive capability; then connect live class and proactive task delivery. Feature staging is implementation sequencing, not a removal of the approved multi-Buddy design.

Validate profile creation/editing, preserved history after renaming, per-Buddy drafts/history, course fallback and explicit overrides, historical attribution after reassignment, accurate deep links, no duplicate chat/artifact records, account isolation, no duplicate reminders, retained review progress across companions, recording controls during navigation, mobile keyboard/focus, contrast, empty/error/loading states, and archive/reassignment behavior. UI-only prototypes must label unavailable actions; backend integration is a separate implementation phase.
