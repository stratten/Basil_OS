import { useCallback, useEffect, useRef } from 'react';
import type { MutableRefObject, RefObject } from 'react';
import {
  findRunNavigationElement,
  flashNavigationTarget,
  prefersReducedMotion,
  resolveScrollLocationRunId,
  scrollOffsetForElement,
  type RunNavigationRequest,
} from './runNavigation';

interface RunNavigationScrollOptions {
  scrollRef: RefObject<HTMLDivElement>;
  currentRunId: string;
  priorRunIds: string[];
  expandedCardId: string | null;
  setExpandedCardId: (cardId: string | null) => void;
  navigationRequest?: RunNavigationRequest | null;
  onLocationChange?: (runId: string) => void;
  userIsReadingEarlierRef: MutableRefObject<boolean>;
  onJumpToLatestContent: () => void;
}

export function useRunNavigationScroll({
  scrollRef,
  currentRunId,
  priorRunIds,
  expandedCardId,
  setExpandedCardId,
  navigationRequest,
  onLocationChange,
  userIsReadingEarlierRef,
  onJumpToLatestContent,
}: RunNavigationScrollOptions) {
  const onLocationChangeRef = useRef(onLocationChange);
  onLocationChangeRef.current = onLocationChange;
  const currentRunIdRef = useRef(currentRunId);
  currentRunIdRef.current = currentRunId;
  const reportedLocationRunIdRef = useRef<string>();
  // While a map-initiated scroll travels, the turns it passes over must not be reported as the location.
  const programmaticTargetRunIdRef = useRef<string | null>(null);
  const handledNavigationNonceRef = useRef<number>();

  useEffect(() => {
    programmaticTargetRunIdRef.current = null;
    reportedLocationRunIdRef.current = undefined;
    userIsReadingEarlierRef.current = false;
  }, [currentRunId, userIsReadingEarlierRef]);

  const isProgrammaticScrollActive = useCallback(
    () => programmaticTargetRunIdRef.current !== null,
    [],
  );

  const releaseProgrammaticScroll = useCallback(() => {
    programmaticTargetRunIdRef.current = null;
  }, []);

  const reportScrollLocation = useCallback((container: HTMLElement, atBottom: boolean) => {
    const programmaticTargetRunId = programmaticTargetRunIdRef.current;
    // A map scroll toward an earlier turn may end clamped at the bottom; the bottom rule must not mask its arrival.
    const locationRunId = resolveScrollLocationRunId(
      container,
      currentRunIdRef.current,
      atBottom && !programmaticTargetRunId,
    );
    if (programmaticTargetRunId) {
      if (locationRunId !== programmaticTargetRunId) return;
      programmaticTargetRunIdRef.current = null;
    }
    if (locationRunId === reportedLocationRunIdRef.current) return;
    reportedLocationRunIdRef.current = locationRunId;
    onLocationChangeRef.current?.(locationRunId);
  }, []);

  useEffect(() => {
    if (!navigationRequest || handledNavigationNonceRef.current === navigationRequest.nonce) return;
    const isPriorRun = priorRunIds.includes(navigationRequest.runId);
    const desiredExpandedCardId = isPriorRun ? navigationRequest.runId : null;
    if (expandedCardId !== desiredExpandedCardId) {
      setExpandedCardId(desiredExpandedCardId);
      return;
    }
    const container = scrollRef.current;
    if (!container) return;
    handledNavigationNonceRef.current = navigationRequest.nonce;
    reportedLocationRunIdRef.current = navigationRequest.runId;
    if (navigationRequest.target.kind === 'latest') {
      programmaticTargetRunIdRef.current = null;
      onJumpToLatestContent();
      return;
    }
    const element = findRunNavigationElement(container, navigationRequest, isPriorRun);
    const top = element ? scrollOffsetForElement(container, element) : 0;
    const reduceMotion = prefersReducedMotion();
    userIsReadingEarlierRef.current = true;
    programmaticTargetRunIdRef.current = navigationRequest.runId;
    if (typeof container.scrollTo === 'function') {
      container.scrollTo({ top, behavior: reduceMotion ? 'auto' : 'smooth' });
    } else {
      container.scrollTop = top;
    }
    if (element && !reduceMotion) flashNavigationTarget(element);
  }, [
    expandedCardId,
    navigationRequest,
    onJumpToLatestContent,
    priorRunIds,
    scrollRef,
    setExpandedCardId,
    userIsReadingEarlierRef,
  ]);

  return { isProgrammaticScrollActive, releaseProgrammaticScroll, reportScrollLocation };
}
