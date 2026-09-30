/**
 * Browser client for the learning-kernel API.
 *
 * The UI preview currently reads the authored samples in learning-content.ts.
 * These contracts are the seam for replacing those samples with versioned,
 * source-aware graph and lesson responses once the API service is connected.
 * Keep this module free of React and provider-specific code so it can also be
 * used by server actions or a future streaming adapter.
 */

export type Gear = 'Quick' | 'Guided' | 'Deep';
export type ClassRecording = { id: string; noteId: string; title: string; mediaType: string; byteCount: number; durationMs: number; markersMs: number[]; status: 'queued' | 'processing' | 'completed' | 'failed'; error?: string | null; createdAt: number; updatedAt: number };
export type LectureStatus = { id: string; noteId: string; title: string; courseId: string | null; recordingStatus: string; captureComplete: boolean; captureInterrupted: boolean; durationMs: number; markersMs: number[]; chunks: { expected: number | null; serverConfirmed: number; transcribed: number; failed: number; missing: number[] }; stages: { transcription: string; semanticAnalysis: string; noteGeneration: string; verification: string }; preferences: Record<string, unknown>; generationVersion: number; pipelineVersion: number; error: string | null; updatedAt: number };
export type LectureEvidence = { segmentId: string; startMs: number; endMs: number };
export type LectureNoteBlock = { id: string; sectionId: string; entityId: string; ordinal: number; blockType: string; title: string; content: string; evidence: LectureEvidence[]; sourceKind: string; verificationStatus: string };
export type LectureSection = { id: string; ordinal: number; title: string; sectionType: string; summary: string; startMs: number; endMs: number; evidence: LectureEvidence[]; confidence: number | null; analysisStatus: string };
export type LectureTranscriptSegment = { id: string; chunkId: string; startMs: number; endMs: number; speaker: string; rawText: string; normalizedText: string; confidence: number | null };

export type GraphRevision = {
  id: string;
  version: number;
  status: 'draft' | 'generating' | 'published' | 'superseded' | 'failed';
  createdAt: string;
  publishedAt?: string | null;
};

export type TopicScope = {
  originalRequest: string;
  normalizedTitle: string;
  interpretation: string;
  objective?: string | null;
  depth: 'introductory' | 'intermediate' | 'advanced' | 'survey';
  language?: string | null;
  boundaries: string[];
  revision: number;
};

export type SourceRecord = {
  id: string;
  title: string;
  url?: string | null;
  locator?: string | null;
  publisher?: string | null;
  status: 'supported' | 'partially_supported' | 'conflicting' | 'insufficient';
  retrievedAt?: string | null;
};

export type ConceptTrust = {
  status: 'supported' | 'partially_supported' | 'conflicting' | 'insufficient';
  confidence?: number | null;
  sourceIds: string[];
  claimIds?: string[];
  reviewedAt?: string | null;
};

export type LearnerOverlay = {
  state: 'unassessed' | 'explored' | 'developing' | 'demonstrated' | 'review_due';
  evidenceCount: number;
  stateVersion: number;
  probability?: number | null;
  uncertainty?: number | null;
};

export type GraphConcept = {
  id: string;
  title: string;
  definition: string;
  summary: string;
  scope?: string | null;
  objectiveIds: string[];
  sourceIds: string[];
  trust: ConceptTrust;
  learner?: LearnerOverlay | null;
  layout?: { x: number; y: number; clusterId?: string | null } | null;
};

export type GraphEdgeType =
  | 'requires'
  | 'recommended_before'
  | 'related'
  | 'part_of'
  | 'contrasts'
  | 'enables';

export type GraphEdge = {
  id: string;
  fromConceptId: string;
  toConceptId: string;
  type: GraphEdgeType;
  rationale: string;
  sourceIds: string[];
  status: 'supported' | 'proposed' | 'conflicting' | 'rejected';
  confidence?: number | null;
};

export type KnowledgeGraph = {
  id: string;
  title: string;
  description: string;
  scope: TopicScope;
  revision: GraphRevision;
  concepts: GraphConcept[];
  edges: GraphEdge[];
  sources: SourceRecord[];
  focusConceptId?: string | null;
};

export type ScopeProposal = {
  kind: 'proposal';
  scope: TopicScope;
  graphId?: string | null;
};

export type ClarificationRequired = {
  kind: 'clarification_required';
  question: string;
  options?: string[];
  reason: string;
};

export type TopicResolution = ScopeProposal | ClarificationRequired;

export type LessonBlockKind =
  | 'explanation'
  | 'example'
  | 'analogy'
  | 'visual'
  | 'check'
  | 'reflection'
  | 'source_note';

export type LessonBlock = {
  id: string;
  kind: LessonBlockKind;
  heading?: string | null;
  body: string;
  conceptIds: string[];
  sourceIds: string[];
  trust: ConceptTrust;
  order: number;
  visualizations?: unknown[];
  parts?: Array<{ kind: 'text' | 'visualization'; text?: string | null; visualizationId?: string | null }>;
};

export type LessonArtifact = {
  id: string;
  sessionId: string;
  conceptId: string;
  graphRevision: number;
  gear: Gear;
  blocks: LessonBlock[];
  nextAction?: 'continue' | 'check_understanding' | 'repair_prerequisite' | 'review' | null;
  status: 'pending' | 'approved' | 'qualified' | 'failed' | 'cancelled';
  verificationRunId?: string | null;
  generatedBy?: string;
};

export type ModeTransitionSuggestion = {
  id: string;
  sourceMode: 'ask' | 'learn' | 'quiz';
  targetMode: 'ask' | 'learn' | 'quiz';
  reason: string;
  confidence: number;
  title: string;
  description: string;
  actionLabel: string;
  dismissLabel: string;
  context: {
    sessionId?: string;
    conceptId?: string;
    conceptTitle?: string;
    courseId?: string;
    seedPrompt?: string;
    originSummary?: string;
    questionCount?: number;
    consecutiveMisses?: number;
    [key: string]: unknown;
  };
  createdAt: string;
  sourceTurnId?: string | null;
  modeRevision?: number | null;
  status?: 'pending' | 'accepted' | 'dismissed' | 'expired' | 'superseded';
};

export type ModeClassification = {
  intent: 'ask' | 'learn' | 'quiz' | 'none';
  confidence: number;
  reason: string;
  targetMode?: 'ask' | 'learn' | 'quiz' | null;
  suggestion?: ModeTransitionSuggestion | null;
  decision: 'stay' | 'suggest' | 'request_transition';
  classificationSource: 'rule' | 'model' | 'fallback';
  ruleId?: string | null;
  rationale: string;
};

export type ModeTransitionInteraction = {
  suggestionId: string;
  action: 'accept' | 'dismiss' | 'applied' | 'failed';
  targetMode: 'ask' | 'learn' | 'quiz';
  sessionId?: string;
  reason?: string;
};

export type LearningSession = {
  id: string;
  graphId: string;
  graphRevision: number;
  goal?: string | null;
  title?: string | null;
  courseId?: string | null;
  currentConceptId?: string | null;
  currentLessonId?: string | null;
  stateVersion: number;
  authorityRevision?: number;
  currentBranchId?: string | null;
  activeGenerationId?: string | null;
  activeQuizId?: string | null;
  activeReviewId?: string | null;
  activeJobId?: string | null;
};

export type SessionTurnSummary = {
  index: number;
  lessonId?: string | null;
  conceptId?: string | null;
  mode?: 'ask' | 'learn' | null;
};

export type SessionSnapshot = {
  session: LearningSession;
  revision: number;
  mode: 'ask' | 'learn';
  journeyStatus: string;
  journeyRevision: number;
  journeyPosition: number;
  currentConceptId?: string | null;
  currentLessonId?: string | null;
  currentBranchId?: string | null;
  activeGenerationId?: string | null;
  activeGenerationStatus?: string | null;
  activeQuizId?: string | null;
  activeReviewId?: string | null;
  activeJobId?: string | null;
  currentRecommendationSetId?: string | null;
  lastCommittedTurn?: SessionTurnSummary | null;
};

