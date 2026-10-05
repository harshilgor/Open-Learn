# Complete UI Redesign

Design brief — 4 October 2026. This records the agreed direction for future UI edits; it does not implement changes.

The [Buddy behavior and recovery contract](BUDDY_BEHAVIOR_AND_RECOVERY_CONTRACT.md) defines memory scope, proactive preparation, mode semantics, persistence, interruption recovery, and release scenarios. It is authoritative for these behaviors across the linked redesign briefs.

## Scope

Create one conversation interface with four modes: Conversation, Ask, Learn, and Quiz. Conversation is the new default mode, with a Grok-style layout and classic iMessage-style message bubbles. Preserve current functionality and multiple conversations. The initial implementation phase remains presentation work only: no backend changes, new conversation model, or data migration. Any new mode behavior or action capability requiring workflow or backend changes is recorded as product direction for subsequent implementation.

Supabase is the selected future shared-data provider. Its setup and synchronization work are deferred and are outside this UI phase.

This brief also records future feature ideas for the redesigned interface. Live class notes, teaching assistance, and sandbox-backed material retrieval are proposed capabilities with additional implementation dependencies; recording them here does not expand the current UI-only implementation scope.

## Visual reference

The supplied screenshots are references for the conversation's appearance: a dark surface, rounded message bubbles, assistant messages aligned left, user messages aligned right, a compact composer along the bottom, and an adjacent right-hand workspace. The later reference also informs a rail of customizable Buddy avatars. Screenshot message contents are not product requirements. Open Learn uses one shared conversation interface supporting multiple personalized Buddies, each with multiple chats.

Use rounded, content-sized bubbles for both participants. Give user and assistant bubbles distinct surfaces with readable contrast in both light and dark themes. Constrain bubble width for comfortable reading, while allowing code, equations, and attachments to render without clipping. Keep existing response actions, citations, streaming states, and error/retry controls accessible.

## Conversation and modes

Buddy is the student's personalized study companion; **Conversation** is the default mode. Students can create personalized companion profiles, assign them to courses/classes, and keep multiple chats under each companion. All profiles use one conversation interface and shared learning capabilities. Modes do not create separate assistants or histories.

New conversations start in Conversation mode across desktop, web, and mobile. A consistent mode selector offers Conversation, Ask, Learn, and Quiz. Each mode has a distinct purpose, while the composer, selected conversation, and available account/course context remain consistent.

| Mode | Purpose and conversation experience | Right-hand canvas |
| --- | --- | --- |
| Conversation — default | Everyday study partner: natural conversations, schedule checks, reminders, planning, quick preparation, and short explanations in message bubbles | Optional; everyday conversation does not require opening it |
| Ask | More developed, ChatGPT-like responses: thorough explanations, worked examples, analysis, headings, code, and citations when useful | Optional; a developed answer can stay in the conversation |
| Learn | The conversation remains available for questions, follow-ups, and guidance | Opens with the detailed explanation and existing lesson content |
| Quiz | The conversation remains available alongside the quiz workflow | Opens with the generated quiz and existing quiz interactions |

### Conversation versus Ask

Conversation is for talking through the student's day and study needs; Ask is for getting a developed answer. Their distinction is purpose and response style, not accuracy or capability. Conversation should be concise when appropriate but can respond at greater length when needed. Do not require a mode switch for every substantial question. It can offer “Explore in Learn” or “Practice with a quiz” when deeper study would help.

Example Buddy requests include “What is on my schedule today?”, “Remind me to review before class”, “Help me prepare in ten minutes”, and “What should I study next?” Ask requests include “Compare these theories in detail” and “Work through this problem step by step.” Schedule and reminder requests depend on available data and implemented integrations; these examples do not certify new capabilities as shipped.

When Buddy handles an action, distinguish a suggested plan from an actual saved change. Show a visible confirmation only after a reminder or schedule action succeeds. If it cannot complete the action, state that clearly rather than implying it was saved.

### Switching modes within a chat

Switching modes preserves the selected conversation and its context. New responses follow the selected mode; earlier messages keep their original presentation. A user can begin with “What should I review before class?” in Conversation and continue into a detailed lesson in Learn or practice in Quiz without starting another chat.

