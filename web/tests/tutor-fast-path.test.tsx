import { expect, it } from 'vitest';
import { canUseTutorFastPath } from '../lib/tutor-fast-path';

it.each(['Explain inertia in two sentences.', 'Give a bus example of that idea.', 'How does slope work?'])
('retains the ordinary tutor shortcut for %s', message => {
  expect(canUseTutorFastPath(message, 'ask', false)).toBe(true);
});

it.each(['Open https://example.com in the browser.', 'Remind me in two minutes to review inertia.',
  'Create a quiz about inertia.', 'Remember that I prefer brief answers.', 'Start recording this class.',
  'Show my upcoming assignments.', 'Find evidence and research inertia.', 'Make flashcards.',
  'Schedule a review tomorrow.', 'Pause that task.'])
('preserves capability admission for %s', message => {
  expect(canUseTutorFastPath(message, 'ask', false)).toBe(false);
});

it.each(['quiz', 'learn', 'in-class'])('preserves selected mode %s', mode => {
  expect(canUseTutorFastPath('Inertia', mode, false)).toBe(false);
});

it('preserves attachments, selections and pending browser replies', () => {
  expect(canUseTutorFastPath('Explain this', 'ask', true)).toBe(false);
});
