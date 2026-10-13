/** UI copy for generation activity events that have an unambiguous meaning. */
export function generationActivityCopy(
  type: string,
  data: Record<string, unknown> = {},
  mode: 'ask' | 'learn' = 'ask',
): string | null {
  if (type === 'tool.started' && data.tool === 'search_web_evidence') {
    const query = typeof data.query === 'string' ? data.query.trim().slice(0, 100) : '';
    return query
      ? `Searching the web for “${query}”…`
      : 'Searching the web…';
  }
  if (type === 'generation.context_ready' && data.heartbeat !== true) return 'Putting your answer together…';
  if (type === 'lesson.block_started') return mode === 'learn' ? 'Writing your lesson…' : 'Writing your answer…';
  if (type === 'visualization.planning') return 'Planning a visual…';
  return null;
}

export function executionTaskCopy(task: { kind: string; status: string; phase: string }): string {
  if (task.status === 'waiting') return 'I need one detail before I continue.';
  if (task.status === 'queued') return task.kind === 'calendar_read' ? 'Getting your Calendar request ready…' : 'Getting your task ready…';
  if (task.status === 'paused') return 'Task paused.';
  if (task.status === 'running') {
    if (task.kind === 'lab_analysis' && task.phase === 'analyze') return 'Analyzing your data…';
    if (task.kind === 'research' && task.phase === 'research') return 'Researching your request…';
    if (task.kind === 'sandbox_lab' && task.phase === 'research') return 'Running your analysis in a sandbox…';
    if (task.kind === 'calendar_read' && task.phase === 'read_calendar') return 'Checking your connected Google Calendar…';
    return 'Working on your request…';
  }
  if (task.status === 'completed_partial') return 'Task finished with partial results.';
  if (task.status === 'completed') return 'Task complete.';
  if (task.status === 'cancelled') return 'Task stopped.';
  if (task.status === 'failed') return 'Task hit a problem.';
  return 'Working on your request…';
}

export function browserTaskCopy(task: {
  status: string;
  actionsUsed: number;
  browserControl?: { owner: 'agent' | 'requesting' | 'human' | 'returning' } | null;
}, latestEvent?: {type?:string;message?:string} | null): string {
  if (latestEvent?.message && ['browser.action','browser.observed','browser.recovering','task.intent','task.input_answered'].includes(latestEvent.type || '')) return latestEvent.message;
  if (task.browserControl?.owner === 'requesting') return 'Requesting control of your website…';
  if (task.browserControl?.owner === 'human') return 'The website is open for your input.';
  if (task.browserControl?.owner === 'returning') return 'Returning control to Buddy…';
  if (task.status === 'queued') return 'Opening your connected website…';
  if (task.status === 'running' && task.actionsUsed > 0) {
    return `Checking your connected website… ${task.actionsUsed} actions so far.`;
  }
  if (task.status === 'running') return 'Starting work on your connected website…';
  return 'Working on your website request…';
}