Selecting Learn or Quiz prepares that workflow; submitting the topic or explicitly requesting the activity starts generation. Opening or reopening a canvas alone must not generate duplicate content. Preserve existing lesson, quiz, and answer state when moving between the conversation and study content.

The right-hand canvas is the working area for deeper study. In Learn mode, detailed explanations belong here rather than forcing the entire lesson into a small bubble. In Quiz mode, questions and the existing answer, hint, feedback, and progress interactions appear here. Preserve existing workflow rules about when generation starts, how answers are submitted, and how learning context is retained; opening the canvas must not independently trigger duplicate requests.

Chat and canvas should clearly refer to the same selected conversation. Follow-up questions about a lesson or quiz retain the context already provided by the current application. Avoid duplicating the full lesson or quiz in both panes; the conversation can show a concise introduction or a control to reopen the relevant content.

## Reminders and proactive study support — core Buddy direction

Reminders are a central part of Buddy's study-partner experience. Users should be able to ask naturally, for example “Remind me to review biology at 7 tonight” or “Remind me tomorrow morning to finish this assignment.” Buddy should create the reminder and notify the user at the requested time through the available notification channels. This is a product requirement for implementation, not a claim that conversational reminder creation is already shipped.

### Creating and managing reminders in conversation

When the request includes enough information, create the reminder without an extra confirmation step. If the time is ambiguous or missing, ask only for the information needed to schedule it correctly. Interpret dates and times in the user's timezone and show the resolved date, time, and timezone in the saved reminder card. Recurring reminders should show their repeat schedule explicitly.

After the reminder is successfully saved, show a compact confirmation in the chat, such as “I'll remind you to review biology today at 7:00 PM.” Include controls to edit the time, cancel, or view the reminder. Do not show a successful confirmation before the save completes. Users can also change or cancel reminders conversationally, with clarification when several reminders match.

Provide a reminders view accessible from Buddy and the existing workspace navigation, showing upcoming and recurring reminders with their course or task context. Notification actions should let users open the related chat or study material, mark the task done, or snooze where supported. Reminder changes and completion should be reflected across signed-in devices once shared-data sync is implemented.

Show notification readiness clearly. A saved reminder and a deliverable device notification are distinct states: if notification permission is unavailable, show that limitation and the available delivery options. Account for timezone changes, daylight-saving transitions, offline devices, retries, and duplicate delivery during implementation. Do not silently reinterpret the requested time or promise exact device delivery when platform conditions prevent it.

### Proactive preparation without a request each time

Buddy should sometimes take useful initiative based on the student's known schedule, upcoming assessments, course materials, and learning progress. For example, before a midterm it can prepare a quick cheat sheet or study summary and tell the student, “I prepared a quick cheat sheet for your biology midterm tomorrow.” The student does not need to ask for each preparation task.

Other examples include a short pre-class refresher, a review checklist before an assignment deadline, or a practice quiz covering concepts the student has struggled with. Use confirmed course dates and available materials, and show the assessment or class that motivated the preparation. Cite sources and label any uncertainty about coverage; do not assume the generated sheet is permitted during an exam.

Deliver proactive work as a compact Buddy message or notification with a preview and an Open control. The full cheat sheet, lesson, or quiz opens in the canvas; on mobile it opens in the expanded study view. Keep outputs available for later rather than making a notification the only way to access them.

Users should be able to enable or disable proactive preparation, choose relevant courses, set quiet hours and notification frequency, and dismiss unhelpful suggestions. Once enabled, useful preparation can run without repeated approval prompts. Prioritize meaningful events, avoid repeatedly preparing the same material, and stop obsolete work when an assessment is cancelled or rescheduled.

Taking initiative here means preparing study content and surfacing helpful reminders. It does not imply permission to send messages to other people, submit coursework, purchase materials, or change an external calendar. Those actions require their own explicit user direction.

### Relationship to scheduled reminders

User-requested reminders follow the user's requested schedule. Proactive preparation is a separate, preference-controlled behavior that chooses useful moments based on study context. Quiet-hour handling must be explicit: proactive notifications respect quiet hours, while any adjustment to an explicitly requested reminder time must follow a visible user setting rather than silently moving the reminder.