export type SessionPositionUpdate = {
  expectedRevision: number;
  currentConceptId?: string | null;
  currentLessonId?: string | null;
  currentBranchId?: string | null;
  activeGenerationId?: string | null;
  activeQuizId?: string | null;
  activeReviewId?: string | null;
  activeJobId?: string | null;
};

export type BranchAnchor = {
  blockId?: string | null;
  selectedText?: string | null;
  startOffset?: number | null;
  endOffset?: number | null;
};

export type Branch = {
  id: string;
  sessionId: string;
  learnerId?: string;
  parentBranchId?: string | null;
  parentId?: string | null;
  conceptId?: string | null;
  anchor: BranchAnchor;
  returnPosition?: { conceptId?: string | null; lessonId?: string | null; blockId?: string | null; offset?: number | null };
  lifecycle?: 'open' | 'closed';
  status?: 'open' | 'collapsed' | 'saved' | 'closed';
  localGear?: Gear | null;
  summary?: string | null;
  revision?: number;
  lessonId?: string | null;
  createdAt?: string;
  updatedAt?: string;
  closedAt?: string | null;
};

export type BranchContext = {
  branch: Branch;
  ancestors: Branch[];
  children: Branch[];
  notes: NoteRecord[];
};

export type TeachingIntent =
  | 'teach'
  | 'simplify'
  | 'example'
  | 'why'
  | 'visualize'
  | 'check_understanding'
  | 'resume';

export type TeachingActionInput = {
  intent: TeachingIntent;
  conceptId?: string;
  gear: Gear;
  message?: string | null;
  parentLessonId?: string | null;
  parentBlockId?: string | null;
  branchId?: string | null;
  anchor?: BranchAnchor | null;
  expectedStateVersion?: number | null;
  curriculumVersion?: number | null;
};

export type RunStatus = {
  runId: string;
  status: 'received' | 'authorized' | 'context_ready' | 'planned' | 'generated' | 'verified' | 'delivered' | 'qualified_response' | 'repairing' | 'failed' | 'cancelled';
  progress?: number | null;
  message?: string | null;
  lesson?: LessonArtifact | null;
};

export type AttemptInput = {
  sessionId: string;
  itemId: string;
  response: unknown;
  assistance?: 'none' | 'hint' | 'example' | 'answer_revealed';
  expectedStateVersion?: number | null;
};

export type AttemptStatus = {
  attemptId: string;
  status: 'received' | 'grading' | 'graded' | 'evidence_accepted' | 'state_committed' | 'review_required' | 'failed';
  result?: 'correct' | 'incorrect' | 'partial' | 'unscored' | null;
  stateVersion?: number | null;
  evidenceIds?: string[];
};

export type NoteInput = {
  sessionId?: string | null;
  conceptId?: string | null;
  body: string;
  branchId?: string | null;
};

export type NoteRecord = NoteInput & { id: string; version: number; updatedAt: string };

export class LearningApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = 'LearningApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type ErrorResponse = { code?: string; message?: string; details?: unknown };

export function apiBaseUrl(): string {
  const configured = typeof process !== 'undefined' ? process.env.NEXT_PUBLIC_LEARNING_API_URL : undefined;
  const desktop = typeof window === 'undefined'
    ? undefined
    : (window as Window & { formaDesktop?: { apiBaseUrl?: string } }).formaDesktop?.apiBaseUrl;
  // The local backend is the default while the hosted API is being wired.
  // Deployments can set NEXT_PUBLIC_LEARNING_API_URL to their API origin.
  return (configured || desktop || 'http://127.0.0.1:8000').replace(/\/$/, '');
}

function desktopToken(): string | undefined {
  if (typeof window === 'undefined') return undefined;
  return (window as Window & { formaDesktop?: { apiToken?: string } }).formaDesktop?.apiToken;
}

function url(path: string): string {
  return `${apiBaseUrl()}${path.startsWith('/') ? path : `/${path}`}`;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  const token = desktopToken();
  if (token) headers.set('X-Forma-Desktop-Token', token);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');

  let response: Response;
  try {
    response = await fetch(url(path), { ...init, headers });
  } catch (cause) {
    if (init.signal?.aborted) throw cause;
    throw new Error('Cannot connect to the tutor service. Your message is still here. Start the local app with start-local.ps1, then try again.');
  }
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    const envelope = body && typeof body === 'object' ? body as ErrorResponse & { detail?: unknown } : {};
    const rawDetail = envelope.detail;
    // FastAPI's default errors (e.g. unknown routes on a stale backend) carry
    // a plain-string detail; surface it instead of a generic status message.
    const error = typeof rawDetail === 'object' && rawDetail !== null ? rawDetail as ErrorResponse : envelope;
    const validationMessage = Array.isArray(rawDetail)
      ? rawDetail.map(item => {
        if (!item || typeof item !== 'object') return '';
        const issue = item as { loc?: unknown; msg?: unknown };
        const path = Array.isArray(issue.loc) ? issue.loc.filter(part => part !== 'body' && part !== 'query' && part !== 'path').join('.') : '';
        const message = typeof issue.msg === 'string' ? issue.msg : '';
        return [path, message].filter(Boolean).join(': ');
      }).filter(Boolean).join('; ')
      : '';
    const message = typeof rawDetail === 'string' && rawDetail
      ? rawDetail
      : error.message || (validationMessage ? `Request validation failed: ${validationMessage}` : `Learning API request failed (${response.status})`);
    throw new LearningApiError(response.status, error.code || 'request_failed', message, error.details);
  }
  return body as T;
}

/**
 * Map low-level API failures to human states. A 404/405 against a known
 * endpoint almost always means the running tutor service predates it, so say
 * so instead of leaking status codes. Mirrors the chat-history pattern.
 */
export type FriendlyServiceError = { message: string; detail: string };

export function friendlyServiceError(cause: unknown, service: string): FriendlyServiceError {
  const raw = cause instanceof Error ? cause.message : 'Unknown error.';
  if (cause instanceof LearningApiError && (cause.status === 404 || cause.status === 405)) {
    return {
      message: `${service} needs the latest tutor service.`,
      detail: 'Restart the local API with start-local.ps1, then return here.',
    };
  }
  if (raw.startsWith('Cannot connect to the tutor service')) {
    return {
      message: 'Could not reach the tutor service.',
      detail: 'Start the local app with start-local.ps1, then try again.',
    };
  }
  return { message: `${service} could not be loaded.`, detail: raw };
}

export type CreateTopicInput = {
  topic: string;
  objective?: string;
  depth?: TopicScope['depth'];
  language?: string;
  boundaries?: string[];
};

export type CreateGraphResult = {
  graphId: string;
  runId?: string | null;
  status: RunStatus['status'];
  scope?: TopicScope | null;
  clarification?: ClarificationRequired | null;
};

export type BaselineGraphConcept = {
  id: string;
  title: string;
  label: string;
  summary: string;
  objective: string;
  source_ids: string[];
  support_status: 'supported' | 'partial' | 'unverified';
};

export type BaselineGraph = {
  id: string;
  scope_id: string;
  title: string;
  description: string;
  publication_state: 'limited_unverified' | 'published' | 'draft';
  trust_summary: string;
  concepts: BaselineGraphConcept[];
  edges: Array<{ id: string; source: string; target: string; type: string; justification: string; support_status: string }>;
  sources: Array<{ id: string; title: string; url?: string | null; support_status: string }>;
  generated_by: string;
  created_at: string;
};

export type BaselineGraphResponse = {
  job: { id: string; scope_id: string; status: string; stage: string; progress: number; graph_id?: string | null; warnings: string[] };
  graph?: BaselineGraph | null;
};

