import { describe, expect, it } from 'vitest';
import {
  formatCheckpointAnswer,
  isValidNumericAnswer,
  orderSelectedValues,
  toggleCheckpointSelection,
} from './checkpointAnswer';

describe('formatCheckpointAnswer', () => {
  it('returns a lone selection as the bare value', () => {
    expect(formatCheckpointAnswer({ selectedValues: ['a'], otherText: '', labeled: true })).toBe('a');
  });

  it('labels several selections on one line', () => {
    expect(formatCheckpointAnswer({ selectedValues: ['a', 'b'], otherText: '', labeled: true })).toBe('Selected: a; b');
  });

  it('labels Other text on its own', () => {
    expect(formatCheckpointAnswer({ selectedValues: [], otherText: 'note', labeled: true })).toBe('Other: note');
  });

  it('puts a selection and Other text on separate lines', () => {
    expect(formatCheckpointAnswer({ selectedValues: ['a'], otherText: 'note', labeled: true })).toBe('Selected: a\nOther: note');
  });

  it('trims whitespace and drops blank values', () => {
    expect(formatCheckpointAnswer({ selectedValues: [' a ', '  '], otherText: '   ', labeled: true })).toBe('a');
  });

  it('returns an empty string when nothing was given', () => {
    expect(formatCheckpointAnswer({ selectedValues: [], otherText: '', labeled: true })).toBe('');
  });

  it('returns unlabeled answers verbatim', () => {
    expect(formatCheckpointAnswer({ selectedValues: ['target-choice:1'], otherText: '', labeled: false })).toBe('target-choice:1');
    expect(formatCheckpointAnswer({ selectedValues: [], otherText: ' free text ', labeled: false })).toBe('free text');
  });
});

describe('toggleCheckpointSelection', () => {
  it('replaces the selection for single-select prompts', () => {
    expect(toggleCheckpointSelection(['a'], 'b', false)).toEqual(['b']);
    expect(toggleCheckpointSelection(['a'], 'a', false)).toEqual(['a']);
  });

  it('adds and removes values for multi-select prompts', () => {
    expect(toggleCheckpointSelection(['a'], 'b', true)).toEqual(['a', 'b']);
    expect(toggleCheckpointSelection(['a', 'b'], 'a', true)).toEqual(['b']);
  });
});

describe('orderSelectedValues', () => {
  it('orders selections by option order and keeps unknown values last', () => {
    const options = [
      { id: '1', label: 'One', value: 'one' },
      { id: '2', label: 'Two', value: 'two' },
      { id: '3', label: 'Three', value: 'three' },
    ];
    expect(orderSelectedValues(options, ['three', 'stray', 'one'])).toEqual(['one', 'three', 'stray']);
  });
});

describe('isValidNumericAnswer', () => {
  it.each(['12', '-3.5', '.5', '1,250', ' 7 ', '+4', '2.'])('accepts %s', value => {
    expect(isValidNumericAnswer(value)).toBe(true);
  });

  it.each(['', 'abc', '1.2.3', '--1', '1e5', 'about 10'])('rejects %s', value => {
    expect(isValidNumericAnswer(value)).toBe(false);
  });
});
