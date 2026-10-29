import { describe, expect, it } from 'vitest';
import {
  hasVisibleActivity,
  nextActivityDisclosure,
  readableActivityCount,
  selectFallbackActivityTrail,
} from './activityDockPresentation';

const thinking = { id: 'thinking', type: 'thinking', timestamp: '', content: 'reasoning' } as const;
const raw = {
  id: 'raw',
  type: 'tool_complete',
  timestamp: '',
  content: 'raw output',
  metadata: { raw_detail: true },
} as const;
const progress = {
  id: 'progress',
  type: 'step',
  timestamp: '',
  content: 'Reading inbox',
  metadata: { progress_step: 'Reading inbox' },
} as const;

describe('activity dock presentation', () => {
  it('transitions disclosure without update-driven expansion', () => {
    expect(nextActivityDisclosure('collapsed', 'toggleTrail')).toBe('trail');
    expect(nextActivityDisclosure('trail', 'showFull')).toBe('full');
    expect(nextActivityDisclosure('full', 'showLess')).toBe('trail');
    expect(nextActivityDisclosure('trail', 'collapse')).toBe('collapsed');
    expect(nextActivityDisclosure('collapsed', 'showFull')).toBe('collapsed');
  });

  it('counts only readable activity and hides a thinking-only dock', () => {
    expect(readableActivityCount([thinking, raw, progress])).toBe(1);
    expect(hasVisibleActivity([thinking, raw], [])).toBe(false);
    expect(hasVisibleActivity([thinking, raw], [{ step: 'Working', isActive: true, isComplete: false }])).toBe(true);
  });

  it('limits fallback progress steps to the latest three', () => {
    const steps = ['One', 'Two', 'Three', 'Four'].map(step => ({
      step,
      isActive: false,
      isComplete: true,
    }));

    expect(selectFallbackActivityTrail(steps).map(step => step.step)).toEqual([
      'Two',
      'Three',
      'Four',
    ]);
  });
});
