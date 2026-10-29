import { useEffect, useRef, useState } from 'react';
import { anchorGlide, sampleGlide, type GlideState } from './glidingProgress';

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Returns `target` drawn smoothly: it moves every animation frame along the countdown's rate instead of stepping when a new value arrives. See glidingProgress.ts for the model.
 */
export function useGlidingProgress(target: number, knownRatePerSecond: number | null): number {
  const [drawn, setDrawn] = useState(target);
  const stateRef = useRef<GlideState | null>(null);
  const targetRef = useRef(target);
  targetRef.current = target;

  useEffect(() => {
    stateRef.current = anchorGlide(stateRef.current, target, performance.now(), knownRatePerSecond);
    if (prefersReducedMotion()) setDrawn(target);
  }, [target, knownRatePerSecond]);

  useEffect(() => {
    if (prefersReducedMotion()) return undefined;
    let frame = 0;
    const tick = (now: number) => {
      const state = stateRef.current;
      if (state) {
        const next = sampleGlide(state, now);
        setDrawn((current) => (Math.abs(current - next) < 0.0005 ? current : next));
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  return drawn;
}
