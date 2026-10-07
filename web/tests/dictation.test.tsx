import { describe, expect, it } from 'vitest';
import { DictationTranscript, insertDictation } from '@/lib/dictation';

describe('dictation draft integrity', () => {
  it('inserts at the selection and preserves surrounding draft', () => {
    expect(insertDictation('Explain this please.', 'gravity', 8, 12)).toBe('Explain gravity please.');
    expect(insertDictation('Hello', 'world.', 5, 5)).toBe('Hello world.');
    expect(insertDictation('Draft', '', 0, 5)).toBe('Draft');
  });
  it('does not silently truncate overflow', () => {
    expect(insertDictation('a'.repeat(3999), 'long transcript', 3999, 3999)).toBeNull();
  });
  it('replaces interim text and deduplicates final/stale events', () => {
    const transcript = new DictationTranscript();
    const send = (sequence: number, type: string, text: string, segmentId = 'one') => transcript.receive({ sequence, type, text, segmentId });
    send(1, 'transcript.interim', 'Study');
    send(2, 'transcript.interim', 'Study physics');
    expect(transcript.interim).toBe('Study physics');
    send(3, 'transcript.final', 'Study physics.');
    send(4, 'transcript.final', 'Study physics.');
    send(2, 'transcript.interim', 'stale');
    expect(transcript.final).toBe('Study physics.');
    expect(transcript.interim).toBe('');
    send(5, 'transcript.final', 'Then chemistry.', 'two');
    expect(transcript.final).toBe('Study physics. Then chemistry.');
  });
});
