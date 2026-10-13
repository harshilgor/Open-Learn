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
  metadata?: {
    representation?: string;
    answerWithheld?: boolean;
    visualSpec?: VisualSpec;
    [key: string]: unknown;
  };
};

export type VisualSpec = {
  kind: 'relationship_diagram' | 'comparison_table' | 'number_line' | 'worked_structure' | 'validated_plot';
  title: string;
  textEquivalent: string;
  nodes?: Array<{ id: string; label: string }>;
  edges?: Array<{ from: string; to: string; label: string }>;
};

export type ResolvedTeachingProfile = {
  gear: Gear;
  depth: 'essential' | 'scaffolded' | 'mechanistic';
  abstraction: 'accessible' | 'balanced' | 'technical';
  stepSize: 'large' | 'manageable' | 'fine';
  localOverride?: string | null;
  anchorScope: 'lesson' | 'block' | 'selection' | 'branch';
  visualSpecKind?: VisualSpec['kind'] | null;
  profileVersion: string;
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
  teachingPlanId?: string | null;
};

export type LearningSession = {
  id: string;
  graphId: string;
  graphRevision: number;
  goal?: string | null;
  currentConceptId?: string | null;
  currentLessonId?: string | null;
  stateVersion: number;
  gear: Gear;
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
  parentId?: string | null;
  conceptId: string;
  anchor: BranchAnchor;
  status: 'open' | 'collapsed' | 'saved';
  lessonId?: string | null;
};

export type TeachingIntent =
  | 'teach'
  | 'simplify'
  | 'example'
  | 'why'
  | 'visualize'
  | 'check_understanding'
  | 'resume'
  | 'deepen';

export type TeachingActionInput = {
  intent: TeachingIntent;
  conceptId: string;
  gear?: Gear | null;
  message?: string | null;
  parentLessonId?: string | null;
  parentBlockId?: string | null;
  anchor?: BranchAnchor | null;
  expectedStateVersion?: number | null;
  curriculumVersion?: number | null;
  supersedesActionId?: string | null;
};

export type RunStatus = {
  runId: string;
  status: 'received' | 'authorized' | 'context_ready' | 'planned' | 'generated' | 'verified' | 'delivered' | 'qualified_response' | 'repairing' | 'failed' | 'cancelled';
  progress?: number | null;
  message?: string | null;
  lesson?: LessonArtifact | null;
  teachingPlan?: { teachingProfile: ResolvedTeachingProfile; representationSequence: string[] } | null;
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

export type LearnerNote = {
  id: string;
  learnerId: string;
  scope: 'learner' | 'private';
  body: string;
  conceptId?: string | null;
  lessonId?: string | null;
  branchId?: string | null;
  documentId?: string | null;
  revision: number;
  provenance: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type AgentDocument = {
  id: string;
  learnerId: string;
  title: string;
  mimeType: 'text/plain' | 'text/markdown' | 'text/csv';
  characterCount: number;
  contentSha256: string;
  createdAt: string;
};

export type AgentTaskStep = {
  tool: 'read_owned_document' | 'extract_key_points' | 'create_learner_note';
  status: 'pending' | 'completed' | 'skipped' | 'failed';
  detail: string;
};

export type AgentTask = {
  id: string;
  learnerId: string;
  kind: 'summarize_to_note';
  goal: string;
  documentIds: string[];
  noteStyle: 'outline' | 'study';
  noteScope: 'learner' | 'private';
  status: 'queued' | 'planning' | 'running' | 'completed' | 'failed' | 'cancelled';
  steps: AgentTaskStep[];
  result?: { noteId?: string | null; documentIds: string[]; summary?: string | null; limitations: string[] } | null;
  errorCode?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type AgentTaskEvent = {
  id: string;
  taskId: string;
  sequence: number;
  type: string;
  data: Record<string, unknown>;
  createdAt: string;
};

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

function apiBaseUrl(): string {
  const configured = typeof process !== 'undefined' ? process.env.NEXT_PUBLIC_LEARNING_API_URL : undefined;
  // The local backend is the default while the hosted API is being wired.
  // Deployments can set NEXT_PUBLIC_LEARNING_API_URL to their API origin.
  return (configured || 'http://127.0.0.1:8000').replace(/\/$/, '');
}

function url(path: string): string {
  return `${apiBaseUrl()}${path.startsWith('/') ? path : `/${path}`}`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');

  const response = await fetch(url(path), { ...init, headers });
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
    const error = body && typeof body === 'object' ? (body as ErrorResponse) : {};
    throw new LearningApiError(response.status, error.code || 'request_failed', error.message || `Learning API request failed (${response.status})`, error.details);
  }
  return body as T;
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

  createSession(input: { graphId: string; graphRevision?: number; goal?: string; gear?: Gear }): Promise<LearningSession> {
    return request<LearningSession>('/v1/sessions', { method: 'POST', body: JSON.stringify(input) });
  },

  updateSessionGear(sessionId: string, input: { gear: Gear; expectedStateVersion?: number | null }): Promise<LearningSession> {
    return request<LearningSession>(`/v1/sessions/${encodeURIComponent(sessionId)}/gear`, { method: 'PATCH', body: JSON.stringify(input) });
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

  openBranch(input: { sessionId: string; parentId?: string | null; conceptId: string; anchor: BranchAnchor }, options?: { idempotencyKey?: string }): Promise<Branch> {
    return request<Branch>('/v1/branches', {
      method: 'POST',
      headers: options?.idempotencyKey ? { 'Idempotency-Key': options.idempotencyKey } : undefined,
      body: JSON.stringify(input),
    });
  },

  updateBranch(branchId: string, input: { status?: Branch['status']; anchor?: BranchAnchor }): Promise<Branch> {
    return request<Branch>(`/v1/branches/${encodeURIComponent(branchId)}`, { method: 'PATCH', body: JSON.stringify(input) });
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

  createAgentDocument(learnerId: string, input: { title: string; content: string; mimeType: AgentDocument['mimeType'] }): Promise<AgentDocument> {
    return request<AgentDocument>(`/v1/learners/${encodeURIComponent(learnerId)}/documents`, {
      method: 'POST',
      headers: { 'X-Dev-Learner-Id': learnerId },
      body: JSON.stringify(input),
    });
  },

  createAgentTask(learnerId: string, input: { goal: string; documentIds: string[]; noteStyle?: 'outline' | 'study'; noteScope?: 'learner' | 'private' }, idempotencyKey: string): Promise<AgentTask> {
    return request<AgentTask>(`/v1/learners/${encodeURIComponent(learnerId)}/agent-tasks`, {
      method: 'POST',
      headers: { 'X-Dev-Learner-Id': learnerId, 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(input),
    });
  },

  getAgentTask(learnerId: string, taskId: string): Promise<AgentTask> {
    return request<AgentTask>(`/v1/learners/${encodeURIComponent(learnerId)}/agent-tasks/${encodeURIComponent(taskId)}`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },

  getAgentTaskEvents(learnerId: string, taskId: string): Promise<AgentTaskEvent[]> {
    return request<AgentTaskEvent[]>(`/v1/learners/${encodeURIComponent(learnerId)}/agent-tasks/${encodeURIComponent(taskId)}/events`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },

  listLearnerNotes(learnerId: string): Promise<LearnerNote[]> {
    return request<LearnerNote[]>(`/v1/learners/${encodeURIComponent(learnerId)}/notes`, {
      headers: { 'X-Dev-Learner-Id': learnerId },
    });
  },
};
