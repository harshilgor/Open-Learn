# Open Learn study workspace redesign — coding agent brief

## Objective and scope

Implement a cohesive right-hand study workspace, improved notes editor, selection context, independent side chats, Focus view, and integration with existing chat, voice, and agent tools. This is an implementation request, not a request for another proposal or a static mockup. Complete the real flows, persistence, error handling, responsive behavior, and verification.

Preserve the existing compact left navigation and messaging-style chat. The right side should feel like part of the same product: quiet, useful, and easy to understand. Keep existing OpenRouter free routing and provider choices. Do not introduce a new paid service to implement these features.

## Product principles

- Conversation stays on the left; the current piece of work lives on the right.
- Use compact typography, subtle borders, the existing theme tokens, small icons, and restrained buttons. Support both light and dark themes.
- Avoid large gray tab strips, promotional empty states, permanent secondary navigation rails, and grids of feature cards.
- Preserve student control: never replace work that is being edited or explicitly pinned.
- Every interaction available by voice must have an accessible visual equivalent.
- Selecting text alone must not send a request, modify a note, or incur generation work.
- Report actual capabilities honestly. Do not present unavailable integrations as working.

## 1. Right workspace layout

Start at approximately 35% of the available desktop content width, with resizing and sensible minimum widths. Remember the chosen width. For new conversations, keep the panel closed until the student opens it or requests an artifact that belongs there.

Replace the permanent Notes / Sources / Practice / Reminders strip with one compact header:

`[Current item title ▾]                       [Pin] [Expand] [Close]`

The title dropdown provides search, recent/open items, and access to Notes, Sources, Practice, Reminders, and Visuals. Creation actions belong in this switcher or the relevant empty state. Keep frequent actions discoverable without building another permanent sidebar.

Switching items preserves document page and scroll position, note cursor/selection where practical, quiz answers, and drafts. Closing the panel does not delete its items. Pinning prevents automatic replacement. Agent-created results open when the panel is idle; otherwise display a compact actionable notice such as “Quiz ready · Open”.

Show loading and failure messages near the affected content/action. Use “Couldn’t load notes · Retry” for an ordinary loading failure; reserve prominent warnings for unsaved work or an action needing attention.

## 2. Selection toolbar and shared context

Use the user's reference: a small horizontal toolbar adjacent to the selection, with three actions:

**Add to chat · Explain · Ask in side chat**

- **Add to chat:** attach the selected material to the active conversation's composer, focus the composer, and do not send automatically.
- **Explain:** submit a clear explanation request with the selection to the active conversation. Preserve the source view.
- **Ask in side chat:** create an independent side conversation anchored to the selection and focus its empty composer. Do not generate an answer until the student asks something.

Position the toolbar within viewport bounds. Preserve the selection when clicking it. It must not interfere with native copying, touch selection handles, keyboard selection, scrolling, or input editing. Provide keyboard/context-menu access and dismiss with Escape. Selecting inside a toolbar or composer must not recursively invoke it.

Support text in notes, chat responses, and document readers. PDF selections include document and page references. Equations, diagrams, and quiz answers need equivalent structured item selection, not brittle extraction of their rendered text alone. Inspect current PDF/selection infrastructure before implementing another layer.

Attached context appears as a small removable chip above the composer, for example `↳ Biology.pdf · p.12 ×`. New selection context replaces the pending selection reference for that composer; it must not discard attachments or drafts. Sent messages retain an immutable reference/excerpt so later selection changes cannot change their meaning. Clicking a reference returns to the source location; missing/deleted sources receive a graceful fallback.

Voice requests such as “Explain this” use the active conversation's attached/current selection, with the source visibly indicated. If no reference exists or it is ambiguous, ask a brief clarification. Never silently attach selections from another side chat.

## 3. Notes redesign

Make the editor the main surface rather than a large centered empty-state card.

