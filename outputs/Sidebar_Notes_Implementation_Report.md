# Sidebar and Notes implementation report

Implemented September 29, 2026.

## What was built

- One sidebar with an accessible Home/Notes tab switcher, contextual New menu, persistent Review/Quiz launchers, shared Courses, contextual chat/note lists, and the existing account footer. There is one visible sidebar collapse control, including in the mobile drawer.
- URL persistence for the active tab, selected course, and selected note. Switching tabs retains the mounted editor and list state. An explicit All courses selection survives refresh.
- Notes grouped into Folders, Your notes, and Generated, with previews, note-type icons, course tags, edited dates, duplicate-title disambiguation, and an accent on the selected note.
- Shared chat/note title generation, plus a revision-safe legacy-title repair endpoint. Explicit user titles are protected. Previews skip prompts, headings, and study-note boilerplate.
- Mutually exclusive empty and blank-editor states. Note actions include Discuss, Record a class, and an overflow menu for rename, move, delete, and Markdown export.
- Shared reading width, heading scale, and Markdown/math rendering configuration for notes and tutor messages.
- A reusable compact tutor chat with the existing composer and streamed generation pipeline. It attaches revision-bound note context, persists its own conversation, supports retries and cancellation, and leaves the main chat and Notes URL intact.
- Recording failures and resumable uploads live in the actionable inline recording banner. The processing-start toast dismisses automatically after four seconds. Orphaned local audio without a note retains a recovery notice.

## Main files

| Area | Files |
| --- | --- |
| Sidebar and routes | `web/components/workspace-sidebar.tsx`, `web/components/learning-workspace.tsx`, `web/components/chat-history.tsx`, `web/app/chat/page.tsx`, `web/app/notes/page.tsx`, `web/lib/workspace-navigation.ts`, `web/lib/learning-workflows.ts` |
| Notes and editor | `web/components/workspace-panel.tsx`, `web/components/workspace-panel.module.css`, `web/lib/note-list.ts`, `web/lib/api.ts` |
| Compact discussion | `web/components/compact-tutor-chat.tsx`, `web/components/compact-tutor-chat.module.css` |
| Shared rendering | `web/lib/markdown-rendering.ts`, `web/components/rich-content.tsx`, `web/components/reading.module.css`, `web/components/learn-chat.module.css`, `web/app/globals.css` |
| Recording status | `web/components/class-recorder.tsx`, `web/components/lecture-notes-view.tsx`, `web/lib/recording-ui.ts` |
| Backend titles and metadata | `backend/app/content_titles.py`, `backend/app/main.py`, `backend/app/workspace_note_service.py`, `backend/app/workspace_note_routes.py` |
| Regression coverage | `web/tests/notes-sidebar.test.tsx`, `web/tests/recording-status.test.tsx`, `web/tests/compact-tutor-chat.test.tsx`, `backend/tests/test_content_titles.py`, `backend/tests/test_workspace_notes.py` |

## Courses and folders

The existing backend course entity is the canonical source. Sidebar courses use `CourseSummary` IDs; chats reference `courseId`, and notes reference `frontmatter.course_id`. Both tabs filter against these same IDs. Legacy generated notes can acquire a course ID through their explicitly linked, owner-matched session. Course names are never used to infer identity. The course arrow still opens the existing course page.

Custom folders are separate from courses. A populated folder is stored in a note's `note_folder` metadata and can be recovered from backend notes. The catalog of empty custom folders remains in localStorage because the backend has no standalone folder resource. Consequently, an empty folder is device-local; it will not sync to another browser before a note is placed in it. No duplicate course store was introduced.

## UI-only support and deviations

- Discuss, note editing, course navigation, and recording retry use real backend paths; they are not stubs. The compact discussion component can be reused by future concept links, but this task does not add new concept-link routing.
- The formatting toolbar uses the brief's allowed fallback: hidden for an empty note, docked once the body contains content. The existing contenteditable editor does not provide a selection-toolbar plugin; replacing the editor would expand the scope and risk existing editing behavior.
- Full-note Discuss attaches the opening 6,000 characters with exact revision/offset information. Longer notes display an explicit opening-passage notice; selecting an excerpt allows discussion of another section.
- A Your notes list accompanies the requested Folders and Generated groups so manual and recorded notes remain discoverable.

## Validation

- TypeScript: `npx tsc --noEmit` passed.
- Frontend: `npx vitest run` — 16 tests passed across four files, including existing tutor component coverage and selected-note restoration.
- Backend: workspace-note, title, and lecture-pipeline suite — 24 tests passed. The simulated-hour lecture test was excluded; existing SQLite datetime deprecation warnings remain.
- Browser: desktop 1440×900 and mobile 390×844; no horizontal overflow at mobile width; one visible collapse control; keyboard Home/Notes tab switching; keyboard note opening; shared course selection across tabs; note/course/tab restoration after refresh.
- Real flows exercised: contextual folder creation, blank note creation, autosave, course navigation, compact Discuss with a streamed tutor response, and a new main chat with a completed tutor response. A temporary stream interruption during the development server reload recovered through the existing durable conversation flow.
- Recording upload/retry and persistent-banner behavior were covered through backend and component tests. Actual microphone capture and OS permission prompts were not exercised.

A sample folder and note named Sidebar verification were created during browser validation. Existing unrelated working-tree changes were preserved. No commit or deployment was performed.

## Local preview

Open http://127.0.0.1:3000/notes with the local frontend and API running.

## Screenshots

Desktop: [sidebar-notes-desktop.jpg](sidebar-notes-desktop.jpg)

Mobile: [sidebar-notes-mobile.jpg](sidebar-notes-mobile.jpg)
