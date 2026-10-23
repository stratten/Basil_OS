import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type AnimationEvent, type ReactNode } from 'react';
import NewItemsPill from '../../../shared/NewItemsPill';
import { useStickToBottom } from '../../../shared/useStickToBottom';
import type { CompanionStreamEntry } from './companionStreamSelectors';
import { STREAM_SEQ_ATTRIBUTE, useStreamSeen } from './useStreamSeen';

/** How long a card keeps its highlight after the reader is taken to it. */
export const HIGHLIGHT_MS = 1600;

/** How long a dismissed row plays its exit before it leaves the stream. Matches `companion-row-leave` in companion.css. */
export const LEAVE_MS = 240;

/** The name of the keyframes on `.companion-stream-row.is-arriving` that grow the row open; its end is when the arrival is over. */
export const ARRIVAL_ANIMATION = 'companion-row-arrive';

export const STREAM_KEY_ATTRIBUTE = 'data-stream-key';

export interface CompanionStreamHandle {
  /** Scrolls the row into view and highlights it. Returns false when no such row is in the stream. */
  scrollToKey: (key: string, block?: ScrollLogicalPosition) => boolean;
}

interface CompanionStreamProps {
  entries: CompanionStreamEntry[];
  renderEntry: (entry: CompanionStreamEntry) => ReactNode;
  /** True once the stream shows real data; rows present at that moment never animate in. */
  ready: boolean;
  /** Rows at or below this seq are backlog and never animate. */
  baselineSeq: number;
  /** Unseen rows, oldest first. The pill shows their count while the reader is scrolled away from the bottom. */
  unseen: CompanionStreamEntry[];
  onSeen: (seq: number) => void;
  /** Whether the stream is on screen, so nothing is marked seen while the pane is hidden. */
  active: boolean;
  empty: ReactNode;
  /** A note above the first row (for example, that the notes are saved and read-only). */
  lead?: ReactNode;
  /** The live "working" row, shown last. */
  working: ReactNode;
  footer?: ReactNode;
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function highestSeq(entries: CompanionStreamEntry[]): number {
  return entries.reduce((highest, entry) => (entry.seq !== null && entry.seq > highest ? entry.seq : highest), 0);
}

/** The scrolling arrival-order stream: newest at the bottom, following new rows while the reader is at the bottom and never moving them while they read above. A pill reports rows that arrived out of view, and rows are marked seen only once they have actually been on screen. */
const CompanionStream = forwardRef<CompanionStreamHandle, CompanionStreamProps>(function CompanionStream(
  { entries, renderEntry, ready, baselineSeq, unseen, onSeen, active, empty, lead, working, footer },
  ref,
) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const { isPinned } = useStickToBottom(scrollRef, contentRef);
  const [highlightedKey, setHighlightedKey] = useState<string | null>(null);
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previousEntries = useRef<Map<string, CompanionStreamEntry>>(new Map());
  const leaveTimers = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const [leaving, setLeaving] = useState<Map<string, CompanionStreamEntry>>(new Map());
  // Rows whose arrival animation has finished. The clipping an arrival needs is dropped then, so a settled card keeps its shadow and highlight ring.
  const [arrived, setArrived] = useState<ReadonlySet<string>>(() => new Set());
  const markArrived = (event: AnimationEvent<HTMLDivElement>, key: string) => {
    if (event.target !== event.currentTarget || event.animationName !== ARRIVAL_ANIMATION) return;
    setArrived((existing) => (existing.has(key) ? existing : new Set(existing).add(key)));
  };
  const mountedMaxSeq = useRef<number | null>(null);
  if (mountedMaxSeq.current === null && ready) mountedMaxSeq.current = highestSeq(entries);
  const animateAfterSeq = Math.max(baselineSeq, mountedMaxSeq.current ?? 0);

  useEffect(() => () => {
    if (highlightTimer.current) clearTimeout(highlightTimer.current);
    leaveTimers.current.forEach((timer) => clearTimeout(timer));
  }, []);

  // A row that left the stream (it was dismissed, or "Show dismissed" was turned off) plays a short exit instead of vanishing. Rows that never had a place in the stream, and everything under reduced motion, simply go.
  useLayoutEffect(() => {
    const current = new Map(entries.map((entry) => [entry.key, entry] as const));
    const departed = Array.from(previousEntries.current.values()).filter((entry) => entry.seq !== null && !current.has(entry.key));
    previousEntries.current = current;
    setLeaving((existing) => {
      const next = new Map(Array.from(existing).filter(([key]) => !current.has(key)));
      if (!prefersReducedMotion()) for (const entry of departed) next.set(entry.key, entry);
      return next.size === existing.size && Array.from(next.keys()).every((key) => existing.has(key)) ? existing : next;
    });
    if (departed.length === 0 || prefersReducedMotion()) return;
    const keys = departed.map((entry) => entry.key);
    const timer = setTimeout(() => {
      leaveTimers.current.delete(timer);
      setLeaving((existing) => {
        const next = new Map(existing);
        for (const key of keys) next.delete(key);
        return next;
      });
    }, LEAVE_MS);
    leaveTimers.current.add(timer);
  }, [entries]);

  const rendered = leaving.size === 0
    ? entries
    : [...entries, ...Array.from(leaving.values())].sort((a, b) => (a.seq ?? Number.MAX_SAFE_INTEGER) - (b.seq ?? Number.MAX_SAFE_INTEGER));
  const rowsKey = entries.map((entry) => entry.key).join('|');
  useStreamSeen(scrollRef, rowsKey, active && ready, onSeen);

  const scrollToKey = useCallback((key: string, block: ScrollLogicalPosition = 'center'): boolean => {
    const row = Array.from(scrollRef.current?.querySelectorAll<HTMLElement>(`[${STREAM_KEY_ATTRIBUTE}]`) ?? []).find((candidate) => candidate.getAttribute(STREAM_KEY_ATTRIBUTE) === key);
    if (!row) return false;
    row.scrollIntoView?.({ block, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
    setHighlightedKey(key);
    if (highlightTimer.current) clearTimeout(highlightTimer.current);
    highlightTimer.current = setTimeout(() => setHighlightedKey(null), HIGHLIGHT_MS);
    return true;
  }, []);

  useImperativeHandle(ref, () => ({ scrollToKey }), [scrollToKey]);

  const jumpToFirstUnseen = () => {
    const first = unseen[0];
    if (first) scrollToKey(first.key, 'start');
  };

  return (
    <div className="companion-stream-frame">
      <div className="companion-scroll" ref={scrollRef}>
        <div ref={contentRef} className="companion-stream" role="log" aria-live="polite" aria-label="Companion feed">
          {lead}
          {entries.length === 0 && empty}
          {rendered.map((entry) => {
            const isNew = entry.seq !== null && entry.seq > animateAfterSeq;
            const isLeaving = leaving.has(entry.key) && !entries.some((candidate) => candidate.key === entry.key);
            const isArriving = isNew && !arrived.has(entry.key);
            const className = ['companion-stream-row', isArriving ? 'is-arriving' : '', highlightedKey === entry.key ? 'is-highlighted' : '', isLeaving ? 'is-leaving' : ''].filter(Boolean).join(' ');
            return (
              <div key={entry.key} className={className} onAnimationEnd={isArriving ? (event) => markArrived(event, entry.key) : undefined} aria-hidden={isLeaving ? true : undefined} {...(isLeaving ? { inert: '' } : {})} {...{ [STREAM_KEY_ATTRIBUTE]: entry.key, ...(entry.seq !== null ? { [STREAM_SEQ_ATTRIBUTE]: entry.seq } : {}) }}>
                {renderEntry(entry)}
              </div>
            );
          })}
          {working}
          {footer}
        </div>
      </div>
      <NewItemsPill count={isPinned ? 0 : unseen.length} onClick={jumpToFirstUnseen} />
    </div>
  );
});

export default CompanionStream;
