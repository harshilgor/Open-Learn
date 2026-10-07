# Student study workspace

Implemented in the existing Open Learn frontend. Existing authenticated notes, materials, quizzes, flashcards, note drafts and visualization APIs remain the persistence and execution boundaries.

## Student flows

- Open the study workspace beside chat on desktop. Drag the separator or use its arrow keys to resize. On phones there is no right-side workspace or bottom navigation. A compact header menu opens the main destinations; notes and linked study tools open as full pages. The desktop workspace remains beside chat.
- Notes, Sources and Practice are always available. Canvas opens on demand from a diagram; additional flashcard and class tabs retain their existing functionality.
- Notes use one main editor. The searchable note picker overlays the editor and closes when a note opens. The empty state offers recent notes, a blank note and Capture this conversation.
- Completed chat responses offer Save to note. Students preview the addition, choose a new or existing note, then confirm. Appending fetches the latest note revision and uses the existing conflict check. Failures preserve the preview. Original explanation links use the durable `/s/:sessionId` route and message anchor.
- Saved explanations preserve durable lesson visualization references alongside Markdown. Equations use the existing math renderer. Canvas reuses the interactive visualization renderer.
- Select a unique passage in a saved note to Explain this, Give an example, Check my understanding, Make flashcards, Suggest improvements or Revisit later. Selection context includes note ID, revision and exact offsets; ambiguous or unsaved selections are excluded.
- Chat passage actions prepare a question and add a removable Using context chip. Sending remains the student's choice, and existing composer text is preserved.
- Suggest improvements requests a grounded draft from the selected note through `/sessions/:id/note-drafts`. It displays the existing draft review card: save separately, replace the selected section with a revision check, or discard. It does not directly overwrite a note.
- Revisit later appends a checklist item under Question to revisit. Checklist controls are usable in the rich editor and changes follow normal note persistence.
- Sources opens cited passages, lists other passages and supports asking about the selected text or passage. These prepared questions explicitly label the text as learner supplied; they do not elevate it into verified evidence.
- Practice lets students choose a saved note for grounded flashcards or a conversational understanding check. Linked study notes expose their existing lesson quizzes, history, results and feedback. Current conversation quizzes reuse the existing quiz workspace. Personal notes use conversational checks rather than being passed as canonical lessons.
- Account changes clear workspace launches and visuals and remount the panel. Note capture ignores stale responses after account changes.

## Implementation entry points

- `web/components/workspace-panel.tsx`: editor, source inspection, practice and canvas.
- `web/components/workspace-split.tsx`: desktop resizing, mobile dialog, launch events and account reset.
- `web/components/save-to-note.tsx`: preview and confirmed append/create.
- `web/components/learn-chat.tsx`: response capture, note context and improvement drafts.
- `web/lib/study-capture.ts`: explanation Markdown and durable visual references.
- `web/lib/workspace-events.ts`: typed UI integration events.

No new database tables or provider keys are required. AI generation uses the current usage-metered backend services. Questions to revisit are ordinary learner-owned Markdown, so they follow existing note storage and account restoration.

## Verification

Automated UI tests cover explicit save approval, append preservation, revision conflicts, saved selection offsets, draft-only improvement requests and revisit persistence. Existing note/sidebar and tutor component tests are included. TypeScript and production build checks are run separately.

Browser inspection covers phone and desktop layout and note picker behavior. The local preview backend is unavailable, so authenticated live generation, provider responses and production persistence need a connected-backend acceptance pass. This change has not been deployed.

Acceptance with a connected backend: capture a response to both destinations; reopen the original explanation; select a note passage and send each prepared action; accept and discard an improvement; mark a revisit item complete and reload; inspect a citation and another passage; generate cards from a note; resume a lesson quiz and inspect mistakes; open an interactive visual in Canvas; switch accounts and confirm previous content is cleared.
