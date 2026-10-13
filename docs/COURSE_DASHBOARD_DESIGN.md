# Course dashboard and conversations

The course is the home for learning context and assets. Buddies are study partners, and a conversation keeps its assigned buddy. Changing the active buddy should not hide conversation history.

## Implemented first iteration

- Conversation history defaults to all buddies, ordered by most recent activity and grouped by date. Course and buddy names remain on each conversation. Search and a buddy filter support finding a specific chat. The existing session-opening handler restores its assigned buddy.
- Every course section retains its course heading, study partner control and navigation.
- Overview begins with a resume action for the most recently updated course conversation. Empty courses offer a first conversation.
- Overview links to materials, classes, notes and practice, and study planning. It previews actual course materials with processing status, plus course chats and notes.
- Materials opens the existing library expanded, including uploads, selection, extracted text and questions against materials.
- Exam and assignment forms, scheduling and Canvas connection move to Study plan, keeping forms off the overview.
- Existing-chat and existing-note pickers fetch their workspace lists only when opened.
- Course styling is isolated in a CSS module with wrapping controls, responsive cards and separate form labels/inputs.

## Next design decisions

1. Add a compact upcoming-deadlines summary to overview, based on academic entities and confirmed dates. Opening it should lead to the existing study planner.
2. Consider a unified course activity stream across chats, notes, materials and classes. The backend needs a paginated activity endpoint before this can reliably cover older items.
3. Add persistent pinned course assets and conversations, with explicit ordering and storage rather than browser-only state.
4. Show progress only when supported by existing learning evidence, with topic-level explanations of what needs practice.

## Validation

TypeScript and lint passed. Dashboard tests verify material preview, most-recent resume, deferred picker data and course heading persistence across sections. Conversation tests verify all-buddy visibility, ordering and explicit filtering; the existing buddy-navigation outage check passed.

Local browser preview was blocked by browser access policy (`ERR_BLOCKED_BY_CLIENT`). Responsive visual verification and production deployment remain outstanding for this iteration. Dictation source files were not modified.