Implementation depends on durable scheduling, notification permissions and delivery, account timezone/preferences, reliable assessment context, background task execution, and saved study artifacts. These dependencies extend beyond UI styling and belong to the feature implementation phase. The UI-only phase can design reminder cards, the reminders view, preferences, and proactive-content previews without claiming those services are operational.

## Personalized Buddies, home, and course integration

The detailed screen, navigation, ownership, and integration specification is [Personalized Buddies, home, courses, and class sessions](BUDDY_HOME_COURSES_AND_CHATS.md). This updates earlier single-companion wording: the target supports multiple customizable Buddies with multiple chats each, built on shared account-owned learning resources.

Students can choose a companion's name, avatar/character, accent color, communication style, and study preferences. Assign a preferred Buddy to each course; a Buddy may support several courses, and a class session can explicitly override the preference. Changing a course preference affects future sessions while preserving historical chat/session attribution.

Home is the selected Buddy's conversational study space: identity and greeting, a few real Today cards for the next class, deadlines, due review, or prepared content, followed by the composer. Existing chats open directly to their messages. Home/Today remains reachable separately. The desktop hierarchy is Buddy rail → chat/navigation sidebar → conversation → optional canvas. Sidebar history belongs to the selected Buddy; Courses, Review, and Reminders expose shared account resources.

Course pages show their preferred Buddy, next class/Start class, assignments, recent class sessions, materials, study outputs, and linked chats. Course chats are references to the same conversations shown in Buddy history. In-Class setup prefills course, Buddy, and materials; completed sessions link their notes, quizzes, recall prompts, and deck from the course history. All modes and companions invoke the same flashcard, quiz, retrieval, and learning services.

Reminders and proactive responsibilities are account-owned with companion/course attribution. They survive new chats and Buddy switching. Companion customization does not alter grading, permissions, or factual standards. Implementation starts with one default personalized Buddy and extends to multiple profiles/assignments through additive schema and UI changes.

## Desktop layout

Retain access to the existing sidebar, New chat, conversation history, course organization, and other workspace features. The selected chat occupies the main conversation area. When Learn or Quiz needs it, the right-hand canvas opens beside the conversation, leaving the composer available.

Allow users to close and reopen the canvas without losing the current lesson or quiz state. Reuse existing panel controls and sizing behavior where possible. Clearly label the canvas content as a lesson or quiz. Companion profiles and mode choices use the same interface and shared canvas components.

## Multiple chats

Each chat belongs to a stable Buddy profile and optionally a course/class session. A narrow Buddy rail switches companions; a collapsible sidebar lists the selected companion's chats and New chat. Switching companions restores its last chat or home state. Provide an explicit All chats search with companion/course labels. Unsent drafts remain scoped to their chats. The profile specification defines default assignment, historical attribution, archive behavior, and shared resource ownership.

Keep the current separate conversations and their history. New chat starts a fresh conversation in Conversation mode. Selecting a previous chat restores its messages and existing study context. Bubble styling and the canvas presentation do not change how chats are stored, named, or associated with courses. Mode selection does not create a separate chat history. Course context should remain visible near the composer where applicable.

## Mobile adaptation

Target mobile navigation is Buddy, Courses, Review, More. The avatar/name opens a companion switcher; a separate Chats control opens that companion's history. Notes remain available through course Study, More, and the canvas. This is the redesign target, distinct from the currently implemented phone bar. See the companion/home specification for screen details.

Use the same Buddy conversation and message bubbles. A phone cannot comfortably show chat and a right-hand canvas side by side, so present the existing lesson or quiz panel as an expanded screen or sheet with a clear return-to-chat control. This is a responsive presentation of the same content, not a separate mobile workflow. Preserve the selected conversation and in-progress work when moving between views. Keep the composer usable with the keyboard open and respect device safe areas.

Conversation remains the default on phones, with the same four mode choices. Ask offers developed responses within the conversation; Learn and Quiz open the expanded study view. Users should not have to learn a different mode model on each device.

## In-Class mode — live notes, quizzes, materials, and teaching assistance

In-Class is a dedicated class-session experience within the same Buddy interface. During class, the user can switch on their microphone and watch notes take shape live in the canvas as the professor teaches. Multiple coordinated agents prepare notes, generate relevant quizzes, and find supporting course materials concurrently. By the end of the session, the platform provides summary notes, a revision quiz, and active-recall practice.

