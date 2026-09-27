import { useCallback, useEffect, useRef, useState, type WheelEvent } from 'react';

interface HistoryRowRevealDeleteOptions {
  enabled: boolean;
}

interface HistoryRowRevealDelete {
  isOpen: boolean;
  offset: number;
  handleWheel: (event: WheelEvent<HTMLElement>) => void;
  close: () => void;
}

const ACTION_WIDTH = 60;
const OPEN_THRESHOLD = 60;
const MAX_OFFSET = 80;

export function useHistoryRowRevealDelete({
  enabled,
}: HistoryRowRevealDeleteOptions): HistoryRowRevealDelete {
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
    accumulatedDeltaRef.current = Math.max(0, Math.min(MAX_OFFSET, accumulatedDeltaRef.current + event.deltaX));
    if (accumulatedDeltaRef.current >= OPEN_THRESHOLD) {
      accumulatedDeltaRef.current = ACTION_WIDTH;
      setOffset(ACTION_WIDTH);
      setIsOpen(true);
      return;
    }
    setOffset(accumulatedDeltaRef.current);
    if (accumulatedDeltaRef.current === 0) setIsOpen(false);
    resetTimerRef.current = setTimeout(() => {
      if (accumulatedDeltaRef.current < OPEN_THRESHOLD) close();
    }, 300);
  }, [close, enabled]);

  return { isOpen, offset, handleWheel, close };
}