export type ChatSessionSummary = {
  id: string;
  title: string;
  goal?: string | null;
  courseId?: string | null;
  updatedAt: string;
  turnCount: number;
};

export type ChatSessionList = {
  sessions: ChatSessionSummary[];
  total: number;
};

export type StudyNoteLink = {
  noteId: string;
  title: string;
  revision: number;
  tutorUpdates: 'ask' | 'auto' | 'never';
  sessionIds: string[];
  sections: Array<Record<string, unknown>>;
};

export type NoteProposalRecord = {
  id: string;
  sessionId: string;
  noteId: string;
  origin: 'turn' | 'quiz' | 'insight';
  status: 'proposed' | 'applied' | 'rejected';
  heading: string;
  body: string;
  sectionId?: string | null;
  conceptTitle?: string | null;
  source: Record<string, unknown>;
  revision: number;
};

export type ProviderSettingsStatus = {
  provider: string;
  openRouterConfigured: boolean;
  openAiConfigured: boolean;
  restartRequired: boolean;
};
export type ProviderConnectionStatus = { connected: boolean; provider: string; model: string };

export type UsageRange = '7d' | '30d' | 'all';

export type UsageTotals = {
  totalTokens: number;
  promptTokens: number;
  completionTokens: number;
  generations: number;
  exactGenerations: number;
  estimatedGenerations: number;
  providerCost: number;
  costIsExact: boolean;
};

export type UsageDay = { date: string; totalTokens: number; generations: number };
export type UsageModelEntry = { model: string; totalTokens: number; generations: number };
export type UsageProviderEntry = { provider: string; totalTokens: number; generations: number };

export type UsageSummary = {
  range: string;
  totals: UsageTotals;
  byDay: UsageDay[];
  byModel: UsageModelEntry[];
  byProvider: UsageProviderEntry[];
};

export type AnalyticsDimension = 'mode' | 'model' | 'provider' | 'course';

export type AnalyticsSeries = {
  key: string;
  totalTokens: number;
  generations: number;
  sharePct: number;
  points: number[];
  genPoints: number[];
};

export type AnalyticsDay = {
  date: string;
  totalTokens: number;
  generations: number;
  promptTokens: number;
  completionTokens: number;
  cost: number;
};

export type AnalyticsSessionModel = { model: string; totalTokens: number; generations: number };

export type AnalyticsSession = {
  sessionId: string;
  title: string;
  totalTokens: number;
  generations: number;
  providerCost: number;
  costIsExact: boolean;
  lastActive: string | null;
  byModel: AnalyticsSessionModel[];
};

export type UsageAnalytics = {
  range: string;
  dimension: string;
  totals: UsageTotals;
  days: AnalyticsDay[];
  series: AnalyticsSeries[];
  topSessions: AnalyticsSession[];
};

export type LocalDataExport = {
  format: 'forma-local-export';
  version: number;
  learner_id: string;
  tables: Record<string, Array<Record<string, unknown>>>;
};

/** A learner-owned Markdown document in the local workspace vault. */
export type WorkspaceNoteSummary = {
  id: string;
  title: string;
  preview: string;
  noteType: 'manual' | 'lesson' | 'recording';
  frontmatter: Record<string, unknown>;
  revision: number;
  relativePath: string;
  updatedAt: string;
};

export type WorkspaceNote = Omit<WorkspaceNoteSummary, 'preview' | 'noteType'> & {
  learnerId: string;
  body: string;
  createdAt: string;
};

export type WorkspaceNoteInput = {
  title: string;
  body?: string;
  frontmatter?: Record<string, unknown>;
};

export type WorkspaceNoteLinkTargetType = 'note' | 'concept' | 'lesson_block' | 'attempt' | 'source_passage';
export type WorkspaceNoteLink = {
  id: string;
  learnerId: string;
  sourceNoteId: string;
  targetType: WorkspaceNoteLinkTargetType;
  targetId: string;
  label?: string | null;
  sourceStatus: 'available' | 'broken';
  targetStatus: 'available' | 'broken';
  createdAt: string;
};

