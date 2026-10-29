import { beforeEach, describe, expect, it } from 'vitest';
import {
  clearLiveGap,
  forgetLiveActivity,
  liveGapStart,
  markLiveFeedLost,
  noteLiveEvent,
  resetLiveActivityClockForTests,
} from './liveActivityClock';

describe('liveActivityClock', () => {
  beforeEach(() => resetLiveActivityClockForTests());

  it('opens a gap at the last event time for every task that had live events', () => {
    noteLiveEvent('a', 1000);
    noteLiveEvent('b', 2000);
    noteLiveEvent('a', 3000);

    markLiveFeedLost();

    expect(liveGapStart('a')).toBe(3000);
    expect(liveGapStart('b')).toBe(2000);
  });

  it('reports no gap for a task that never received a live event', () => {
    markLiveFeedLost();

    expect(liveGapStart('never-seen')).toBeUndefined();
  });

  it('keeps the original gap start when the feed is lost again before the first gap is healed', () => {
    noteLiveEvent('a', 1000);
    markLiveFeedLost();
    noteLiveEvent('a', 5000);
    markLiveFeedLost();

    expect(liveGapStart('a')).toBe(1000);
  });

  it('opens a fresh gap after the previous one was cleared', () => {
    noteLiveEvent('a', 1000);
    markLiveFeedLost();
    clearLiveGap('a');
    noteLiveEvent('a', 9000);
    markLiveFeedLost();

    expect(liveGapStart('a')).toBe(9000);
  });

  it('forgets a task entirely', () => {
    noteLiveEvent('a', 1000);
    markLiveFeedLost();

    forgetLiveActivity('a');
    markLiveFeedLost();

    expect(liveGapStart('a')).toBeUndefined();
  });
});
