import { describe, expect, it } from 'vitest';
import { BOTTOM_TOLERANCE_PX, distanceFromBottom, hasContentBelowFold, isAtBottom, readingEarlierAfterScroll } from './liveScrollFollow';

describe('distanceFromBottom', () => {
  it('measures the content hidden below the visible area', () => {
    expect(distanceFromBottom({ scrollHeight: 1000, scrollTop: 300, clientHeight: 500 })).toBe(200);
    expect(distanceFromBottom({ scrollHeight: 500, scrollTop: 0, clientHeight: 500 })).toBe(0);
  });

  it('is not positive when everything fits', () => {
    expect(distanceFromBottom({ scrollHeight: 300, scrollTop: 0, clientHeight: 500 })).toBeLessThanOrEqual(0);
  });
});

describe('isAtBottom and hasContentBelowFold', () => {
  it('treats a few pixels short of the end as the end', () => {
    expect(isAtBottom({ scrollHeight: 1000, scrollTop: 500 - 10, clientHeight: 500 })).toBe(true);
    expect(isAtBottom({ scrollHeight: 1000, scrollTop: 500 - BOTTOM_TOLERANCE_PX, clientHeight: 500 })).toBe(false);
  });

  it('reports hidden content only when the end is really out of sight', () => {
    expect(hasContentBelowFold({ scrollHeight: 400, scrollTop: 0, clientHeight: 500 })).toBe(false);
    expect(hasContentBelowFold({ scrollHeight: 520, scrollTop: 0, clientHeight: 500 })).toBe(false);
    expect(hasContentBelowFold({ scrollHeight: 900, scrollTop: 0, clientHeight: 500 })).toBe(true);
  });
});

describe('readingEarlierAfterScroll', () => {
  it('starts reading earlier when the reader scrolls up away from the end', () => {
    expect(readingEarlierAfterScroll({ wasReadingEarlier: false, previousScrollTop: 400, scrollTop: 250, atBottom: false })).toBe(true);
  });

  it('does not start reading earlier when new content grew under a view that was following the end', () => {
    // The view jumped to the old end (scrollTop moved down from 400 to 600), then more content arrived before the event was handled, so it is no longer at the bottom.
    expect(readingEarlierAfterScroll({ wasReadingEarlier: false, previousScrollTop: 400, scrollTop: 600, atBottom: false })).toBe(false);
    // The same when the position did not move at all because the content grew.
    expect(readingEarlierAfterScroll({ wasReadingEarlier: false, previousScrollTop: 600, scrollTop: 600, atBottom: false })).toBe(false);
  });

  it('keeps reading earlier while the reader scrolls down without reaching the end', () => {
    expect(readingEarlierAfterScroll({ wasReadingEarlier: true, previousScrollTop: 200, scrollTop: 350, atBottom: false })).toBe(true);
  });

  it('stops reading earlier once the reader is back at the end', () => {
    expect(readingEarlierAfterScroll({ wasReadingEarlier: true, previousScrollTop: 350, scrollTop: 500, atBottom: true })).toBe(false);
    expect(readingEarlierAfterScroll({ wasReadingEarlier: false, previousScrollTop: 500, scrollTop: 500, atBottom: true })).toBe(false);
  });
});
