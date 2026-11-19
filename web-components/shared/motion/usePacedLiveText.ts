import { useEffect, useRef, useState } from 'react';

const BASE_CHARACTERS_PER_SECOND = 90;
// A backlog is worked off within this many seconds, so a large block that lands at once still arrives as a quick, steady reveal rather than a pop.
const LIVE_CATCH_UP_SECONDS = 1.5;
const FINISHED_CATCH_UP_SECONDS = 1.0;
const MAX_FRAME_SECONDS = 0.1;

export interface PacedLiveText {
  /** The part of `content` that has been revealed so far. */
  text: string;
  /** True while revealed text is still catching up with `content`; surfaces that belong after the text should wait. */
  isRevealing: boolean;
}

function reducedMotionRequested(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function nextWordBoundary(text: string, index: number): number {
  if (index >= text.length) return text.length;
  const offset = text.slice(index).search(/\s/);
  return offset === -1 ? text.length : index + offset;
}

/**
 * Reveals text that grows during a live run on word boundaries at a steady pace, so bursts of tokens, or a whole block arriving at once after a stall, do not make the page jump.
 *
 * Text that is already present when the key first renders is shown whole, and a task that was never seen running (one opened from history) is never paced, so nothing the reader has already seen is replayed. Pacing begins once `live` has been true for the current `revealKey`, and it keeps draining after `live` turns false so the end of a run is not cut short. Reduced-motion users get the text as it arrives.
 */
export function usePacedLiveText(revealKey: string, content: string, live: boolean): PacedLiveText {
  const [reducedMotion] = useState(reducedMotionRequested);
  const [reveal, setReveal] = useState({ key: revealKey, length: content.length });
  const revealedRef = useRef(content.length);
  const sawLiveRef = useRef(live);
  const contentRef = useRef(content);
  const liveRef = useRef(live);
  contentRef.current = content;
  liveRef.current = live;
  if (live) sawLiveRef.current = true;

  const canPace = typeof globalThis.requestAnimationFrame === 'function';
  const pacing = sawLiveRef.current && !reducedMotion && canPace;
  const revealedLength = reveal.key === revealKey ? reveal.length : content.length;

  // A different key is a different task: start from whatever it already shows.
  useEffect(() => {
    revealedRef.current = contentRef.current.length;
    sawLiveRef.current = liveRef.current;
    setReveal({ key: revealKey, length: contentRef.current.length });
  }, [revealKey]);

  useEffect(() => {
    if (!pacing) {
      // Stay in step with the content so that pacing, when a run starts, begins from what is already on screen.
      revealedRef.current = content.length;
      setReveal(previous => (
        previous.key === revealKey && previous.length === content.length
          ? previous
          : { key: revealKey, length: content.length }
      ));
      return undefined;
    }
    if (revealedRef.current > content.length) {
      revealedRef.current = content.length;
      setReveal({ key: revealKey, length: content.length });
    }
    if (revealedRef.current >= content.length) return undefined;

    let frameId = 0;
    let lastTimestamp: number | null = null;
    const step = (timestamp: number) => {
      const elapsedSeconds = lastTimestamp === null
        ? 1 / 60
        : Math.min(MAX_FRAME_SECONDS, Math.max(0, (timestamp - lastTimestamp) / 1000));
      lastTimestamp = timestamp;
      const text = contentRef.current;
      const backlog = text.length - revealedRef.current;
      const catchUpSeconds = liveRef.current ? LIVE_CATCH_UP_SECONDS : FINISHED_CATCH_UP_SECONDS;
      const charactersPerSecond = Math.max(BASE_CHARACTERS_PER_SECOND, backlog / catchUpSeconds);
      const advanced = Math.min(text.length, revealedRef.current + charactersPerSecond * elapsedSeconds);
      const nextLength = nextWordBoundary(text, Math.floor(advanced));
      revealedRef.current = Math.max(advanced, nextLength);
      setReveal(previous => (
        previous.key === revealKey && previous.length >= nextLength ? previous : { key: revealKey, length: nextLength }
      ));
      if (nextLength >= text.length) {
        revealedRef.current = text.length;
        return;
      }
      frameId = globalThis.requestAnimationFrame(step);
    };
    frameId = globalThis.requestAnimationFrame(step);
    return () => globalThis.cancelAnimationFrame(frameId);
  }, [content, pacing, revealKey]);

  if (!pacing) return { text: content, isRevealing: false };
  const visibleLength = Math.min(revealedLength, content.length);
  return { text: content.slice(0, visibleLength), isRevealing: visibleLength < content.length };
}
