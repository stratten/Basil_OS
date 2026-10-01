import { useEffect, useRef, useState } from 'react';
import { prefersReducedMotion } from './prefersReducedMotion';

const BASE_CHARACTERS_PER_SECOND = 90;
const STREAMING_CATCH_UP_SECONDS = 1.2;
const FINISHING_CATCH_UP_SECONDS = 0.4;
const MAX_FRAME_SECONDS = 0.1;

const completedRevealIds = new Set<string>();

function nextRevealBoundary(text: string, index: number): number {
  if (index >= text.length) return text.length;
  const offset = text.slice(index).search(/\s/);
  return offset === -1 ? text.length : index + offset;
}

/**
 * Reveals streamed text on word boundaries at a steady pace so bursts of tokens do not make the bubble jump. Rows that were not streaming when they mounted render their full content immediately.
 */
export function usePacedStreamingText(revealId: string, content: string, streaming: boolean): string {
  const [skipPacing] = useState(() => (
    !streaming
    || completedRevealIds.has(revealId)
    || prefersReducedMotion()
    || typeof globalThis.requestAnimationFrame !== 'function'
  ));
  const [visibleLength, setVisibleLength] = useState(() => (skipPacing ? content.length : 0));
  const revealedRef = useRef(skipPacing ? content.length : 0);
  const contentRef = useRef(content);
  const streamingRef = useRef(streaming);
  contentRef.current = content;
  streamingRef.current = streaming;

  useEffect(() => {
    if (skipPacing) return undefined;
    if (revealedRef.current > content.length) {
      revealedRef.current = content.length;
      setVisibleLength(content.length);
    }
    if (revealedRef.current >= content.length) {
      if (!streaming) completedRevealIds.add(revealId);
      return undefined;
    }
    let frameId = 0;
    let lastTimestamp: number | null = null;
    const step = (timestamp: number) => {
      const elapsedSeconds = lastTimestamp === null
        ? 1 / 60
        : Math.min(MAX_FRAME_SECONDS, Math.max(0, (timestamp - lastTimestamp) / 1000));
      lastTimestamp = timestamp;
      const text = contentRef.current;
      const backlog = text.length - revealedRef.current;
      const catchUpSeconds = streamingRef.current ? STREAMING_CATCH_UP_SECONDS : FINISHING_CATCH_UP_SECONDS;
      const charactersPerSecond = Math.max(BASE_CHARACTERS_PER_SECOND, backlog / catchUpSeconds);
      const advanced = Math.min(text.length, revealedRef.current + charactersPerSecond * elapsedSeconds);
      const nextLength = nextRevealBoundary(text, Math.floor(advanced));
      revealedRef.current = Math.max(advanced, nextLength);
      setVisibleLength((current) => Math.max(current, nextLength));
      if (nextLength >= text.length) {
        revealedRef.current = text.length;
        if (!streamingRef.current) completedRevealIds.add(revealId);
        return;
      }
      frameId = globalThis.requestAnimationFrame(step);
    };
    frameId = globalThis.requestAnimationFrame(step);
    return () => globalThis.cancelAnimationFrame(frameId);
  }, [content, revealId, skipPacing, streaming]);

  return skipPacing ? content : content.slice(0, visibleLength);
}
