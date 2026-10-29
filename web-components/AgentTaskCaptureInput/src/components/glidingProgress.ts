// A countdown ring is driven by values that arrive in steps: the end-of-speech countdown from the backend a few times a second, the recording timer ten times a second. Drawing each value as it arrives makes the ring tick. This model keeps the last value as an anchor, moves along the countdown's own rate between anchors, and glides out any gap when a new anchor disagrees with where the ring was drawn.

/** How quickly a gap between the drawn ring and a new anchor closes, as the time constant of an exponential. */
export const GLIDE_TIME_CONSTANT_MS = 220;
/** Past this long without a new anchor the ring stops extrapolating, so a stalled feed cannot drain the ring to empty on its own. It is well over the longest gap a healthy feed leaves between values, so a late value is corrected rather than stalled around. */
export const MAX_EXTRAPOLATION_MS = 600;
/** Anchors closer together than this give a noisy rate estimate, so the previous rate is kept. */
const MIN_RATE_SAMPLE_MS = 30;

export interface GlideState {
  value: number;
  at: number;
  ratePerSecond: number;
  offset: number;
  offsetAt: number;
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export function sampleGlide(state: GlideState, nowMs: number): number {
  const extrapolatedMs = Math.min(MAX_EXTRAPOLATION_MS, Math.max(0, nowMs - state.at));
  const along = clamp01(state.value + (state.ratePerSecond * extrapolatedMs) / 1000);
  const decay = Math.exp(-Math.max(0, nowMs - state.offsetAt) / GLIDE_TIME_CONSTANT_MS);
  return clamp01(along + state.offset * decay);
}

/**
 * Records a newly received value. `knownRatePerSecond` is the countdown's own rate when it is known in advance, such as the end-of-speech ring, which always empties over the same span. When it is null the rate is estimated from how fast successive values fall.
 */
export function anchorGlide(
  previous: GlideState | null,
  target: number,
  nowMs: number,
  knownRatePerSecond: number | null,
): GlideState {
  const clampedTarget = clamp01(target);
  if (!previous) {
    return { value: clampedTarget, at: nowMs, ratePerSecond: knownRatePerSecond ?? 0, offset: 0, offsetAt: nowMs };
  }
  const drawnNow = sampleGlide(previous, nowMs);
  let ratePerSecond = previous.ratePerSecond;
  if (knownRatePerSecond !== null) {
    ratePerSecond = knownRatePerSecond;
  } else if (nowMs - previous.at >= MIN_RATE_SAMPLE_MS && clampedTarget <= previous.value) {
    ratePerSecond = Math.max(-1, Math.min(0, ((clampedTarget - previous.value) / (nowMs - previous.at)) * 1000));
  }
  return {
    value: clampedTarget,
    at: nowMs,
    ratePerSecond,
    offset: drawnNow - clampedTarget,
    offsetAt: nowMs,
  };
}
