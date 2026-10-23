import { useCallback, useEffect, useRef, useState, type WheelEvent } from 'react';

interface HistoryRowRevealDeleteOptions {
  enabled: boolean;
  /** Total width of the revealed action area in pixels; rows with two side-by-side actions pass a wider value. */
  actionWidth?: number;
}

interface HistoryRowRevealDelete {
  isOpen: boolean;
  offset: number;
  handleWheel: (event: WheelEvent<HTMLElement>) => void;
  close: () => void;
}

const DEFAULT_ACTION_WIDTH = 60;
const OVERSHOOT = 20;

export function useHistoryRowRevealDelete({
  enabled,
  actionWidth = DEFAULT_ACTION_WIDTH,
}: HistoryRowRevealDeleteOptions): HistoryRowRevealDelete {
  const openThreshold = actionWidth;
  const maxOffset = actionWidth + OVERSHOOT;
  const [offset, setOffset] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const accumulatedDeltaRef = useRef(0);
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const close = useCallback(() => {
    accumulatedDeltaRef.current = 0;
    setOffset(0);
    setIsOpen(false);
  }, []);

  useEffect(() => {
    if (!enabled) close();
  }, [close, enabled]);

  useEffect(() => () => {
    if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
  }, []);

  const handleWheel = useCallback((event: WheelEvent<HTMLElement>) => {
    if (!enabled || Math.abs(event.deltaX) <= Math.abs(event.deltaY) || Math.abs(event.deltaX) < 2) return;
    event.stopPropagation();
    if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
    accumulatedDeltaRef.current = Math.max(0, Math.min(maxOffset, accumulatedDeltaRef.current + event.deltaX));
    if (accumulatedDeltaRef.current >= openThreshold) {
      accumulatedDeltaRef.current = actionWidth;
      setOffset(actionWidth);
      setIsOpen(true);
      return;
    }
    setOffset(accumulatedDeltaRef.current);
    if (accumulatedDeltaRef.current === 0) setIsOpen(false);
    resetTimerRef.current = setTimeout(() => {
      if (accumulatedDeltaRef.current < openThreshold) close();
    }, 300);
  }, [actionWidth, close, enabled, maxOffset, openThreshold]);

  return { isOpen, offset, handleWheel, close };
}
