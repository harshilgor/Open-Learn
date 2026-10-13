import { describe, expect, it } from 'vitest';
import { browserTaskCopy, executionTaskCopy, generationActivityCopy } from '@/lib/generation-activity';

describe('generation activity copy', () => {
  it('names web browsing only when the web evidence tool actually starts', () => {
    expect(generationActivityCopy('tool.started', { tool: 'search_web_evidence', query: 'photosynthesis' }))
      .toBe('Searching the web for “photosynthesis”…');
    expect(generationActivityCopy('tool.started', { tool: 'unknown_tool' })).toBeNull();
  });

  it('describes actual generation milestones with the selected learning mode', () => {
    expect(generationActivityCopy('generation.context_ready')).toBe('Putting your answer together…');
    expect(generationActivityCopy('generation.context_ready', { heartbeat: true })).toBeNull();
    expect(generationActivityCopy('lesson.block_started', {}, 'learn')).toBe('Writing your lesson…');
    expect(generationActivityCopy('lesson.block_started', {}, 'ask')).toBe('Writing your answer…');
    expect(generationActivityCopy('visualization.planning')).toBe('Planning a visual…');
    expect(generationActivityCopy('tool.started', { tool: 'browser_navigation' })).toBeNull();
  });

  it('uses task state and phase for agent and website work labels', () => {
    expect(executionTaskCopy({ kind: 'lab_analysis', status: 'running', phase: 'analyze' })).toBe('Analyzing your data…');
    expect(executionTaskCopy({ kind: 'sandbox_lab', status: 'running', phase: 'research' })).toBe('Running your analysis in a sandbox…');
    expect(executionTaskCopy({ kind: 'calendar_read', status: 'queued', phase: 'inspect' })).toBe('Getting your Calendar request ready…');
    expect(executionTaskCopy({ kind: 'calendar_read', status: 'running', phase: 'read_calendar' })).toBe('Checking your connected Google Calendar…');
    expect(executionTaskCopy({ kind: 'research', status: 'waiting', phase: 'clarify' })).toBe('I need one detail before I continue.');
    expect(browserTaskCopy({ status: 'running', actionsUsed: 2, browserControl: { owner: 'agent' } }))
      .toBe('Checking your connected website… 2 actions so far.');
    expect(browserTaskCopy({ status: 'running', actionsUsed: 0, browserControl: { owner: 'human' } }))
      .toBe('The website is open for your input.');
  });
});
