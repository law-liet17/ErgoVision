// Tests for voice input (feature 5): speech text -> form fields. Never scores.
// Run with:  node tests/test_voice.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fillFor, parseTaskSpeech, wordsToNumbers } from '../web/voice.js';

const EXAMPLE = 'Twelve kg box, lifts it about twenty times a minute, grip is poor, holds it for more than a minute.';

// field shapes as the forms define them: {key, type, options: [[value, label]]}
const sel = (key, ...values) => ({ key, type: 'select', options: values.map(v => [v, v]) });
const LAB = [{ key: 'load_kg', type: 'number' }, sel('coupling', 'good', 'fair', 'poor', 'unacceptable'),
  { key: 'static_posture', type: 'bool' }, { key: 'repeated_actions', type: 'bool' }, { key: 'load_static_or_repeated', type: 'bool' }];
const NIOSH = [{ key: 'load_kg', type: 'number' }, { key: 'lifts_per_min', type: 'number' },
  sel('duration', '1h', '2h', '8h'), sel('coupling', 'good', 'fair', 'poor')];
const STRAIN = [{ key: 'efforts_per_min', type: 'number' }, { key: 'hours_per_day', type: 'number' }];

test('the example sentence from the brief', () => {
  const { facts } = parseTaskSpeech(EXAMPLE);
  assert.deepEqual(facts, { load_kg: 12, per_min: 20, coupling: 'poor', static_hold: true });
});

test('it fills the lab task details', () => {
  const fill = fillFor(parseTaskSpeech(EXAMPLE).facts, LAB);
  assert.deepEqual(fill, { load_kg: 12, coupling: 'poor', static_posture: true, repeated_actions: true, load_static_or_repeated: true });
});

test('it fills the NIOSH form, mapping hours onto its duration options', () => {
  const fill = fillFor(parseTaskSpeech('15 kilos, 3 lifts per minute, fair handles, for 6 hours a shift').facts, NIOSH);
  assert.deepEqual(fill, { load_kg: 15, lifts_per_min: 3, coupling: 'fair', duration: '8h' });
});

test('only fields the form has are filled', () => {
  const fill = fillFor(parseTaskSpeech(EXAMPLE).facts, STRAIN);
  assert.deepEqual(fill, { efforts_per_min: 20 });
});

test('number words', () => {
  assert.equal(wordsToNumbers('twenty five times'), '25 times');
  assert.equal(wordsToNumbers('two and a half kg'), '2.5 kg');
  assert.equal(wordsToNumbers('one hundred and twenty a minute'), '120 a minute');
  assert.equal(wordsToNumbers('seven point five kilos'), '7.5 kilos');
  assert.equal(wordsToNumbers('12kg'), '12 kg');
});

test('other ways of saying it', () => {
  const cases = [
    ['about 8 kilograms, every 30 seconds', { load_kg: 8, per_min: 2 }],
    ['ninety times an hour with a good grip', { per_min: 1.5, coupling: 'good' }],
    ['no handles, held over 2 minutes', { coupling: 'poor', static_hold: true }],
    ['the box has a bad grip and it is not held for long', { coupling: 'poor', static_hold: false }],
    ['works 4 hours per day at 10/min', { hours: 4, per_min: 10 }],
  ];
  for (const [text, want] of cases) assert.deepEqual(parseTaskSpeech(text).facts, want, text);
});

test('nothing recognisable fills nothing', () => {
  const { facts } = parseTaskSpeech('the worker looks tired today');
  assert.deepEqual(facts, {});
  assert.deepEqual(fillFor(facts, LAB), {});
});
