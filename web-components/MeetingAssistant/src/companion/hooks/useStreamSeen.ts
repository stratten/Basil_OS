import { useEffect, useState, type RefObject } from 'react';

/** The attribute a stream row carries so the reader's view can be matched to the row's arrival `seq`. */
export const STREAM_SEQ_ATTRIBUTE = 'data-stream-seq';

/** A card taller than the stream still counts as seen once this much of it is on screen. */
const SEEN_MIN_VISIBLE_PX = 96;
const SEEN_MIN_RATIO = 0.5;

function documentIsVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState !== 'hidden';
}

/**
 * Reports the highest row `seq` that has actually been on screen. A row counts only while the page is visible, so a hidden window or a collapsed sidebar never marks anything seen. It re-observes whenever `rowsKey` changes (rows were added or removed) and whenever the page becomes visible again.
 */
export function useStreamSeen(scrollRef: RefObject<HTMLElement>, rowsKey: string, enabled: boolean, onSeen: (seq: number) => void): void {
  const [visible, setVisible] = useState(documentIsVisible);

  useEffect(() => {
    const update = () => setVisible(documentIsVisible());
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!enabled || !visible || !scroller || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver(
      (records) => {
        let highest = -1;
        for (const record of records) {
          if (!record.isIntersecting) continue;
          if (record.intersectionRatio < SEEN_MIN_RATIO && record.intersectionRect.height < SEEN_MIN_VISIBLE_PX) continue;
          const seq = Number((record.target as HTMLElement).getAttribute(STREAM_SEQ_ATTRIBUTE));
          if (Number.isFinite(seq) && seq > highest) highest = seq;
        }
        if (highest >= 0) onSeen(highest);
      },
      { root: scroller, threshold: [0, SEEN_MIN_RATIO, 1] },
    );
    scroller.querySelectorAll(`[${STREAM_SEQ_ATTRIBUTE}]`).forEach((row) => observer.observe(row));
    return () => observer.disconnect();
  }, [scrollRef, rowsKey, enabled, visible, onSeen]);
}
