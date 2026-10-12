/** A latency shortcut may bypass advisory work, never explicit product actions. */
export function canUseTutorFastPath(text: string, mode: string, hasContext: boolean): boolean {
  if (mode !== 'ask' || hasContext) return false;
  // Conservative routing hint only. The normal server admission path retains
  // capability checks, permissions, source scope and idempotent acceptance.
  return !/https?:\/\/|\b(?:remind|reminders?|snooze|schedule|calendar|routine|flash\s*cards|quiz|record|recording|in[- ]class|browser|website|portal|canvas|lms|research|investigate|dataset|spreadsheet|csv|email|gmail|remember|forget|monitor|watch|notify|save|store|open|visit|browse|navigate|go to|cancel|stop|pause|resume|continue|start|create|make|generate|prepare|build|plan|send|add|update|delete|taking|coming up|upcoming|deadlines?|assignments?|exams?)\b/i.test(text);
}