Keep Conversation as the default everyday mode. In-Class is an explicitly started session available from the mode controls or course view, alongside the Conversation, Ask, Learn, and Quiz experiences. It retains the selected course and conversation context rather than creating another assistant identity. This is a future feature requiring implementation beyond the initial UI-only phase.

The user selects the course and explicitly starts a live class session. Show a clear microphone/recording indicator, elapsed time, and Pause and Stop controls. Make the distinction between recording a class and sending a short voice message clear.

As speech is transcribed, organize notes into headings, key ideas, definitions, examples, and questions in front of the user. Distinguish provisional text from settled notes, and allow corrections without silently overwriting the student's edits. Keep the current section visible without forcing scrolling when the user is reading an earlier section.

Buddy remains available beside the notes for questions such as “Explain what the professor just said” or “How does this connect to last week's topic?” Detailed teaching content opens in the canvas. On desktop, offer clear views for live notes, explanations, and source material within the existing canvas area. On mobile, show these as expanded views with a return-to-chat control and persistent recording status.

### Coordinated agents during class

| Responsibility | Live output |
| --- | --- |
| Notes agent | Structured lecture notes, key terms, examples, and unresolved questions |
| Materials agent | Relevant textbook passages, slides, and readings with source links |
| Quiz agent | Short checks for understanding based on concepts already covered |
| Revision agent | A developing summary and active-recall prompts, finalized after class |

Coordinate these responsibilities through one class session and shared, versioned lecture context. All agents should work from the same transcript segments and covered topics; mark provisional segments and revise derived content when transcription is corrected. Do not generate quiz questions about topics the professor has not yet covered merely because they appear later in a textbook. Separate lecture-derived content from supplementary material and preserve citations and lecture timestamps where available.

Present the results as one coherent study workspace, not separate agent chats. Compact status messages such as “Updating notes”, “Finding a textbook section”, and “Preparing practice questions” are enough; agent internals need not dominate the UI. On desktop, the canvas provides Notes, Materials, and Practice views. On mobile, these become selectable expanded views with recording status always accessible.

Generate live quizzes as the lecture progresses and make them available when the student chooses to practice. Show new-question availability without interrupting listening, automatically switching views, revealing answers, or requiring an immediate response. Keep questions stable once the user begins answering; flag a correction if a transcript revision changes a question's premise.

Recording and note capture remain usable if material retrieval or quiz generation fails. Show partial readiness and retries per output rather than treating the entire class session as failed. Preserve student edits and quiz attempts while agents update their own generated content.

### Course materials and sandbox-assisted retrieval

As the professor introduces a topic, the agent can find relevant passages in the student's available textbooks, slides, readings, and other course materials. The planned sandbox feature can support inspecting and processing those materials when needed. Retrieval should use materials the user has uploaded or connected and is authorized to access; this does not assume every textbook is automatically available.

Surface relevant chapters, pages, or sections alongside the live notes, with a short explanation of how they connect to the lecture and a link back to the source. Separate what the professor said from Buddy's explanation or supplementary textbook content. If speech or topic matching is uncertain, show that uncertainty rather than attaching an unrelated source confidently.

For example, when a professor starts explaining cellular respiration, the notes begin a section for that topic. Buddy finds the corresponding chapter in the course textbook, offers a cited supporting passage, and lets the student open a deeper explanation without leaving the class session.

Material lookup and processing should appear as compact progress states, leaving recording and note-taking usable. Show missing materials, failed retrieval, or unavailable sandbox execution with a retry or material-selection option.

### Finishing a class session

After Stop, retain the captured notes and automatically finalize a class revision package. Show “Finalizing” while processing completes; do not promise every output is ready immediately when recording ends. Make each completed output available independently:

- **Summary notes:** a concise overview plus organized notes covering the lecture's main concepts, definitions, examples, and outstanding questions, with links to relevant lecture passages and supporting materials.
- **Revision quiz:** practice across the topics actually covered, with answer explanations and feedback using the existing quiz experience once integrated. Keep missed or uncertain concepts available for follow-up study.
- **Active recall:** prompts that require the student to retrieve an explanation, definition, process, or comparison before revealing the answer. Offer a way to check the response and revisit difficult prompts; keep answers hidden until requested.

