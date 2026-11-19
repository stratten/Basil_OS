import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { RefObject, TransitionEvent } from 'react';
import { settleWhenUntransitioned } from './presenceTransitionSettle';

export type PresencePhase = 'entering' | 'present' | 'exiting' | 'exited';

export interface PresenceTransition<T extends HTMLElement = HTMLDivElement> {
  /** Attach to the region's element so an exit that never starts a transition still completes. */
  regionRef: RefObject<T>;
  shouldRender: boolean;
  phase: PresencePhase;
  completeTransition: (event: TransitionEvent<HTMLElement>) => void;
  settle: () => void;
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function usePresenceTransition<T extends HTMLElement = HTMLDivElement>(visible: boolean): PresenceTransition<T> {
  const [phase, setPhase] = useState<PresencePhase>(() => visible ? 'entering' : 'exited');
  const animationFrameRef = useRef<number | null>(null);
  const regionRef = useRef<T>(null);

  const cancelPendingFrame = useCallback(() => {
    if (animationFrameRef.current === null) return;
    cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = null;
  }, []);

  useLayoutEffect(() => {
    cancelPendingFrame();

    if (!visible) {
      setPhase(current => {
        if (current === 'exited') return current;
        // A region hidden before its entrance frame is still invisible, and its entering style matches its exiting style. No property would change, the browser would never send a transitionend, and the region would stay mounted and take up layout space forever.
        if (current === 'entering' || prefersReducedMotion()) return 'exited';
        return 'exiting';
      });
      return;
    }

    if (prefersReducedMotion()) {
      setPhase('present');
      return;
    }

    setPhase(current => current === 'present' || current === 'entering' ? current : 'entering');
    animationFrameRef.current = requestAnimationFrame(() => {
      animationFrameRef.current = null;
      setPhase(current => current === 'entering' ? 'present' : current);
    });
  }, [cancelPendingFrame, visible]);

  useEffect(() => cancelPendingFrame, [cancelPendingFrame]);

  const settle = useCallback(() => {
    setPhase(current => current === 'exiting' ? 'exited' : current === 'entering' ? 'present' : current);
  }, []);

  // The entrance can be cut short before the browser styled it (for example a task that finishes right after it mounts), so the exit changes no property and no transitionend is ever sent. Settle those exits once a frame shows nothing is animating.
  useLayoutEffect(() => {
    if (phase !== 'exiting' || !regionRef.current) return;
    return settleWhenUntransitioned(regionRef.current, settle);
  }, [phase, settle]);

  const completeTransition = useCallback((event: TransitionEvent<HTMLElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.propertyName !== 'opacity' && event.propertyName !== 'width' && event.propertyName !== 'flex-basis') return;
    settle();
  }, [settle]);

  return {
    regionRef,
    shouldRender: phase !== 'exited',
    phase,
    completeTransition,
    settle,
  };
}