export type NoteDraftAnchor = { kind: 'lesson_block' | 'quiz_attempt' | 'note_excerpt' | 'material_passage'; id: string; label: string };
export type NoteDraft = { id: string; sessionId: string; status: 'ready' | 'saved' | 'replaced' | 'discarded'; generatedLabel: 'ai_generated_draft'; title: string; body: string; proposedTags: string[]; proposedLinks: NoteDraftAnchor[]; sourceAnchors: NoteDraftAnchor[]; originKind: string; originReference: string; replacement?: { noteId: string; expectedRevision: number; startOffset: number; endOffset: number } | null; provider: string; createdAt: string };
export type CreateNoteDraftInput = { originKind: 'lesson' | 'selection' | 'quiz_feedback' | 'mentioned_notes'; lessonId?: string; blockId?: string; selectedText?: string; quizAttemptId?: string; noteContext?: { notes: { noteId: string; expectedRevision?: number; startOffset?: number; endOffset?: number }[] }; replacement?: { noteId: string; expectedRevision: number; startOffset: number; endOffset: number } };
export const learningApi = {
  async createBaselineGraph(input: { topic: string; objective?: string; depth?: 'overview' | 'introductory' | 'deep' }, options?: { signal?: AbortSignal; idempotencyKey?: string }): Promise<BaselineGraphResponse> {
    const scope = await request<{ id: string }>('/v1/topic-scopes', {
      method: 'POST',
      signal: options?.signal,
      headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
      body: JSON.stringify(input),
    });
    return request<BaselineGraphResponse>(`/v1/topic-scopes/${encodeURIComponent(scope.id)}/graph-jobs`, {
      method: 'POST',
      signal: options?.signal,
      headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
    });
  },

  resolveTopic(input: CreateTopicInput, options?: { signal?: AbortSignal; idempotencyKey?: string }): Promise<TopicResolution> {
    return request<TopicResolution>('/v1/topics/resolve', {
      method: 'POST',
      signal: options?.signal,
      headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
      body: JSON.stringify(input),
    });
  },

  createGraph(input: CreateTopicInput & { scopeRevision?: number }, options?: { signal?: AbortSignal; idempotencyKey?: string }): Promise<CreateGraphResult> {
    return request<CreateGraphResult>('/v1/graphs', {
      method: 'POST',
      signal: options?.signal,
      headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
      body: JSON.stringify(input),
    });
  },

  getGraph(graphId: string, params: { revision?: number; focus?: string; depth?: number; signal?: AbortSignal } = {}): Promise<KnowledgeGraph> {
    const query = new URLSearchParams();
    if (params.revision !== undefined) query.set('revision', String(params.revision));
    if (params.focus) query.set('focus', params.focus);
    if (params.depth !== undefined) query.set('depth', String(params.depth));
    const suffix = query.size ? `?${query.toString()}` : '';
    return request<KnowledgeGraph>(`/v1/graphs/${encodeURIComponent(graphId)}${suffix}`, { signal: params.signal });
  },

  createSession(input: { graphId?: string; topic?: string; gear?: Gear; graphRevision?: number; goal?: string; courseId?: string | null }): Promise<LearningSession> {
    return request<LearningSession>('/v1/sessions', {
      method: 'POST',
      body: JSON.stringify({
        ...input,
        course_id: input.courseId ?? undefined,
      }),
    });
  },

  getSession(sessionId: string): Promise<LearningSession> {
    return request<LearningSession>(`/v1/sessions/${encodeURIComponent(sessionId)}`);
  },

  getSessionSnapshot(sessionId: string): Promise<SessionSnapshot> {
    return request<SessionSnapshot>(`/v1/sessions/${encodeURIComponent(sessionId)}/snapshot`);
  },

  updateSessionPosition(sessionId: string, input: SessionPositionUpdate): Promise<SessionSnapshot> {
    return request<SessionSnapshot>(`/v1/sessions/${encodeURIComponent(sessionId)}/position`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },

  listChatSessions(params: { limit?: number; offset?: number } = {}): Promise<ChatSessionList> {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set('limit', String(params.limit));
    if (params.offset !== undefined) query.set('offset', String(params.offset));
    const suffix = query.size ? `?${query.toString()}` : '';
    return request<ChatSessionList>(`/v1/sessions${suffix}`);
  },

  renameChatSession(sessionId: string, title: string): Promise<LearningSession> {
    return request<LearningSession>(`/v1/sessions/${encodeURIComponent(sessionId)}`, { method: 'PATCH', body: JSON.stringify({ title }) });
  },

  regenerateChatTitle(sessionId: string, automatic = false): Promise<LearningSession> {
    return request<LearningSession>(`/v1/sessions/${encodeURIComponent(sessionId)}/regenerate-title${automatic ? '?automatic=true' : ''}`, { method: 'POST' });
  },

  deleteChatSession(sessionId: string): Promise<void> {
    return request<void>(`/v1/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
  },

  classifyMode(sessionId: string, message: string, currentMode: 'ask' | 'learn', bypassSuggestionId?: string): Promise<ModeClassification> {
    return request<ModeClassification>(`/v1/sessions/${encodeURIComponent(sessionId)}/mode-classification`, {
      method: 'POST', body: JSON.stringify({ message, currentMode, bypassSuggestionId }),
    });
  },

  getPendingModeTransition(sessionId: string): Promise<{ pending: { suggestion: ModeTransitionSuggestion; decision: 'suggest' | 'request_transition'; status: 'pending' | 'accepted'; startupStatus?: string; originalRequest: string } | null }> {
    return request(`/v1/sessions/${encodeURIComponent(sessionId)}/mode-transition`);
  },

  recordTransitionInteraction(suggestionId: string, action: 'accept' | 'dismiss' | 'applied' | 'failed', targetMode: 'ask' | 'learn' | 'quiz', sessionId?: string, expectedModeRevision?: number): Promise<{ status: string; startupStatus?: string; replayed?: boolean; suggestion?: ModeTransitionSuggestion }> {
    return request<{ status: string; startupStatus?: string; replayed?: boolean; suggestion?: ModeTransitionSuggestion }>(`/v1/sessions/${encodeURIComponent(sessionId || 'default')}/transition-interaction`, {
      method: 'POST',
      body: JSON.stringify({
        suggestionId,
        action,
        targetMode,
        expectedModeRevision,
      }),
    });
  },

  getTransitionGap(sessionId: string, conceptId: string, conceptTitle: string, consecutiveMisses = 2): Promise<{ suggestion: ModeTransitionSuggestion | null }> {
    const params = new URLSearchParams({
      concept_id: conceptId,
      concept_title: conceptTitle,
      consecutive_misses: String(consecutiveMisses),
    });
    return request<{ suggestion: ModeTransitionSuggestion | null }>(`/v1/sessions/${encodeURIComponent(sessionId)}/transition-gap?${params.toString()}`);
  },

  getProviderSettings(): Promise<ProviderSettingsStatus> {
    return request<ProviderSettingsStatus>('/v1/provider-settings');
  },

  testProviderConnection(): Promise<ProviderConnectionStatus> {
    return request<ProviderConnectionStatus>('/v1/provider-settings/test', { method: 'POST' });
  },

  saveProviderKey(provider: 'openrouter' | 'openai', apiKey: string): Promise<ProviderSettingsStatus> {
    return request<ProviderSettingsStatus>('/v1/provider-settings', { method: 'PUT', body: JSON.stringify({ provider, apiKey }) });
  },

  deleteProviderKey(provider: 'openrouter' | 'openai'): Promise<ProviderSettingsStatus> {
    return request<ProviderSettingsStatus>(`/v1/provider-settings/${encodeURIComponent(provider)}`, { method: 'DELETE' });
  },

  async getStudyNote(sessionId: string): Promise<StudyNoteLink | null> {
    try {
      return await request<StudyNoteLink>(`/v1/sessions/${encodeURIComponent(sessionId)}/study-note`);
    } catch (cause) {
      if (cause instanceof LearningApiError && cause.status === 404) return null;
      throw cause;
    }
  },

  createStudyNote(sessionId: string): Promise<StudyNoteLink> {
    return request<StudyNoteLink>(`/v1/sessions/${encodeURIComponent(sessionId)}/study-note`, { method: 'POST' });
  },

  setStudyNoteMode(noteId: string, tutorUpdates: StudyNoteLink['tutorUpdates'], expectedRevision: number): Promise<{ noteId: string; revision: number; tutorUpdates: StudyNoteLink['tutorUpdates'] }> {
    return request(`/v1/study-notes/${encodeURIComponent(noteId)}/settings`, {
      method: 'PATCH', body: JSON.stringify({ tutorUpdates, expectedRevision }),
    });
  },

  saveStudyInsight(sessionId: string, input: { heading?: string; body: string }): Promise<{ noteId: string; revision: number; sectionId: string }> {
    return request(`/v1/sessions/${encodeURIComponent(sessionId)}/study-note/insights`, { method: 'POST', body: JSON.stringify(input) });
  },

  listNoteProposals(sessionId: string, status?: string): Promise<{ proposals: NoteProposalRecord[] }> {
    const suffix = status ? `?${new URLSearchParams({ status })}` : '';
    return request(`/v1/sessions/${encodeURIComponent(sessionId)}/note-proposals${suffix}`);
  },

  acceptNoteProposal(proposalId: string, input: { body?: string; heading?: string; expectedRevision?: number }): Promise<{ proposalId: string; status: string }> {
    return request(`/v1/note-proposals/${encodeURIComponent(proposalId)}/accept`, { method: 'POST', body: JSON.stringify(input) });
  },

  rejectNoteProposal(proposalId: string): Promise<{ proposalId: string; status: string }> {
    return request(`/v1/note-proposals/${encodeURIComponent(proposalId)}/reject`, { method: 'POST' });
  },

  getUsageSummary(range: UsageRange = 'all', sessionId?: string): Promise<UsageSummary> {
    const query = new URLSearchParams({ range });
    if (sessionId) query.set('sessionId', sessionId);
    return request<UsageSummary>(`/v1/usage/summary?${query.toString()}`);
  },

  getUsageAnalytics(range: '7d' | '30d' = '7d', dimension: AnalyticsDimension = 'mode', limit = 5): Promise<UsageAnalytics> {
    const query = new URLSearchParams({ range, dimension, limit: String(limit) });
    return request<UsageAnalytics>(`/v1/usage/analytics?${query.toString()}`);
  },

  explainLesson(lessonId: string, input: { blockId: string; selectedText: string; mode?: 'explain' | 'simpler' | 'example' | 'symbols' | 'why' }, options?: { signal?: AbortSignal }): Promise<{ blocks: Array<{ heading: string; body: string }> }> {
    return request(`/v1/lessons/${encodeURIComponent(lessonId)}/explanations`, { method: 'POST', signal: options?.signal, body: JSON.stringify(input) });
  },
  getLessonVisualization(lessonId: string, visualizationId: string): Promise<unknown> {
    return request(`/v1/lessons/${encodeURIComponent(lessonId)}/visualizations/${encodeURIComponent(visualizationId)}`);
  },
  changeLessonVisualization(lessonId: string, visualizationId: string, change: {
    operation: 'change_parameter' | 'annotate' | 'set_domain'; expectedRevision: number;
    parameterId?: string; value?: number; annotation?: unknown; xDomain?: [number, number];
  }): Promise<unknown> {
    return request(`/v1/lessons/${encodeURIComponent(lessonId)}/visualizations/${encodeURIComponent(visualizationId)}`, {
      method: 'PATCH', body: JSON.stringify(change),
    });
  },

  teachingAction(sessionId: string, input: TeachingActionInput, options?: { signal?: AbortSignal; idempotencyKey?: string }): Promise<RunStatus> {
    return request<RunStatus>(`/v1/sessions/${encodeURIComponent(sessionId)}/actions`, {
      method: 'POST',
      signal: options?.signal,
      headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
      body: JSON.stringify(input),
    });
  },

  getRun(runId: string, options?: { signal?: AbortSignal }): Promise<RunStatus> {
    return request<RunStatus>(`/v1/runs/${encodeURIComponent(runId)}`, { signal: options?.signal });
  },

  openBranch(input: { learnerId?: string; sessionId: string; parentBranchId?: string | null; conceptId?: string | null; anchor: BranchAnchor; returnPosition?: Branch['returnPosition']; localGear?: Gear | null; summary?: string | null }, options?: { idempotencyKey?: string }): Promise<Branch> {
    const learnerId = input.learnerId || 'local';
    return request<Branch>(`/v1/learners/${encodeURIComponent(learnerId)}/branches`, {
      method: 'POST',
      headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
      body: JSON.stringify({ sessionId: input.sessionId, parentBranchId: input.parentBranchId, anchor: { ...input.anchor, conceptId: input.conceptId }, returnPosition: input.returnPosition || { lessonId: null, blockId: input.anchor.blockId || null }, localGear: input.localGear, summary: input.summary }),
    });
  },

  listBranches(learnerId = 'local', sessionId?: string, includeClosed = false): Promise<Branch[]> {
    const params = new URLSearchParams({ includeClosed: String(includeClosed) });
    if (sessionId) params.set('sessionId', sessionId);
    return request<Branch[]>(`/v1/learners/${encodeURIComponent(learnerId)}/branches?${params}`);
  },

  getBranchContext(learnerId: string, branchId: string): Promise<BranchContext> {
    return request<BranchContext>(`/v1/learners/${encodeURIComponent(learnerId)}/branches/${encodeURIComponent(branchId)}/context`);
  },

  updateBranch(learnerId: string, branchId: string, input: { expectedRevision: number; returnPosition?: Branch['returnPosition']; localGear?: Gear | null; summary?: string | null }): Promise<Branch> {
    return request<Branch>(`/v1/learners/${encodeURIComponent(learnerId)}/branches/${encodeURIComponent(branchId)}`, { method: 'PATCH', body: JSON.stringify(input) });
  },

  closeBranch(learnerId: string, branchId: string, cancelled = false): Promise<Branch> {
    return request<Branch>(`/v1/learners/${encodeURIComponent(learnerId)}/branches/${encodeURIComponent(branchId)}/${cancelled ? 'cancel' : 'close'}`, { method: 'POST' });
  },

  submitAttempt(input: AttemptInput, options?: { idempotencyKey?: string }): Promise<AttemptStatus> {
    return request<AttemptStatus>('/v1/attempts', {
      method: 'POST',
      headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
      body: JSON.stringify(input),
    });
  },

  getAttempt(attemptId: string): Promise<AttemptStatus> {
    return request<AttemptStatus>(`/v1/attempts/${encodeURIComponent(attemptId)}`);
  },

  saveNote(input: NoteInput, options?: { idempotencyKey?: string }): Promise<NoteRecord> {
    return request<NoteRecord>('/v1/notes', {
      method: 'POST',
      headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
      body: JSON.stringify(input),
    });
  },

  updateNote(noteId: string, body: string, version: number): Promise<NoteRecord> {
    return request<NoteRecord>(`/v1/notes/${encodeURIComponent(noteId)}`, { method: 'PATCH', body: JSON.stringify({ body, version }) });
  },

  listWorkspaceNotes(learnerId = 'local'): Promise<WorkspaceNoteSummary[]> {
    return request<WorkspaceNoteSummary[]>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },

  searchWorkspaceNotes(query: string, learnerId = 'local'): Promise<{ notes: WorkspaceNoteSummary[] }> {
    return request<{ notes: WorkspaceNoteSummary[] }>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes/search?${new URLSearchParams({ query })}`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },

  getWorkspaceNote(noteId: string, learnerId = 'local'): Promise<WorkspaceNote> {
    return request<WorkspaceNote>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes/${encodeURIComponent(noteId)}`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },

  createWorkspaceNote(input: WorkspaceNoteInput, learnerId = 'local'): Promise<WorkspaceNote> {
    return request<WorkspaceNote>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes`, {
      method: 'POST',
      headers: { 'X-Dev-Learner-Id': learnerId },
      body: JSON.stringify(input),
    });
  },

  updateWorkspaceNote(noteId: string, input: WorkspaceNoteInput & { expectedRevision: number }, learnerId = 'local'): Promise<WorkspaceNote> {
    return request<WorkspaceNote>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes/${encodeURIComponent(noteId)}`, {
      method: 'PATCH',
      headers: { 'X-Dev-Learner-Id': learnerId },
      body: JSON.stringify(input),
    });
  },

  listWorkspaceNoteLinks(noteId: string, learnerId = 'local'): Promise<{ links: WorkspaceNoteLink[] }> {
    return request<{ links: WorkspaceNoteLink[] }>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes/${encodeURIComponent(noteId)}/links`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },

  listWorkspaceNoteBacklinks(noteId: string, learnerId = 'local'): Promise<{ links: WorkspaceNoteLink[] }> {
    return request<{ links: WorkspaceNoteLink[] }>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-note-links/backlinks/note/${encodeURIComponent(noteId)}`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },

  createWorkspaceNoteLink(noteId: string, input: { expectedRevision: number; targetType: WorkspaceNoteLinkTargetType; targetId: string; label?: string }, learnerId = 'local'): Promise<WorkspaceNoteLink> {
    return request<WorkspaceNoteLink>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes/${encodeURIComponent(noteId)}/links`, {
      method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId }, body: JSON.stringify(input),
    });
  },

  deleteWorkspaceNoteLink(noteId: string, linkId: string, expectedRevision: number, learnerId = 'local'): Promise<void> {
    return request<void>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes/${encodeURIComponent(noteId)}/links/${encodeURIComponent(linkId)}?${new URLSearchParams({ expectedRevision: String(expectedRevision) })}`, {
      method: 'DELETE', headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },

  getNoteDraft(draftId: string): Promise<NoteDraft> { return request<NoteDraft>(`/v1/note-drafts/${encodeURIComponent(draftId)}`); },
  saveNoteDraft(draftId: string): Promise<{ noteDraftId: string; noteId: string }> { return request(`/v1/note-drafts/${encodeURIComponent(draftId)}/save`, { method: 'POST' }); },
  replaceNoteDraft(draftId: string, input: { expectedNoteRevision: number; startOffset: number; endOffset: number }): Promise<{ noteDraftId: string; noteId: string }> { return request(`/v1/note-drafts/${encodeURIComponent(draftId)}/replace`, { method: 'POST', body: JSON.stringify(input) }); },
  discardNoteDraft(draftId: string): Promise<{ noteDraftId: string }> { return request(`/v1/note-drafts/${encodeURIComponent(draftId)}/discard`, { method: 'POST' }); },

  getRecommendations(sessionId: string, learnerId = 'local'): Promise<RecommendationSet> {
    return request<RecommendationSet>(`/v1/sessions/${encodeURIComponent(sessionId)}/recommendations`, { headers: { 'X-Dev-Learner-Id': learnerId } });
  },

  recordRecommendationInteraction(recommendationId: string, eventType: 'impression' | 'selection' | 'dismissal' | 'completion' | 'failure', learnerId = 'local', idempotencyKey = crypto.randomUUID(), evidenceId?: string): Promise<void> {
    return request<void>(`/v1/recommendations/${encodeURIComponent(recommendationId)}/interactions`, { method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId, 'Idempotency-Key': idempotencyKey }, body: JSON.stringify({ eventType, evidenceId }) });
  },
  exportLocalData(learnerId = 'local'): Promise<LocalDataExport> {
    return request<LocalDataExport>(`/v1/learners/${encodeURIComponent(learnerId)}/export`);
  },

  deleteLocalData(learnerId = 'local'): Promise<{ deleted: Record<string, number>; total: number }> {
    return request<{ deleted: Record<string, number>; total: number }>(`/v1/learners/${encodeURIComponent(learnerId)}/data`, { method: 'DELETE' });
  },
  getReviewDashboard(learnerId = 'local'): Promise<ReviewDashboard> {
    return request<ReviewDashboard>(`/v1/learners/${encodeURIComponent(learnerId)}/review`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },
  createReviewSession(input: { length?: 'quick' | 'standard' | 'deep'; conceptIds?: string[]; resumeSessionId?: string; optional?: boolean; sessionId?: string }, learnerId = 'local'): Promise<{ sessionId: string }> {
    return request<{ sessionId: string }>('/v1/review/sessions', {
      method: 'POST',
      headers: { 'X-Dev-Learner-Id': learnerId, 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    });
  },
  getReviewSession(sessionId: string, learnerId = 'local'): Promise<ReviewSession> {
    return request<ReviewSession>(`/v1/review/sessions/${encodeURIComponent(sessionId)}`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },
  submitReviewConfidence(sessionId: string, itemId: string, confidence: ReviewConfidence, expectedRevision: number, learnerId = 'local'): Promise<ReviewSession> {
    return request<ReviewSession>(`/v1/review/sessions/${encodeURIComponent(sessionId)}/items/${encodeURIComponent(itemId)}/confidence`, {
      method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId, 'Content-Type': 'application/json' },
      body: JSON.stringify({ confidence, expectedRevision }),
    });
  },
  skipReviewItem(sessionId: string, itemId: string, expectedRevision: number, learnerId = 'local'): Promise<ReviewSession> {
    return request<ReviewSession>(`/v1/review/sessions/${encodeURIComponent(sessionId)}/items/${encodeURIComponent(itemId)}/skip`, {
      method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId, 'Content-Type': 'application/json' },
      body: JSON.stringify({ expectedRevision }),
    });
  },
  remediateReviewItem(sessionId: string, itemId: string, expectedRevision: number, learnerId = 'local'): Promise<ReviewSession> {
    return request<ReviewSession>(`/v1/review/sessions/${encodeURIComponent(sessionId)}/items/${encodeURIComponent(itemId)}/remediate`, {
      method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId, 'Content-Type': 'application/json' },
      body: JSON.stringify({ expectedRevision }),
    });
  },
  completeReviewSession(sessionId: string, expectedRevision: number, learnerId = 'local'): Promise<ReviewSession> {
    return request<ReviewSession>(`/v1/review/sessions/${encodeURIComponent(sessionId)}/complete`, {
      method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId, 'Content-Type': 'application/json' },
      body: JSON.stringify({ expectedRevision }),
    });
  },
  askTutorFromReview(sessionId: string, itemId: string, learnerId = 'local'): Promise<ReviewAskTutorPayload> {
    return request<ReviewAskTutorPayload>(`/v1/review/sessions/${encodeURIComponent(sessionId)}/items/${encodeURIComponent(itemId)}/ask-tutor`, {
      method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },
  backfillReview(learnerId = 'local'): Promise<{ id: string }> {
    return request<{ id: string }>(`/v1/learners/${encodeURIComponent(learnerId)}/review/backfill`, {
      method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId, 'Idempotency-Key': crypto.randomUUID() },
    });
  },
  getConceptExplanation(conceptId: string, learnerId = 'local'): Promise<ConceptStateExplanation> {
    return request<ConceptStateExplanation>(`/v1/learners/${encodeURIComponent(learnerId)}/state/${encodeURIComponent(conceptId)}/explanation`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },
  getLearnerTimeline(params: { cursor?: string; limit?: number } = {}, learnerId = 'local'): Promise<TimelinePage> {
    const query = new URLSearchParams();
    if (params.cursor) query.set('cursor', params.cursor);
    if (params.limit !== undefined) query.set('limit', String(params.limit));
    const suffix = query.size ? `?${query.toString()}` : '';
    return request<TimelinePage>(`/v1/learners/${encodeURIComponent(learnerId)}/timeline${suffix}`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },
  createLocalBackup(): Promise<{ format: string; archiveBase64: string }> { return request('/v1/local-backup'); },
  preflightLocalBackup(archiveBase64: string): Promise<{ archiveVersion: number; recordCount: number; fileCount: number; existingRecordCount: number; requiresReplaceConfirmation: boolean }> {
    return request('/v1/local-backup/preflight', { method: 'POST', body: JSON.stringify({ archiveBase64 }) });
  },
  restoreLocalBackup(archiveBase64: string, confirmReplace: boolean): Promise<{ restored: number; files: number }> {
    return request('/v1/local-backup/restore', { method: 'POST', body: JSON.stringify({ archiveBase64, confirmReplace }) });
  },
  listCourses(params: { includeArchived?: boolean } = {}): Promise<CourseSummary[]> {
    const query = new URLSearchParams();
    if (params.includeArchived) query.set('include_archived', 'true');
    const suffix = query.size ? `?${query.toString()}` : '';
    return request<CourseSummary[]>(`/v1/courses${suffix}`);
  },
  createCourse(input: CourseCreateInput): Promise<CoursePublic> {
    return request<CoursePublic>('/v1/courses', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  getCourse(courseId: string): Promise<CoursePublic> {
    return request<CoursePublic>(`/v1/courses/${encodeURIComponent(courseId)}`);
  },
  updateCourse(courseId: string, input: CourseUpdateInput): Promise<CoursePublic> {
    return request<CoursePublic>(`/v1/courses/${encodeURIComponent(courseId)}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },
  deleteCourse(courseId: string): Promise<void> {
    return request<void>(`/v1/courses/${encodeURIComponent(courseId)}`, {
      method: 'DELETE',
    });
  },
  listCourseSessions(courseId: string, params: { limit?: number; offset?: number } = {}): Promise<{ sessions: ChatSessionSummary[]; total: number }> {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set('limit', String(params.limit));
    if (params.offset !== undefined) query.set('offset', String(params.offset));
    const suffix = query.size ? `?${query.toString()}` : '';
    return request<{ sessions: ChatSessionSummary[]; total: number }>(`/v1/courses/${encodeURIComponent(courseId)}/sessions${suffix}`);
  },

  refreshNoteTitles(learnerId = 'local'): Promise<{ updated: number; skipped: number }> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes/refresh-titles`, { method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId } });
  },

  uploadClassRecording(noteId: string, audio: Blob, durationMs: number, markersMs: number[], learnerId = 'local'): Promise<ClassRecording> {
    return request<ClassRecording>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes/${encodeURIComponent(noteId)}/class-recording`, {
      method: 'PUT',
      headers: { 'X-Dev-Learner-Id': learnerId, 'Content-Type': audio.type || 'audio/webm', 'X-Recording-Duration-Ms': String(durationMs), 'X-Recording-Markers-Ms': markersMs.join(',') },
      body: audio,
    });
  },

  getClassRecording(noteId: string, learnerId = 'local'): Promise<ClassRecording> {
    return request<ClassRecording>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes/${encodeURIComponent(noteId)}/class-recording`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },

  async getClassRecordingAudio(recordingId: string, learnerId = 'local'): Promise<Blob> {
    const headers = new Headers({ Accept: 'audio/*', 'X-Dev-Learner-Id': learnerId });
    const token = desktopToken();
    if (token) headers.set('X-Forma-Desktop-Token', token);
    const response = await fetch(url(`/v1/learners/${encodeURIComponent(learnerId)}/class-recordings/${encodeURIComponent(recordingId)}/audio`), { headers });
    if (!response.ok) throw new Error('Class recording audio is unavailable.');
    return response.blob();
  },

  retryClassRecording(noteId: string, learnerId = 'local'): Promise<ClassRecording> {
    return request<ClassRecording>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes/${encodeURIComponent(noteId)}/class-recording/retry`, {
      method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },

  createLectureRecording(input: { id: string; title: string; courseId?: string | null; startedAtMs: number; noteFolder?: string | null; preferences: Record<string, unknown> }, learnerId = 'local'): Promise<LectureStatus> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings`, { method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId }, body: JSON.stringify(input) });
  },

  listLectureRecordings(learnerId = 'local'): Promise<{ recordings: LectureStatus[] }> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings`, { headers: { 'X-Dev-Learner-Id': learnerId } });
  },

  getLectureRecording(id: string, learnerId = 'local'): Promise<LectureStatus> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings/${encodeURIComponent(id)}`, { headers: { 'X-Dev-Learner-Id': learnerId } });
  },

  uploadLectureChunk(id: string, chunk: { sequenceNumber: number; startMs: number; endMs: number; mimeType: string; sha256: string; blob: Blob }, learnerId = 'local'): Promise<{ recordingId: string; sequenceNumber: number; sha256: string; duplicate: boolean }> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings/${encodeURIComponent(id)}/chunks/${chunk.sequenceNumber}`, {
      method: 'PUT', headers: { 'X-Dev-Learner-Id': learnerId, 'Content-Type': chunk.mimeType, 'X-Chunk-Start-Ms': String(chunk.startMs), 'X-Chunk-End-Ms': String(chunk.endMs), 'X-Chunk-Sha256': chunk.sha256 }, body: chunk.blob,
    });
  },

  finalizeLectureRecording(id: string, input: { expectedChunkCount: number; durationMs: number; markersMs: number[]; captureInterrupted: boolean }, learnerId = 'local'): Promise<LectureStatus> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings/${encodeURIComponent(id)}/finalize`, { method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId }, body: JSON.stringify(input) });
  },

  getLectureChunks(id: string, learnerId = 'local'): Promise<{ chunks: { sequenceNumber: number; startMs: number; endMs: number; mediaType: string; transcriptionStatus: string; error: string | null }[] }> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings/${encodeURIComponent(id)}/chunks`, { headers: { 'X-Dev-Learner-Id': learnerId } });
  },

  getLectureTranscript(id: string, learnerId = 'local'): Promise<{ segments: LectureTranscriptSegment[] }> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings/${encodeURIComponent(id)}/transcript`, { headers: { 'X-Dev-Learner-Id': learnerId } });
  },

  getLectureSections(id: string, learnerId = 'local'): Promise<{ sections: LectureSection[] }> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings/${encodeURIComponent(id)}/sections`, { headers: { 'X-Dev-Learner-Id': learnerId } });
  },

  getLectureNotes(id: string, learnerId = 'local'): Promise<{ generationVersion: number; blocks: LectureNoteBlock[] }> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings/${encodeURIComponent(id)}/notes`, { headers: { 'X-Dev-Learner-Id': learnerId } });
  },

  retryLectureFailures(id: string, learnerId = 'local'): Promise<LectureStatus> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings/${encodeURIComponent(id)}/retry`, { method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId } });
  },

  regenerateLectureNotes(id: string, preferences: Record<string, unknown>, learnerId = 'local'): Promise<LectureStatus> {
    return request(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings/${encodeURIComponent(id)}/regenerate`, { method: 'POST', headers: { 'X-Dev-Learner-Id': learnerId }, body: JSON.stringify(preferences) });
  },

  async getLectureChunkAudio(id: string, sequence: number, learnerId = 'local'): Promise<Blob> {
    const headers = new Headers({ Accept: 'audio/*', 'X-Dev-Learner-Id': learnerId });
    const token = desktopToken();
    if (token) headers.set('X-Forma-Desktop-Token', token);
    const response = await fetch(url(`/v1/learners/${encodeURIComponent(learnerId)}/lecture-recordings/${encodeURIComponent(id)}/chunks/${sequence}/audio`), { headers });
    if (!response.ok) throw new Error('Lecture audio is unavailable.');
    return response.blob();
  },

  deleteWorkspaceNote(noteId: string, expectedRevision: number, learnerId = 'local'): Promise<void> {
    return request<void>(`/v1/learners/${encodeURIComponent(learnerId)}/workspace-notes/${encodeURIComponent(noteId)}?${new URLSearchParams({ expectedRevision: String(expectedRevision) })}`, {
      method: 'DELETE',
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },
  addCourseSession(courseId: string, sessionId: string): Promise<{ courseId: string; sessionId: string }> {
    return request(`/v1/courses/${encodeURIComponent(courseId)}/sessions/${encodeURIComponent(sessionId)}`, { method: 'PUT' });
  },
  removeCourseSession(courseId: string, sessionId: string): Promise<void> {
    return request(`/v1/courses/${encodeURIComponent(courseId)}/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
  },
  listCourseNotes(courseId: string): Promise<{ notes: WorkspaceNoteSummary[]; total: number }> {
    return request<{ notes: WorkspaceNoteSummary[]; total: number }>(`/v1/courses/${encodeURIComponent(courseId)}/notes`);
  },
  getCourseRoadmap(courseId: string): Promise<CourseRoadmapNode[]> {
    return request<CourseRoadmapNode[]>(`/v1/courses/${encodeURIComponent(courseId)}/roadmap`);
  },
  generateCourseRoadmap(courseId: string, input?: { prompt?: string; replaceExisting?: boolean }): Promise<CourseRoadmapNode[]> {
    return request<CourseRoadmapNode[]>(`/v1/courses/${encodeURIComponent(courseId)}/roadmap/generate`, {
      method: 'POST',
      body: JSON.stringify(input || {}),
    });
  },
  addRoadmapNode(courseId: string, input: { title: string; phase: string; conceptId?: string | null }): Promise<CourseRoadmapNode> {
    return request<CourseRoadmapNode>(`/v1/courses/${encodeURIComponent(courseId)}/roadmap/nodes`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  updateRoadmapNode(courseId: string, nodeId: string, input: Partial<Pick<CourseRoadmapNode, 'title' | 'phase' | 'conceptId' | 'status' | 'orderIndex'>> | 'planned' | 'in_progress' | 'completed' | 'needs_review'): Promise<CourseRoadmapNode> {
    const body = typeof input === 'string' ? { status: input } : input;
    return request<CourseRoadmapNode>(`/v1/courses/${encodeURIComponent(courseId)}/roadmap/${encodeURIComponent(nodeId)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },
  deleteRoadmapNode(courseId: string, nodeId: string): Promise<void> {
    return request<void>(`/v1/courses/${encodeURIComponent(courseId)}/roadmap/${encodeURIComponent(nodeId)}`, {
      method: 'DELETE',
    });
  },
  reorderRoadmapNodes(courseId: string, nodeIds: string[]): Promise<CourseRoadmapNode[]> {
    return request<CourseRoadmapNode[]>(`/v1/courses/${encodeURIComponent(courseId)}/roadmap/reorder`, {
      method: 'POST',
      body: JSON.stringify({ nodeIds }),
    });
  },
  evaluateCourseProgression(courseId: string): Promise<{
    courseId: string;
    nodesUpdated: number;
    completedCount: number;
    totalCount: number;
    dueReviewCount: number;
    roadmap: CourseRoadmapNode[];
  }> {
    return request(`/v1/courses/${encodeURIComponent(courseId)}/roadmap/evaluate`, {
      method: 'POST',
    });
  },
  listCourseMaterials(courseId: string): Promise<{ materials: CourseMaterial[]; total: number }> {
    return request<{ materials: CourseMaterial[]; total: number }>(`/v1/courses/${encodeURIComponent(courseId)}/materials`);
  },
  addCourseTextMaterial(courseId: string, input: { title: string; text: string; role?: 'reference' | 'textbook' | 'lecture_notes' }): Promise<CourseMaterial> {
    return request<CourseMaterial>(`/v1/courses/${encodeURIComponent(courseId)}/materials/text`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  async uploadCourseMaterial(courseId: string, file: File, role: 'reference' | 'textbook' | 'lecture_notes' = 'reference'): Promise<CourseMaterial> {
    if (file.size > 50 * 1024 * 1024) throw new Error('File exceeds 50 MB limit.');
    const lower = file.name.toLowerCase();
    const mediaType = lower.endsWith('.pdf')
      ? 'application/pdf'
      : lower.endsWith('.md')
      ? 'text/markdown'
      : lower.endsWith('.png')
      ? 'image/png'
      : lower.match(/\.jpe?g$/)
      ? 'image/jpeg'
      : lower.endsWith('.webp')
      ? 'image/webp'
      : lower.endsWith('.gif')
      ? 'image/gif'
      : 'text/plain';

    const item = await request<{ materialId: string; versionId: string; uploadPath: string }>(
      '/v1/materials',
      {
        method: 'POST',
        body: JSON.stringify({ title: file.name, mediaType, byteCount: file.size, role, courseId }),
      }
    );
    await fetch(`${apiBaseUrl()}${item.uploadPath}`, {
      method: 'PUT',
      headers: { 'Content-Type': mediaType },
      body: file,
    });
    return request<CourseMaterial>(`/v1/materials/${encodeURIComponent(item.materialId)}`);
  },
  detachCourseMaterial(courseId: string, materialId: string): Promise<void> {
    return request<void>(`/v1/courses/${encodeURIComponent(courseId)}/materials/${encodeURIComponent(materialId)}`, {
      method: 'DELETE',
    });
  },
  getMaterialBlocks(versionId: string): Promise<{ blocks: Array<{ id?: string; spanId?: string; title?: string; pageIndex: number; text: string }> }> {
    return request(`/v1/material-versions/${encodeURIComponent(versionId)}/blocks`);
  },
};

export type NextActionKind = 'learn' | 'ask' | 'quiz' | 'review';
export type PedagogicalAction = 'teach' | 'check' | 'repair';
export type NextActionRecommendation = {
  id: string;
  actionKind: NextActionKind;
  title: string;
  rationale: string;
  conceptId?: string | null;
  conceptTitle?: string | null;
  effortMinutes: number;
  context: Record<string, string>;
  score: number;
  pedagogicalAction?: PedagogicalAction | null;
  whyCode?: string | null;
  evidenceIds: string[];
  inputDigest?: string | null;
  isPrimary: boolean;
};
export type RecommendationSet = {
  id: string;
  sessionId: string;
  policyVersion: string;
  inputDigest?: string | null;
  status: 'current' | 'superseded' | 'cancelled';
  supersededBySetId?: string | null;
  fulfilledEvidenceId?: string | null;
  createdAt: string;
  recommendations: NextActionRecommendation[];
};

export type ReviewConfidence = 'guessing' | 'somewhat' | 'confident' | 'very';
export type ReviewDashboardConcept = {
  conceptId: string; title: string; reason: string; masteryEstimate: string;
  lastReviewedAt?: string | null; nextReviewAt?: string | null; sourceLessonId?: string | null; sourceLessonTitle?: string | null;
};
export type ReviewDashboard = {
  dueCount: number; weakCount: number; newCount: number; totalConcepts: number; estimatedMinutes: number;
  streakDays: number; preparing: boolean; unfinishedSessionId?: string | null;
  needsAttention: ReviewDashboardConcept[]; recentlyStrengthened: ReviewDashboardConcept[]; recentlyLearned: ReviewDashboardConcept[];
  empty: boolean; caughtUp: boolean;
};
export type ReviewItem = {
  id: string; conceptId: string; conceptTitle: string; questionType: string; prompt: string;
  options: { id: string; label: string }[]; status: string; dueReason?: string | null;
  sourceLessonId?: string | null; attempt?: Record<string, unknown> | null; remediation?: { heading: string; body: string; followUpPrompt?: string } | null;
};
export type ReviewSession = {
  id: string; status: string; length: string; revision: number; itemCount: number; currentIndex: number;
  estimatedMinutes: number; items: ReviewItem[]; summary?: {
    reviewed: number; strengthened: string[]; improving: string[]; needsPractice: string[]; message?: string;
  } | null; createdAt: string; updatedAt: string;
};
export type ReviewAskTutorPayload = {
  sessionId?: string | null; prompt: string; context: Record<string, unknown>; returnReviewSessionId: string;
};

export type ConceptStateExplanation = {
  state: {
    conceptId: string;
    status: string;
    version: number;
    tentativeConfidence?: number | null;
    uncertainty?: number | null;
  };
  admittedEvidence: {
    id: string;
    kind: string;
    outcome: string;
    condition: string;
    score?: number | null;
    createdAt?: string;
  }[];
  rationale: string;
  review?: {
    dueAt?: string | null;
    dueReason?: string | null;
    status?: string;
    intervalDays?: number | null;
  } | null;
};

export type TimelineEntry = {
  id: string;
  kind: string;
  occurredAt: string;
  conceptId?: string | null;
  summary: string;
  deepLink?: Record<string, string>;
};

export type TimelinePage = {
  entries: TimelineEntry[];
  nextCursor?: string | null;
};

export type CourseTeachingPreferences = {
  depth: 'introductory' | 'standard' | 'deep';
  pace: 'brisk' | 'steady' | 'thorough';
  mathLevel: 'minimal' | 'standard' | 'rigorous';
  visualEmphasis: boolean;
  codeExamples: boolean;
  firstPrinciples: boolean;
};

export type CourseReminderPreferences = {
  enabled: boolean;
  days: string[];
  time: string;
  targetMinutes: number;
};

export type CourseRoadmapNode = {
  id: string;
  courseId: string;
  phase: string;
  conceptId?: string | null;
  title: string;
  status: 'planned' | 'in_progress' | 'completed' | 'needs_review';
  orderIndex: number;
  createdAt: string;
};

export type CourseMaterial = {
  id: string;
  title: string;
  role: 'reference' | 'textbook' | 'lecture_notes' | 'sample_paper' | 'answer_key';
  courseId?: string | null;
  versionId: string;
  status: 'uploaded' | 'queued' | 'running' | 'ready' | 'partially_ready' | 'failed' | 'needs_attention';
  mediaType: string;
  byteCount: number;
  jobId?: string | null;
  issues?: { message: string }[];
};

export type CourseSummary = {
  id: string;
  name: string;
  goal: string;
  sessionCount: number;
  noteCount: number;
  materialCount: number;
  dueReviewCount: number;
  roadmapProgress: number;
  updatedAt: string;
  archivedAt?: string | null;
};

export type CoursePublic = {
  id: string;
  name: string;
  goal: string;
  teachingPreferences: CourseTeachingPreferences;
  reminderPreferences: CourseReminderPreferences;
  roadmap: CourseRoadmapNode[];
  summary: CourseSummary;
  createdAt: string;
  updatedAt: string;
  archivedAt?: string | null;
};

export type CourseCreateInput = {
  name: string;
  goal?: string;
  teachingPreferences?: Partial<CourseTeachingPreferences>;
  reminderPreferences?: Partial<CourseReminderPreferences>;
};

export type CourseUpdateInput = {
  name?: string;
  goal?: string;
  teachingPreferences?: Partial<CourseTeachingPreferences>;
  reminderPreferences?: Partial<CourseReminderPreferences>;
  archived?: boolean;
};

