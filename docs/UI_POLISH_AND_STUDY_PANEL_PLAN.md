# UI polish and study panel plan

Scope: the UI/UX review of 13 October 2026 (screenshots of chat, Dashboard, Courses, Notes, Calendar, Concepts, Settings, the reading and visual previews, and every right-panel tab at 1440px, 1180px and 390px, light and dark) and the follow-up decisions on the right panel, visuals in notes, Practice and In-Class.

Work top to bottom. Each phase ends with a **Done when** check. Phases 1–3 are independent of 4–8 and can run in parallel.

## Decisions already made

- The right panel keeps **Notes, Canvas, Practice and In-Class**. Sources and Reminders leave the panel. Flashcards move inside Practice.
- **Canvas** holds what the agent makes (visuals and versions of them). **Notes** is where the learner keeps them.
- **In-Class** opens from a course page *and* stays available as a panel tab.
- **"Add to note" is selective.** It is never a chip on every message or every visual. It appears as a quiet action in a visual's own toolbar, and is suggested only for visuals the learner engaged with (see 5.3).

---

## Phase 0 — Prepare the codebase

- [ ] Run Prettier over `web/` in a formatting-only commit. Many components and CSS modules are single lines over 2,000 characters, which makes visual diffs unreviewable.
- [ ] Fix the 7 failing web tests in `web/tests/study-dashboard.test.tsx` and `web/tests/study-workspace.test.tsx` (their mocks lack `request` and `listWorkspaceNotesPage`).
- [ ] Fix the 31 ESLint errors (mostly React Compiler rules: setState inside effects, refs read during render).
- [ ] Add `npm run lint` and the full `npx vitest run` to the `frontend` job in `.github/workflows/platform-quality.yml`. Today CI runs neither, so these failures were invisible.
- [ ] Rename `web/package.json` `name` from `site-creator-vinext-starter` and update the stale `web/README.md` ("Forma", sample maps).

**Done when:** `web/` lint and all web tests pass in CI.

## Phase 1 — First impressions