- Quiet header: editable title, save status, overflow menu.
- New note: “Untitled note”, writing cursor, and immediate typing. Do not persist empty notes merely from visiting the panel.
- Note switcher: searchable recent notes, optionally grouped by course; no permanent nested sidebar.
- Formatting: compact contextual tools on selection; keep routine writing free of persistent controls.
- “Create from conversation” is a secondary action and only enabled when there is conversation content to capture.
- Saving a passage or explanation includes a small source reference back to the relevant chat message, document, or page.
- Selecting note text supports explaining it, asking Buddy about it, rewriting, adding examples, or creating practice. Do not add every action to the three-button selection toolbar; use the conversation for richer requests.
- Agent edits target the relevant note/revision. Show substantial replacements as a proposal with **Apply / Keep original**. After applying, provide Undo and retained version history.
- Auto-save with explicit states: saving, saved, offline/local draft, and retry needed. Preserve local drafts during network failure, reconcile on reconnect, and avoid silently overwriting a newer server revision.
- Practice can be created from a note or selection. At the student's request, save missed concepts into review notes with links to their origins.

Reuse existing note storage/editor capabilities where available. Choose any additional editor dependency only after inspecting the current implementation and explaining the need in the implementation notes.

## 4. Side conversations

Students can open multiple independent conversations while concentrating on a document or note.

Each floating chat has:

- A short topic title and draggable header.
- A source-context chip/reference.
- Compact messages and the existing slim composer.
- A minimize control. Put secondary actions, including closing/removing the popup, in a title menu.

Minimized conversations appear as topic chips along the bottom. Restore them without losing messages or drafts. Closing a popup must have an unambiguous meaning and must not silently delete saved history. Persist open/minimized state and reasonable window positions; clamp positions after viewport changes. New windows should avoid the current selection and existing windows where practical. Keep layering predictable.

Use the selection toolbar as the primary entry point. Voice commands such as “Discuss this separately” or “Open a side chat about this” should call the same workspace action. Dragging a selection into available space is an optional shortcut only after the primary accessible flows work; it is not required for discovery or task completion.

Each side chat gets an independent saved conversation/session, source reference, message history, and draft, with a link to its parent conversation where appropriate. It shares the authenticated account, Buddy identity, and authorized course context, not unrelated messages from sibling conversations. Reuse existing chat/session APIs and components.

Only one conversation receives microphone input at a time. Clearly indicate which one is listening. Switching conversations must not misroute an in-flight response or transcript. Generated responses remain attached to their originating conversation.

## 5. Focus view and responsive behavior

Expand makes the current document/note fill the available workspace and collapses the main chat into an accessible floating conversation. Restore returns to the prior panel arrangement without losing state. Support natural-language requests such as “Let me focus on this document” through the same action contract.

On phones, show one document/workspace view and one chat sheet at a time. Provide a simple conversation switcher rather than overlapping movable windows. Preserve the same source context, history, drafts, and tool behavior. Respect safe-area insets, software keyboards, touch targets, reduced motion, and zoom.

## 6. Workspace content and agent actions

All outputs are persistent items with stable identity, ownership, and revision where editable:

| Item | Required experience |
| --- | --- |
| Notes | Edit, auto-save, review proposed changes, restore versions, follow source links. |
| Sources | Read documents, return to cited passages, select material and ask about it. |
| Practice | Answer one question at a time, retain progress, review feedback and mistakes. |
| Reminders | Compact upcoming list, completion and rescheduling through existing tools. |
| Visuals | View generated diagrams/graphs, expand, and download where supported. |

“Make question three harder” must target the existing quiz. “Add an example” must identify the relevant note or ask which item. Prevent stale writes with revision checks and avoid duplicating artifacts on retries.

After a wrong practice answer, offer contextual next steps: show the relevant passage, explain another way, or try a similar question. Use demonstrated answers as learning evidence; do not infer a fixed learning style.

Use compact progress such as “Creating 5 questions from Chapter 3…” and Cancel. Cancellation should stop work where supported and otherwise prevent a late result from unexpectedly changing the view. Represent failure/retry and completed results honestly. Preserve the current item while the student edits it.

## 7. Architecture and repository integration

Inspect current code and applicable repository instructions before changing anything. The worktree contains ongoing work: preserve unrelated changes. Useful starting points (verify their current responsibilities):

