import { act } from 'react';

const SETTLE_FRAMES = 8;

/**
 * Test helper that stands in for the native host finishing an animated window
 * expand: the viewport changes size once and then stays put, which is the
 * signal `useSettledExpand` waits for before revealing collapsed content.
 */
export async function settleHostWindowResize(): Promise<void> {
  Object.defineProperty(window, 'innerHeight', {
    configurable: true,
    value: window.innerHeight + 40,
  });
  window.dispatchEvent(new Event('resize'));
  await act(async () => {
    for (let frame = 0; frame < SETTLE_FRAMES; frame += 1) {
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    }
  });
}