The post-class screen offers Review notes, Start revision quiz, and Practice active recall. The user can also continue a deeper explanation in Learn mode. Link all outputs to the same course and class session, preserve the original lecture notes, and clearly label generated summaries. Propose later review or reminders through Buddy without claiming a reminder was saved unless scheduling succeeds.

If recording or transcription was incomplete, identify the missing coverage in the revision package. A failed quiz or summary task should remain retryable without replaying or discarding the successful capture and other outputs.

### Dependencies and open design choices

This is a proposal, not a claim that In-Class mode, live transcription, continuous note generation, coordinated agents, or sandbox retrieval is implemented. It depends on audio capture and recovery, streaming transcription, incremental note updates, shared agent context, durable background processing, course-material retrieval, source attribution, and the sandbox integration where required. Specify recording permissions and classroom consent expectations, interruption handling, offline behavior, and save/upload status before implementation. Determine whether teaching suggestions appear automatically or only when requested, how much provisional note revision is acceptable during class, and the generation cadence and resource budget for concurrent agents.

### Acceptance criteria for the future In-Class feature

Activation, capture lifecycle, live processing, specialist coordination, frontend rendering, and finalization are specified in [In-Class mode architecture](IN_CLASS_MODE_ARCHITECTURE.md).

- Starting a class session selects a course and explicitly enables recording, with visible Pause and Stop controls.
- Notes appear incrementally while supporting materials and live practice questions are prepared concurrently.
- All generated outputs reflect covered lecture content and distinguish supplementary sources.
- Agent activity does not interrupt listening or overwrite student edits and in-progress answers.
- Ending a session produces summary notes, a revision quiz, and active-recall practice, with honest readiness and partial-failure states.
- The class session and its outputs remain accessible for later study through the same interface on desktop and mobile.

## Shared flashcard skill/agent

Flashcard creation is a shared capability callable from Conversation, Ask, Learn, Quiz, In-Class, or Review without changing the selected conversation mode. It can use notes, lesson content, course materials, lecture segments, and quiz mistakes to prepare editable, source-linked draft decks. The chat shows a compact result card; preview, editing, and review open in the canvas or expanded mobile view. Decks remain available under Review, organized by course.

The agent owns card generation and quality checks; platform services own saving, review attempts, scheduling, and notification delivery. Generating a deck does not establish mastery or automatically publish cards into scheduled review. The complete proposed contracts, data model, runtime integration, frontend rendering, and delivery sequence are in [Shared flashcard agent architecture](FLASHCARD_AGENT_ARCHITECTURE.md). This remains design work beyond the initial UI-only phase.

## Acceptance criteria for the UI-only implementation

- Both user and assistant messages use rounded message bubbles, with user messages on the right and assistant messages on the left.
- Existing multiple-chat navigation and conversation history continue to work.
- New chats open in Conversation, the default study-partner mode, across devices.
- Conversation, Ask, Learn, and Quiz are available within the same conversation, with clearly communicated purposes.
- Mode changes preserve context and earlier message presentation; new responses use the selected mode.
- Ask, Learn, and Quiz remain available with their existing functionality.
- Learn opens detailed learning content in the right-hand canvas on desktop.
- Quiz opens generated quizzes and their existing interactions in that canvas.
- Chat stays usable while the desktop canvas is open.
- Closing or reopening a panel preserves existing lesson and quiz state and does not start duplicate generation.
- Existing rich content, citations, attachments, response actions, loading, errors, and retry behavior remain usable.
- Phone layouts offer an accessible way to move between chat and expanded study content.
- Changes stay within UI presentation; backend contracts, storage, and learning workflows remain unchanged.

## Details to settle during design

Exact bubble colors, Buddy's visual identity, canvas width, and the phone sheet versus full-screen presentation remain design choices. Start with the existing application's visual system and the supplied reference rather than adding new capabilities.

Restore the saved response mode when reopening a chat, as defined in the behavior contract; new chats default to Conversation. In-Class capture never restarts automatically. Inventory which current capabilities support schedules, reminders, planning, and quick preparation; missing action capabilities belong to subsequent feature implementation rather than the UI-only phase.