- [ ] **Install popup** (`web/components/app-install.tsx:26`): stop opening it 1.5s after first load. Show it only after the 3rd session *and* only when `beforeinstallprompt` fired. Otherwise offer "Install app" in the account menu. It currently covers the whole composer on phones.
- [ ] **Empty chat screen:** centre the greeting over the composer (it currently starts at neither the composer's edge nor the centre). Add 3–4 starter cards (Explain a concept · Quiz me · Upload my notes · Plan my week) and a "Continue where you left off" row when history exists.
- [ ] **Waiting state:** replace the grey "Stop generating" chip shown in the assistant slot with a typing indicator. Keep Stop in the composer only.
- [ ] **AI unavailable state:** when no provider answers, show a clear message with Retry and a link to Settings → AI service instead of a 30-second silent wait.

**Done when:** a first-time visitor on a 390px phone can see and use the composer immediately, and an unavailable provider produces a visible, actionable message.

## Phase 2 — Design system

Current CSS: 597 distinct hex colours, 108 font sizes, 62 radii, 73 shadows, ~15 breakpoints, 130 `!important`.

- [ ] **Load the font.** `--font-sans` names Inter but nothing loads it. Self-host Inter (or a chosen heading face) with `@font-face` and `font-display: swap`.
- [ ] **Type scale:** 12 / 13 / 14 / 16 / 18 / 22 / 28. Minimum UI text 13px (today 12px is most common and 10–11px appears 150+ times). Wire the existing `--type-*` tokens to it.
- [ ] **Colour tokens:** reduce to ~20 semantic tokens (surface, surface-raised, border, text, text-muted, accent, accent-soft, success, warning, danger…). Light and dark values for each.
- [ ] **Radii** 6 / 10 / 16 / full. **Shadows** sm / md / lg. **Breakpoints** 640 / 1024 / 1280.
- [ ] **Buttons:** three variants only — primary (filled), secondary (outline), ghost. One primary per screen.
- [ ] Replace every native `<select>` (Calendar view, Settings density/text size, chat search buddy filter, Practice "Study from", In-Class "Save this class in") with the shadcn `Select` already in `web/components/ui/select.tsx`.
- [ ] Use `→` (or no icon) for in-app navigation buttons. Keep `↗` for external links only (Dashboard uses `↗` for "Open review", "Open calendar").
- [ ] Migrate CSS modules to tokens one screen at a time, then add stylelint `declaration-strict-value` for `color`, `background`, `font-size`, `border-radius`, `box-shadow` so raw values cannot return.
- [ ] **Dark mode:** base `#111`–`#161616` instead of `#050505`; raised surfaces in small steps (`#1b1b1b`, `#222`); visible borders; keep a hint of the sage accent.

**Done when:** a token audit shows ≤25 colours, ≤8 font sizes, ≤4 radii, ≤3 shadows outside `web/vendor`, and the stylelint rule passes.

## Phase 3 — Navigation and page shell

- [ ] **One destination list** for desktop and mobile. Today the desktop rail has Home, Search, Courses, Calendar (no Notes); the mobile menu has Buddy, Courses, Calendar, Notes, Dashboard, Review, Reminders, Settings.
- [ ] Tooltips on every rail icon; consider an expandable rail with labels.
- [ ] Use one name for Home/Dashboard.
- [ ] **One title per page:** drop either the top-bar title or the page heading on Courses, Calendar, Dashboard and Notes; drop the small all-caps label above headings where it repeats them.
- [ ] Remove the stray "›" active marker beside the Buddy avatar in the rail.
- [ ] Put `/concepts` inside the shared layout and style its inputs and buttons (today they have no borders and "Find concepts" doesn't look like a button).
- [ ] Keep the Buddy header on Settings for consistency.
- [ ] Notes list column: make its background fill the full height.
- [ ] Notes: remove the duplicate "New note" button and make "New folder" the same button variant.

**Done when:** every route renders in the same shell with the same navigation on desktop and mobile.

## Phase 4 — Right panel restructure

### 4.1 Remove and merge

- [x] **Remove the Sources tab** (`sourcesPanel` in `web/components/workspace-panel.tsx`).
- [x] **Citation popover:** clicking a citation in chat opens a popover with the exact passage, page number and "Open in file". Re-point `WORKSPACE_SOURCE_OPEN_EVENT` to it.
- [ ] Move uploaded files under each course's materials.
- [x] **Move Reminders** out of the panel to Calendar and the Dashboard.
- [x] **Merge Flashcards into Practice** (details in Phase 7). Re-point `WORKSPACE_FLASHCARDS_OPEN_EVENT` to Practice with the Flashcards view selected.
- [x] Update `WorkspaceTab`, `tabNames`, `validLayout` in `web/components/workspace-split.tsx`, and migrate stored layouts (`forma-workspace-panel-v1`) that reference removed tabs.

### 4.2 Header and tabs

- [x] **Tool selector:** a fixed segmented control with icon + label: Notes · Canvas · Practice · Class. Tools are always present and are never opened or closed.
- [x] **Document tabs** in a second row, only for open notes (the row scrolls; an overflow menu after ~5 is still to do). Fixes today's truncated tabs ("Reminde", "Rem") and the ▾ switcher overlapping them.
- [x] Remove the ▾ switcher and the ＋ launcher (they list the same items; the ＋ menu runs off-screen).
- [x] Keep three header controls — Expand, Pin, ⋯ (close, reset width, help) — at ≥28px with tooltips.
- [ ] **One open/close toggle** (the chat header button), shown as "on" while the panel is open. Remove the panel's second toggle.

### 4.3 One layout for every tool

- [x] Build a shared `PanelSection` component: icon · title · one-line description · optional primary action; content with 16px padding; optional sticky footer for the main action. Model it on the Reminders tab.
- [ ] Apply it to Notes, Canvas, Practice and In-Class. Canvas and Flashcards are currently unstyled — fix those first.
- [x] Top-align In-Class (it is the only tool centred vertically and jumps when switching).
- [ ] Notes empty state: remove the lone "hide list" icon when there are no notes; add "Start a note from this chat".

### 4.4 Layout and behaviour

- [x] **Visible resize handle:** grip on hover, 8px hit area, `col-resize` cursor, double-click resets width. (The handle exists in `workspace-split.tsx` but looks like a 1px border.)
- [ ] Minimum width ~420px; remember width per tool. *(Minimum width of 380px done; per-tool width not yet.)*
- [x] **Below 1220px:** add a dimmed backdrop and edge shadow (or push the chat narrower) so the chat is not cut mid-word; fold "Return to conversation · Study workspace" into the panel header.
- [ ] **Focus mode:** centre content at ~720px; turn the "Chat with Buddy" pill into a docked mini-chat. *(Centring done at 760px; docked mini-chat not yet.)*
- [ ] Slightly different panel surface (`--sidebar` in light, `#141414` in dark) and a soft inner shadow on its left edge.
- [x] 200ms slide-and-fade open/close using the `motion` import already in `workspace-split.tsx`; respect reduced motion.
- [ ] **Context bar:** one line under the header, "Linked to: *‹chat title›*", with a switcher.
- [ ] Badges: a dot on Canvas when a new visual arrives; a count on Practice when items are due.

**Done when:** the panel shows exactly four tools with one header pattern, works at 1180px without covering the chat, and old stored layouts load without errors.

## Phase 5 — Visuals in notes

Existing foundation: notes already store ` ```visualization-ref ` blocks (`web/lib/study-capture.ts`, `backend/app/study_note_service.py:430`) and render them via `web/components/visualization-reference.tsx` — but only for lesson charts, only when a whole chat is saved, and only as a collapsed list at the bottom of the note.

### 5.1 Reference format

- [ ] Define one block for both visual types:
  ````
  ```visual
  {"kind":"generated","id":"vis_123","revision":2,"lessonId":"lesson_abc","state":{"length":1.2},"title":"Pendulum"}
  ```
  ````
  `kind` is `lesson` or `generated`; `revision` is pinned; `state` holds saved control values.
- [ ] Keep reading old ` ```visualization-ref ` blocks (map to `kind: "lesson"`).
- [ ] Backend: an owner-scoped endpoint to fetch a generated visual by id + revision (lesson visuals already have `GET /v1/lessons/{id}/visualizations/{id}`).
- [ ] When a newer revision exists, show "Newer version available · Update" on the embed.

### 5.2 Inline rendering in the note editor

- [ ] Render each block **where it sits in the text**, as a locked block (`contenteditable="false"` figure) that can be moved or deleted but not typed into; serialise it back to the fenced block on save.
- [ ] Remove the bottom "Lesson visuals" list once inline rendering ships.
- [ ] Store a **snapshot image** per embed (reuse the screenshot from `backend/app/visual_verification.py`). Use it for Markdown/PDF export, print, mobile and as the loading placeholder.
- [ ] Revisit the editor: if more block types are planned, move notes to TipTap/ProseMirror instead of extending `contentEditable` + `execCommand`.

### 5.3 Selective "Add to note"

- [ ] **Quiet action:** an "Add to note" icon in each visual's own toolbar (next to full screen / export), in chat and in Canvas. Not a chip under every message.
- [ ] **Suggest only on engagement.** Show a single inline suggestion "Keep this in your note?" (Add · Not now) only when the learner engaged with the visual: moved a control, opened full screen, asked Buddy to edit it, or spent more than ~20s on it.
- [ ] Suggest at most once per visual; never for visuals already in a note; "Not now" is remembered.
- [ ] Setting: Suggestions **On / Off** for "Keep visuals in notes".
- [ ] Destination picker: this chat's note (default) · another note · new note. If a note is open in the panel, insert at the cursor.

### 5.4 Creating visuals inside notes

- [ ] **"Visualize this"** in the note's selection toolbar (beside Add to chat / Explain / Ask in side chat). Runs the visual pipeline with the selected text and the note as context; inserts the result below the selection.
- [ ] **`/visual` slash command:** pick one of this chat's visuals, or type a prompt to generate in place.
- [ ] Drag a visual from Canvas or chat into an open note (last).
- [ ] **Lesson → note:** "Save this lesson as a note" as a primary lesson action, copying text and visuals into a learner-owned note (extend `captureReadingBlocks`).

**Done when:** a learner can create a visual from selected note text, add an existing visual to a note from its toolbar, see both inline, and export the note with images.

## Phase 6 — Canvas as the visual workbench

- [ ] Thumbnail strip of every visual in the current conversation, newest first.
- [ ] Version history per visual (lineage already exists: "Version 2").
- [ ] Actions: Add to note · Edit with Buddy (sends "change X" to the chat) · Full screen · Export image.
- [ ] Empty state: faint sample visual and "Ask Buddy to *draw*, *graph* or *simulate* something", with one suggested prompt.
- [ ] In chat, show a small "Open in Canvas →" on visuals; clicking slides the panel open on Canvas.

**Done when:** every visual from a conversation can be found, compared by version, edited and sent to a note from Canvas.

## Phase 7 — Practice hub (quizzes + flashcards)

Existing data: `GET /v1/quizzes` (status, origin), review sessions and the learner review dashboard (`backend/app/review_routes.py`), `GET /v1/flashcard-decks` (filterable by course).

### 7.1 Layout

- [x] **Continue:** unfinished quizzes and review sessions with progress ("3/8 answered") and Resume.
- [ ] **Due today:** due flashcards + concepts due for review, time estimate, one "Start mixed review" button. *(Counts with links done; mixed review needs the backend session.)*
- [ ] **From your classes:** quizzes and decks grouped by class/lecture and course, with status (not started / % done / done).
- [ ] **Weak spots:** concepts with repeated misses → "Practice this".
- [x] **History:** completed quizzes with scores (collapsed).
- [x] **New:** one create flow with a Quiz | Flashcards toggle, source picker (this chat · a note · a class) and optional focus. Remove the duplicate "Make flashcards" buttons.
- [x] Practising runs in the panel; Expand switches to focus mode.

### 7.2 Backend

- [x] First version: aggregate the three existing endpoints on the client.
- [ ] Add `class_id` (lecture/class session) and `course_id` to quiz and flashcard-deck records when created from a class — migration plus writers in the quiz and flashcard services. Needed for "From your classes".
- [ ] Expose unfinished state (current question index, answered count) on quiz listings if not already present.
- [ ] Mixed review session that interleaves due flashcards and due concepts.
- [ ] `GET /v1/practice/overview`: one owner-scoped call returning the sections above, ranked.

### 7.3 Elsewhere

- [ ] "Due today" card on the Dashboard.
- [ ] "Quiz me on this note" in the note menu, opening Practice with the note preselected.

**Done when:** a learner opening Practice sees unfinished work first, can resume a quiz from a past class, and can start one review covering everything due.

## Phase 8 — In-Class

- [ ] **Start from a course:** a "Start class" button on each course page that opens In-Class with the course preselected.
- [ ] Keep the **Class** tool in the panel for starting a general or course class from a chat.
- [ ] After a class ends, link its notes, quiz and flashcards to the class so they appear in Practice → From your classes and on the course page.

**Done when:** a class can be started from a course page or the panel, and its outputs appear under that course and in Practice.

## Phase 9 — Content polish

- [ ] Reading view: one accent for callouts (today the "Key idea" box is amber with a green label inside); clearer heading sizes relative to body.
- [ ] Hide the "text" language label on plain code blocks.
- [ ] Charts: single colour for single-series bars; less empty padding under charts.
- [ ] Empty states for Notes and Calendar routines at the same standard as Courses (icon, one sentence, one action).
- [ ] Skeleton loaders for Dashboard, Courses and Practice.
- [ ] Motion: fade-and-slide for incoming messages; one open/close animation shared by sheets, menus and popovers.

## Phase 10 — Mobile

- [ ] Study tools open as a **bottom sheet** from a "Tools" button in the composer row (snap points at half and full height) instead of a separate page.
- [ ] Practice as a home tab on mobile.
- [ ] Verify every phase above at 390px.

---

## Suggested order

1. Phase 0, then Phase 1.
2. Phase 4.1–4.3 (panel cleanup and shared layout).
3. Phase 5.1–5.3 (reference format, inline embeds, selective "Add to note").
4. Phase 7.1 with client aggregation, then 7.2.
5. Phases 2 and 3 in parallel with the above, screen by screen.
6. Phase 5.4, Phase 6, Phase 8.
7. Phases 4.4, 9 and 10.
