export function insertDictation(draft: string, transcript: string, start: number, end: number, limit = 4000): string | null {
  const text = transcript.trim();
  if (!text) return draft;
  const before = draft.slice(0, start), after = draft.slice(end);
  const next = before + (before && !/\s$/.test(before) ? ' ' : '') + text + (after && !/^\s|^[.,!?;:]/.test(after) ? ' ' : '') + after;
  return next.length <= limit ? next : null;
}

export class DictationTranscript {
  private segments = new Set<string>();
  private sequence = 0;
  final = '';
  interim = '';
  receive(event: { sequence: number; segmentId: string; text: string; type: string }) {
    if (!Number.isInteger(event.sequence) || event.sequence <= this.sequence || typeof event.text !== 'string') return;
    this.sequence = event.sequence;
    if (event.type === 'transcript.final') {
      if (!this.segments.has(event.segmentId)) {
        this.segments.add(event.segmentId);
        this.final = [this.final, event.text.trim()].filter(Boolean).join(' ');
      }
      this.interim = '';
    } else if (event.type === 'transcript.interim') this.interim = event.text;
  }
}
