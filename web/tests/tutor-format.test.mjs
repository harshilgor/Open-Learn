import assert from 'node:assert/strict';
import { test } from 'node:test';
import { checkExerciseAnswer, encodeConceptLinks, normalizeShortAnswer, parseConceptLink, parseExerciseJson, splitTutorContent } from '../lib/tutor-format.ts';

const numeric = { id: 'chain-1', type: 'numeric', prompt: 'What is 2 × 3?', answer: '6', explanation: 'Multiply two by three.', hint: 'Use multiplication.' };

test('concept links accept valid terms with and without a short definition', () => {
  assert.deepEqual(parseConceptLink('[[Chain rule|Derivatives of compositions multiply]]'), { term: 'Chain rule', definition: 'Derivatives of compositions multiply' });
  assert.deepEqual(parseConceptLink('[[Chain rule]]'), { term: 'Chain rule' });
  assert.equal(parseConceptLink('[[|empty]]'), null);
  assert.equal(parseConceptLink('[[Term|]]'), null);
  assert.equal(parseConceptLink('[[broken]'), null);
  assert.equal(parseConceptLink(`[[Term|${'word '.repeat(16).trim()}]]`), null);
});

test('exercise JSON distinguishes a valid item, a partial stream, and invalid data', () => {
  const parsed = parseExerciseJson(JSON.stringify(numeric));
  assert.equal(parsed.status, 'valid');
  assert.equal(parseExerciseJson('{"id":"chain-1"', false).status, 'partial');
  assert.equal(parseExerciseJson('{"id":"chain-1"').status, 'invalid');
  assert.equal(parseExerciseJson(JSON.stringify({ ...numeric, answer: 'NaN' })).status, 'invalid');
  assert.equal(parseExerciseJson(JSON.stringify({ ...numeric, id: 'bad id' })).status, 'invalid');
});

test('numeric and short text answer checks handle edge cases', () => {
  assert.equal(checkExerciseAnswer(numeric, '6.000000001'), true);
  assert.equal(checkExerciseAnswer(numeric, ''), false);
  assert.equal(checkExerciseAnswer(numeric, 'Infinity'), false);
  assert.equal(checkExerciseAnswer({ ...numeric, answer: '0', tolerance: 0 }, '-0'), true);
  assert.equal(checkExerciseAnswer({ ...numeric, type: 'short_text', answer: 'Chain Rule!' }, '  chain,   rule  '), true);
  assert.equal(normalizeShortAnswer('  THE—CHAIN rule. '), 'the chain rule');
});

test('sample tutor response preserves headings, concept links, and one exercise card', () => {
  const response = '## Derivatives\n\n[[Chain rule|Derivatives of compositions multiply]] links the layers.\n\n```exercise\n' + JSON.stringify(numeric) + '\n```';
  const parts = splitTutorContent(response);
  assert.deepEqual(parts.map(part => part.kind), ['markdown', 'exercise']);
  assert.match(encodeConceptLinks(parts[0].body), /^## Derivatives/m);
  assert.match(encodeConceptLinks(parts[0].body), /\[Chain rule\]\(concept:Chain%20rule\?definition=/);
  assert.equal(parts[1].exercise.id, 'chain-1');
  assert.equal(splitTutorContent('```exercise\n{"id":')[0].kind, 'pending_exercise');
  assert.equal(splitTutorContent('```exercise\n{"id":"invalid"}\n```')[0].kind, 'invalid_exercise');
  assert.equal(encodeConceptLinks('`[[Code]]`'), '`[[Code]]`');
});
