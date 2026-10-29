import { describe, expect, it } from 'vitest';
import {
  isRunRevealed,
  pruneExpandedTurns,
  revealRunInExpandedTurns,
  toggleExpandedTurn,
  trimExpandedTurnsForMode,
} from './expandedTurns';

describe('expandedTurns', () => {
  it('prunes ids that are not earlier turns of the displayed task and keeps the order', () => {
    expect(pruneExpandedTurns(['b', 'gone', 'a'], ['a', 'b', 'c'])).toEqual(['b', 'a']);
    expect(pruneExpandedTurns([], ['a'])).toEqual([]);
  });

  it('trims to the most recently opened turn in single mode and keeps all in multiple mode', () => {
    expect(trimExpandedTurnsForMode(['a', 'b', 'c'], 'single')).toEqual(['c']);
    expect(trimExpandedTurnsForMode(['a'], 'single')).toEqual(['a']);
    expect(trimExpandedTurnsForMode([], 'single')).toEqual([]);
    expect(trimExpandedTurnsForMode(['a', 'b'], 'multiple')).toEqual(['a', 'b']);
  });

  it('toggles by replacing in single mode and adding or removing in multiple mode', () => {
    expect(toggleExpandedTurn(['a'], 'single', 'b')).toEqual(['b']);
    expect(toggleExpandedTurn(['a'], 'single', 'a')).toEqual([]);
    expect(toggleExpandedTurn(['a'], 'multiple', 'b')).toEqual(['a', 'b']);
    expect(toggleExpandedTurn(['a', 'b'], 'multiple', 'a')).toEqual(['b']);
  });

  it('reveals a navigated prior run by replacing in single mode', () => {
    expect(isRunRevealed(['a'], 'single', 'b', true)).toBe(false);
    expect(isRunRevealed(['b'], 'single', 'b', true)).toBe(true);
    expect(revealRunInExpandedTurns(['a'], 'single', 'b', true)).toEqual(['b']);
  });

  it('collapses every earlier turn in single mode when navigating to the current run', () => {
    expect(isRunRevealed(['a'], 'single', 'current', false)).toBe(false);
    expect(isRunRevealed([], 'single', 'current', false)).toBe(true);
    expect(revealRunInExpandedTurns(['a'], 'single', 'current', false)).toEqual([]);
  });

  it('adds a navigated prior run without closing others in multiple mode', () => {
    expect(isRunRevealed(['a'], 'multiple', 'b', true)).toBe(false);
    expect(isRunRevealed(['a', 'b'], 'multiple', 'b', true)).toBe(true);
    expect(revealRunInExpandedTurns(['a'], 'multiple', 'b', true)).toEqual(['a', 'b']);
    expect(revealRunInExpandedTurns(['a', 'b'], 'multiple', 'b', true)).toEqual(['a', 'b']);
  });

  it('leaves the open turns alone in multiple mode when navigating to the current run', () => {
    expect(isRunRevealed(['a'], 'multiple', 'current', false)).toBe(true);
    expect(revealRunInExpandedTurns(['a'], 'multiple', 'current', false)).toEqual(['a']);
  });
});