- `web/components/workspace-panel.tsx` and `workspace-panel.module.css`
- `web/components/learning-workspace.tsx`
- `web/components/learn-chat.tsx`, `learn-chat.module.css`, and `chat-composer.tsx`
- `web/components/class-pdf-reader.tsx`
- `web/components/voice/voice-provider.tsx` and `voice-dock.tsx`
- Existing notes, session, source, tool execution, and persistence services
- `docs/STUDENT_WORKSPACE_IMPLEMENTATION.md`
- `docs/VOICE_TUTOR_IMPLEMENTATION_PLAN.md`

Create or extend a typed shared workspace state/action layer. It should express:

- Layout mode, panel width, active item, open/recent items, and pinned state.
- Item identity/type/revision and source location.
- Active conversation and per-conversation pending selection context.
- Dirty/save status, reading position, and recoverable drafts.
- Side-chat identity, parent/source references, position, and minimized state.
- Agent operation status, target item, cancellation, and pending-result notices.

Define common actions for UI, chat tools, and voice: attach context, open item, create side chat, focus/restore workspace, propose/apply edit, and show operation result. Reuse the current transport/event mechanisms. Do not create a separate voice-only implementation.

Persist durable items and conversations on the server. Store layout preferences and local drafts under account-scoped keys; clear/switch correctly at logout/account changes. Validate all item access on the server. Treat selected document content as untrusted source material, never higher-priority instructions. Bound context payloads and preserve source provenance. Avoid sending entire documents on every message.

## 8. Build sequence

1. Audit current components, APIs, state, and tests; document reuse and required schema/API additions.
2. Implement the compact workspace shell, item switcher, resizing, pinning, and state restoration.
3. Redesign Notes with reliable auto-save, draft recovery, and source references.
4. Implement selection toolbar and immutable message context for text and structured items.
5. Reuse chat/session infrastructure for independent side conversations and Focus view.
6. Connect artifact updates, agent progress/cancellation, practice feedback, and voice workspace actions.
7. Verify complete workflows on desktop and mobile, fix integration issues, and document any concrete blockers.

These are implementation dependencies, not separate MVP releases. Do not claim completion on the strength of fixture screenshots alone.

## 9. Acceptance criteria and verification

- Right panel matches the compact chat design, opens at a sensible width, resizes, restores state, and never hides active work unexpectedly.
- Selecting text reveals the three-action toolbar. Native copy works. Add to chat does not send. Explain sends once with the correct source. Ask in side chat opens an independent draft.
- Sent context references remain correct after selection changes, refresh, and switching items.
- Notes save and reopen correctly; offline edits survive refresh; concurrent edits do not silently overwrite each other; proposed changes can be rejected and applied edits undone.
- At least three side chats can coexist on desktop with independent histories and drafts; minimizing, restoring, and viewport resizing keep them usable.
- Focus view and normal view round-trip without losing reading position, pending work, or conversation state.
- A quiz generated from selected material opens in the right place, retains answers, links feedback to sources, and supports targeted revision.
- Pinned/edited items remain visible when other agent jobs finish; the result notice opens the correct saved artifact.
- Voice and typed requests target the same selected item/conversation; microphone input cannot leak into another side chat.
- Keyboard-only and touch flows work. Focus is visible and predictable; icons have accessible labels; overlays do not trap the user unnecessarily.
- Loading, offline, retry, cancellation, missing-source, stale-revision, and permission failures are handled explicitly.
- Run relevant existing tests and add focused tests for state isolation, persistence, source targeting, and action routing. Visually verify realistic populated content at desktop and mobile widths, including long notes, equations, and PDFs.

Known local environment issue at handoff: the preview at `http://127.0.0.1:3001/` has shown “Temporarily offline” despite a separately healthy local API. Diagnose the current state and restore browser-to-API connectivity before claiming end-to-end saving or generation is verified. Fixtures can aid visual work but cannot establish backend success.

## Delivery

Implement the features in the existing architecture. Provide a concise change summary, tests and real workflows verified, screenshots of the finished populated workspace, and any remaining setup blockers. Document schema/configuration changes and migration steps. Do not deploy or alter paid service plans solely on the authority of this brief; follow the user's deployment instructions for the actual execution session.
