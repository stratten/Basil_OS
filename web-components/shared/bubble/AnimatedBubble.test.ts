import { describe, expect, it } from 'vitest';
import {
  BUBBLE_COLOR_TRANSITION_MS,
  retargetRgbTransition,
  rgbTransitionValue,
  type RgbColor,
  type RgbTransition,
} from './AnimatedBubble';

function expectRgbClose(actual: RgbColor, expected: RgbColor): void {
  expected.forEach((channel, index) => {
    expect(actual[index]).toBeCloseTo(channel, 6);
  });
}

describe('AnimatedBubble color transitions', () => {
  it('eases from the displayed color to a new target over the native 500 ms duration', () => {
    const red: RgbColor = [1, 0, 0];
    const green: RgbColor = [0, 1, 0];
    const initial: RgbTransition = { from: red, to: red, startedAt: 0 };
    const transition = retargetRgbTransition(initial, green, 100);

    expect(BUBBLE_COLOR_TRANSITION_MS).toBe(500);
    expectRgbClose(rgbTransitionValue(transition, 100), red);
    expectRgbClose(rgbTransitionValue(transition, 350), [0.5, 0.5, 0]);
    expectRgbClose(rgbTransitionValue(transition, 600), green);
  });

  it('retargets from the currently displayed color without snapping during an interrupted transition', () => {
    const red: RgbColor = [1, 0, 0];
    const green: RgbColor = [0, 1, 0];
    const blue: RgbColor = [0, 0, 1];
    const initial: RgbTransition = { from: red, to: red, startedAt: 0 };
    const towardGreen = retargetRgbTransition(initial, green, 100);
    const displayedAtInterruption = rgbTransitionValue(towardGreen, 350);
    const towardBlue = retargetRgbTransition(towardGreen, blue, 350);

    expectRgbClose(displayedAtInterruption, [0.5, 0.5, 0]);
    expectRgbClose(rgbTransitionValue(towardBlue, 350), displayedAtInterruption);
    expectRgbClose(rgbTransitionValue(towardBlue, 600), [0.25, 0.25, 0.5]);
    expectRgbClose(rgbTransitionValue(towardBlue, 850), blue);
  });
});
