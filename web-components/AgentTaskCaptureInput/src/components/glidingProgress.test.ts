import { describe, expect, it } from 'vitest';
import {
  anchorGlide,
  GLIDE_TIME_CONSTANT_MS,
  MAX_EXTRAPOLATION_MS,
  sampleGlide,
  type GlideState,
} from './glidingProgress';

const SILENCE_RATE = -1 / 2;

function drawSilenceCountdown(valuesBySecond: Array<[number, number]>, frameMs = 16): number[] {
  let state: GlideState | null = null;
  const drawn: number[] = [];
  let next = 0;
  const end = valuesBySecond[valuesBySecond.length - 1][0] * 1000;
  for (let t = 0; t <= end; t += frameMs) {
    while (next < valuesBySecond.length && valuesBySecond[next][0] * 1000 <= t) {
      state = anchorGlide(state, valuesBySecond[next][1], valuesBySecond[next][0] * 1000, SILENCE_RATE);
      next += 1;
    }
    if (state) drawn.push(sampleGlide(state, t));
  }
  return drawn;
}

describe('the countdown ring between received values', () => {
  it('keeps moving on every frame through a feed that arrives in lumps about 320 ms apart', () => {
    const lumps: Array<[number, number]> = [];
    for (let step = 0; step <= 4; step += 1) lumps.push([step * 0.32, 0.75 - step * 0.16]);

    const drawn = drawSilenceCountdown(lumps);
    const steps = drawn.slice(1).map((value, index) => drawn[index] - value);

    expect(Math.max(...steps)).toBeLessThan(0.012);
    expect(Math.min(...steps)).toBeGreaterThanOrEqual(0);
    expect(steps.filter((step) => step < 0.002).length).toBe(0);
  });

  it('moves on every frame even when values arrive only four times a second', () => {
    const quarterSecondSteps: Array<[number, number]> = [];
    for (let step = 0; step <= 6; step += 1) quarterSecondSteps.push([step * 0.25, 0.75 - step * 0.125]);

    const drawn = drawSilenceCountdown(quarterSecondSteps);
    const steps = drawn.slice(1).map((value, index) => drawn[index] - value);

    expect(Math.max(...steps)).toBeLessThan(0.01);
    expect(steps.filter((step) => step === 0).length).toBeLessThan(2);
  });

  it('is monotonic when the received values agree with the countdown rate', () => {
    const steps: Array<[number, number]> = [];
    for (let step = 0; step <= 12; step += 1) steps.push([step * 0.1, 0.75 - step * 0.05]);

    const drawn = drawSilenceCountdown(steps);

    for (let index = 1; index < drawn.length; index += 1) {
      expect(drawn[index]).toBeLessThanOrEqual(drawn[index - 1] + 1e-9);
    }
  });

  it('glides back up instead of jumping when the countdown is canceled and restarted', () => {
    let state = anchorGlide(null, 0.2, 0, SILENCE_RATE);
    state = anchorGlide(state, 0.75, 100, SILENCE_RATE);

    const justAfter = sampleGlide(state, 100);
    const settled = sampleGlide(state, 100 + GLIDE_TIME_CONSTANT_MS * 8);

    expect(justAfter).toBeLessThan(0.3);
    expect(settled).toBeCloseTo(0.75 + SILENCE_RATE * (MAX_EXTRAPOLATION_MS / 1000), 1);
    expect(sampleGlide(state, 100 + GLIDE_TIME_CONSTANT_MS)).toBeGreaterThan(justAfter);
  });

  it('stops extrapolating when the feed stalls, so the ring does not empty on its own', () => {
    const state = anchorGlide(null, 0.75, 0, SILENCE_RATE);

    const stalled = sampleGlide(state, 10_000);

    expect(stalled).toBeCloseTo(0.75 + SILENCE_RATE * (MAX_EXTRAPOLATION_MS / 1000), 5);
    expect(stalled).toBeGreaterThan(0.4);
  });

  it('estimates the rate of a timer whose speed is not known in advance', () => {
    let state = anchorGlide(null, 1, 0, null);
    for (let step = 1; step <= 10; step += 1) state = anchorGlide(state, 1 - step * 0.01, step * 100, null);

    expect(state.ratePerSecond).toBeCloseTo(-0.1, 2);
  });

  it('keeps its rate when a timer restarts at full', () => {
    let state = anchorGlide(null, 1, 0, null);
    state = anchorGlide(state, 0.9, 1000, null);
    const rateBeforeRestart = state.ratePerSecond;

    state = anchorGlide(state, 1, 1100, null);

    expect(state.ratePerSecond).toBe(rateBeforeRestart);
  });

  it('never leaves the 0 to 1 range', () => {
    const state = anchorGlide(anchorGlide(null, 1.4, 0, SILENCE_RATE), -0.5, 10, SILENCE_RATE);

    for (let t = 0; t < 2000; t += 50) {
      const value = sampleGlide(state, t);
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(1);
    }
  });
});
