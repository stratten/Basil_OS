import { describe, expect, it } from 'vitest';

import {
  AMBIENT_COMPACT_MAX_WIDTH,
  AMBIENT_COMPACT_MIN_WIDTH,
  resolveCollapsedPanelSize,
} from './collapsedPanelSizing';

describe('resolveCollapsedPanelSize', () => {
  it('keeps universal controls visible at the compact minimum', () => {
    expect(resolveCollapsedPanelSize(0, 44)).toEqual({
      width: AMBIENT_COMPACT_MIN_WIDTH,
      height: 64,
    });
  });

  it('uses the measured header width when it fits compact chrome', () => {
    expect(resolveCollapsedPanelSize(286, 52)).toEqual({
      width: 286,
      height: 64,
    });
  });

  it('caps long title content rather than growing indefinitely', () => {
    expect(resolveCollapsedPanelSize(900, 52).width).toBe(
      AMBIENT_COMPACT_MAX_WIDTH,
    );
  });
});
