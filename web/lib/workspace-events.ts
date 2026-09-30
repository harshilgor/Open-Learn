export type WorkspaceNoteSeed = {
  id: string;
  title: string;
  body: string;
  frontmatter: Record<string, unknown>;
};

export const WORKSPACE_NOTE_SEED_EVENT = 'forma:workspace-note-seed';
export const WORKSPACE_NOTE_OPEN_EVENT = 'forma:workspace-note-open';
export const WORKSPACE_NOTE_MENTION_EVENT = 'forma:workspace-note-mention';
export const WORKSPACE_NOTE_REPLACE_DRAFT_EVENT = 'forma:workspace-note-replace-draft';
export const WORKSPACE_SOURCE_OPEN_EVENT = 'forma:workspace-source-open';
export const WORKSPACE_QUIZ_OPEN_EVENT = 'forma:workspace-quiz-open';
export const WORKSPACE_QUIZ_REQUEST_EVENT = 'forma:workspace-quiz-request';
export const CHAT_SESSION_OPEN_EVENT = 'forma:chat-session-open';
export const WORKSPACE_PANEL_TOGGLE_EVENT = 'forma:workspace-panel-toggle';
export const WORKSPACE_PANEL_SET_COLLAPSED_EVENT = 'forma:workspace-panel-set-collapsed';

export type WorkspaceNoteMention = { noteId: string; title: string; revision: number; startOffset: number; endOffset: number; excerpt: string };
export type WorkspaceQuizOpen = {
  id: string;
  sessionId: string;
  conceptId?: string;
  requestedTopic?: string;
  lessonNoteId?: string;
  sourceTransitionId?: string;
  origin: 'ask' | 'learn';
  quizId?: string;
};

export function openWorkspaceQuiz(input: Omit<WorkspaceQuizOpen, 'id'>): void {
  window.dispatchEvent(new CustomEvent<WorkspaceQuizOpen>(WORKSPACE_QUIZ_OPEN_EVENT, {
    detail: { ...input, id: crypto.randomUUID() },
  }));
}

export function requestWorkspaceQuiz(): void {
  window.dispatchEvent(new Event(WORKSPACE_QUIZ_REQUEST_EVENT));
}

export function toggleWorkspacePanel(): void {
  window.dispatchEvent(new CustomEvent(WORKSPACE_PANEL_TOGGLE_EVENT));
}

export function setWorkspacePanelCollapsed(collapsed: boolean): void {
  window.dispatchEvent(new CustomEvent<boolean>(WORKSPACE_PANEL_SET_COLLAPSED_EVENT, { detail: collapsed }));
}

/**
 * An explicit, local UI boundary between a lesson and the learner-owned vault.
 * The note panel decides whether an unsaved editor can be replaced.
 */
export function openWorkspaceNoteDraft(input: Omit<WorkspaceNoteSeed, 'id'>): void {
  window.dispatchEvent(new CustomEvent<WorkspaceNoteSeed>(WORKSPACE_NOTE_SEED_EVENT, {
    detail: { ...input, id: crypto.randomUUID() },
  }));
}

/** Focus an existing note from a chat-context receipt without copying it. */
export function openWorkspaceNote(noteId: string): void {
  window.dispatchEvent(new CustomEvent<string>(WORKSPACE_NOTE_OPEN_EVENT, { detail: noteId }));
}

/** Add an explicit selected note excerpt to the current chat context. */
export function mentionWorkspaceNoteExcerpt(input: WorkspaceNoteMention): void {
  window.dispatchEvent(new CustomEvent<WorkspaceNoteMention>(WORKSPACE_NOTE_MENTION_EVENT, { detail: input }));
}

/** Request a draft that can replace an explicitly selected, saved note section. */
export function createWorkspaceNoteReplacementDraft(input: { noteId: string; title: string; revision: number; startOffset: number; endOffset: number }): void {
  window.dispatchEvent(new CustomEvent(WORKSPACE_NOTE_REPLACE_DRAFT_EVENT, { detail: input }));
}

/** Focus a learner-owned material passage without altering the chat thread. */
export function openWorkspaceSource(input: { spanId: string; versionId?: string; title?: string }): void {
  window.dispatchEvent(new CustomEvent(WORKSPACE_SOURCE_OPEN_EVENT, { detail: input }));
}

/** Return from a study note to its linked chat session ("how I learned this"). */
export function openChatSession(sessionId: string): void {
  window.dispatchEvent(new CustomEvent<string>(CHAT_SESSION_OPEN_EVENT, { detail: sessionId }));
}

export const REVIEW_OPEN_EVENT = 'forma:review-open';
export const REVIEW_RETURN_EVENT = 'forma:review-return';
export const REVIEW_ASK_TUTOR_EVENT = 'forma:review-ask-tutor';

export type ReviewOpenDetail = { sessionId?: string; conceptId?: string };
export type ReviewAskTutorDetail = {
  prompt: string;
  context: Record<string, unknown>;
  returnReviewSessionId: string;
  chatSessionId?: string | null;
};

export function openReview(detail: ReviewOpenDetail = {}): void {
  window.dispatchEvent(new CustomEvent<ReviewOpenDetail>(REVIEW_OPEN_EVENT, { detail }));
}

export function returnToReview(sessionId: string): void {
  window.dispatchEvent(new CustomEvent<string>(REVIEW_RETURN_EVENT, { detail: sessionId }));
}
