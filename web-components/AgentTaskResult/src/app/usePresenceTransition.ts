import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { TransitionEvent } from 'react';

export type PresencePhase = 'entering' | 'present' | 'exiting' | 'exited';

export interface PresenceTransition {
  shouldRender: boolean;
  phase: PresencePhase;
  completeTransition: (event: TransitionEvent<HTMLElement>) => void;
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function usePresenceTransition(visible: boolean): PresenceTransition {
  const [phase, setPhase] = useState<PresencePhase>(() => visible ? 'entering' : 'exited');
  const animationFrameRef = useRef<number | null>(null);

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
        return prefersReducedMotion() ? 'exited' : 'exiting';
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

  const completeTransition = useCallback((event: TransitionEvent<HTMLElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.propertyName !== 'opacity' && event.propertyName !== 'width' && event.propertyName !== 'flex-basis') return;
    setPhase(current => current === 'exiting' ? 'exited' : current === 'entering' ? 'present' : current);
  }, []);

  return {
    shouldRender: phase !== 'exited',
    phase,
    completeTransition,
  };
}
