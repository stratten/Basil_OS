import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import type { AudioSourceKindDTO, TranscriptLineDTO } from '../bridge/types';
import { useCopiedFlag } from '@shared/useCopyFeedback';
import { plainMarkdownText } from '@shared/plainMarkdownText';
import { copyText } from '../bridge/meetingBridge';
import { LINK_FLASH_MS, useCompanionLinks } from '../companion/companionLinks';
import { KIND_LABELS } from '../companion/CompanionItemCard';
import { chipsByRow, spanRowIds, timedRowFromLine } from '../companion/companionTranscriptLinks';
import { buildTranscriptRows, formatTranscriptForCopy, formatTranscriptTimestamp } from '../lib/transcriptFormatting';
import { CheckIcon, CloseIcon, CopyIcon } from './MeetingIcons';

export { buildTranscriptRows };

interface TranscriptPanelProps {
  transcript: TranscriptLineDTO[];
  ui: {
    transcriptionState: string;
    isApplyingWindowedRetranscription: boolean;
    isRecording?: boolean;
    hasRecordedAudio?: boolean;
    isPostProcessing?: boolean;
    activePostProcessingMeetingId?: string | null;
    displayedMeetingWorkOwnerId?: string | null;
    isCapturePaused?: boolean;
    isLiveTranscriptionEnabled?: boolean;
  };
}

/** One Companion item a transcript line carries a chip for. */
interface TranscriptChip {
  id: string;
  kindLabel: string;
  summary: string;
}

const SUMMARY_MAX_CHARS = 90;
const NO_CHIPS = new Map<string, TranscriptChip[]>();
const NO_LINKED_ROWS: ReadonlySet<string> = new Set();

function summarize(text: string): string {
  const plain = plainMarkdownText(text);
  return plain.length > SUMMARY_MAX_CHARS ? `${plain.slice(0, SUMMARY_MAX_CHARS - 1)}…` : plain;
}

function sameChips(a: TranscriptChip[], b: TranscriptChip[]): boolean {
  return a.length === b.length && a.every((chip, index) => chip.id === b[index].id && chip.kindLabel === b[index].kindLabel && chip.summary === b[index].summary);
}

function TranscriptPanel({ transcript, ui }: TranscriptPanelProps) {
  const links = useCompanionLinks();
  const [searchActive, setSearchActive] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [currentMatchIndex, setCurrentMatchIndex] = useState(0);
  const [copied, flashCopied] = useCopiedFlag();
  const [isNearBottom, setIsNearBottom] = useState(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());
  const setRowRef = useCallback((id: string, node: HTMLDivElement | null) => {
    if (node) rowRefs.current.set(id, node);
    else rowRefs.current.delete(id);
  }, []);

  const rows = useMemo(() => buildTranscriptRows(transcript), [transcript]);
  const timedRows = useMemo(() => rows.map((row) => timedRowFromLine(row.line)), [rows]);
  const timedRowsRef = useRef(timedRows);
  timedRowsRef.current = timedRows;

  // Chips beside the lines the Companion spoke up on. A line whose chips did not change keeps the same array, so its memoized row does not re-render when another line's chips change.
  const chipItems = links?.items;
  const previousChips = useRef(NO_CHIPS);
  const chipsForRow = useMemo(() => {
    if (!chipItems || chipItems.length === 0) {
      previousChips.current = NO_CHIPS;
      return NO_CHIPS;
    }
    const itemsById = new Map(chipItems.map((item) => [item.id, item]));
    const next = new Map<string, TranscriptChip[]>();
    for (const [rowId, itemIds] of chipsByRow(timedRows, chipItems)) {
      const chips = itemIds.flatMap((itemId) => {
        const item = itemsById.get(itemId);
        return item ? [{ id: item.id, kindLabel: KIND_LABELS[item.kind], summary: summarize(item.text) }] : [];
      });
      const earlier = previousChips.current.get(rowId);
      next.set(rowId, earlier && sameChips(earlier, chips) ? earlier : chips);
    }
    previousChips.current = next;
    return next;
  }, [chipItems, timedRows]);

  // The lines to highlight: the span of whichever item is hovered, plus the span just jumped to.
  const [flashed, setFlashed] = useState<{ key: string; rowIds: ReadonlySet<string> } | null>(null);
  const hoveredItemId = links?.hoveredItemId ?? null;
  const hoveredRowIds = useMemo<ReadonlySet<string>>(() => {
    const item = hoveredItemId === null ? undefined : chipItems?.find((candidate) => candidate.id === hoveredItemId);
    return item ? new Set(spanRowIds(timedRows, item.transcript_range)) : NO_LINKED_ROWS;
  }, [hoveredItemId, chipItems, timedRows]);

  const transcriptFocus = links?.transcriptFocus ?? null;
  useEffect(() => {
    if (transcriptFocus === null) return undefined;
    const ids = spanRowIds(timedRowsRef.current, { start: transcriptFocus.start, end: transcriptFocus.end });
    if (ids.length === 0) return undefined;
    setIsNearBottom(false);
    const first = rowRefs.current.get(ids[0]);
    if (first && typeof first.scrollIntoView === 'function') first.scrollIntoView({ block: 'center', behavior: 'smooth' });
    setFlashed({ key: transcriptFocus.key, rowIds: new Set(ids) });
    const timer = setTimeout(() => setFlashed((current) => (current?.key === transcriptFocus.key ? null : current)), LINK_FLASH_MS);
    return () => clearTimeout(timer);
  }, [transcriptFocus]);

  const showInCompanion = links?.showInCompanion;
  const hover = links?.hover;
  const isGeneratingTranscriptForThisMeeting = Boolean(
    ui.isPostProcessing && ui.activePostProcessingMeetingId === ui.displayedMeetingWorkOwnerId,
  );
  const matchIds = useMemo(() => {
    const needle = searchTerm.trim().toLocaleLowerCase();
    return needle ? rows.filter((row) => row.line.text.toLocaleLowerCase().includes(needle)).map((row) => row.line.id) : [];
  }, [rows, searchTerm]);

  useEffect(() => {
    if (!isNearBottom || ui.isApplyingWindowedRetranscription || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [rows, isNearBottom, ui.isApplyingWindowedRetranscription]);

  useEffect(() => {
    setCurrentMatchIndex(0);
  }, [searchTerm]);

  useEffect(() => {
    if (matchIds.length === 0) return;
    const boundedIndex = Math.min(currentMatchIndex, matchIds.length - 1);
    const row = rowRefs.current.get(matchIds[boundedIndex]);
    if (row && typeof row.scrollIntoView === 'function') {
      row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
    setIsNearBottom(false);
  }, [currentMatchIndex, matchIds]);

  const handleScroll = () => {
    const node = scrollRef.current;
    if (!node) return;
    const distanceFromBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
    setIsNearBottom(distanceFromBottom < 48);
  };

  const copyAll = () => {
    copyText(formatTranscriptForCopy(rows));
    flashCopied();
  };

  const closeSearch = () => {
    setSearchActive(false);
    setSearchTerm('');
    setCurrentMatchIndex(0);
  };

  const focusMatch = (direction: -1 | 1) => {
    if (matchIds.length === 0) return;
    setCurrentMatchIndex((index) => (index + direction + matchIds.length) % matchIds.length);
  };

  return (
    <section className="meeting-transcript-panel">
      <div className="meeting-transcript-scroll" ref={scrollRef} onScroll={handleScroll}>
        {rows.length === 0 && (
          <p className="meeting-transcript-empty-state">
            {ui.transcriptionState === 'loadingModels'
              ? 'Loading transcription models…'
              : ui.isRecording
                ? ui.isCapturePaused
                  ? 'Recording is paused.'
                  : ui.isLiveTranscriptionEnabled === false
                    ? 'Live transcription is off. The transcript will be generated when the meeting ends.'
                    : 'Listening for speech…'
                : isGeneratingTranscriptForThisMeeting
                  ? 'Generating a transcript from the recorded audio…'
                  : ui.hasRecordedAudio
                    ? 'No transcript was saved for this recording, but the audio was captured. Use Transcript Tools below to generate one.'
                    : 'Transcript will appear here once recording starts.'}
          </p>
        )}
        {rows.map((row) => (
          <TranscriptRow
            key={row.line.id}
            line={row.line}
            isGroupLeader={row.isGroupLeader}
            label={row.label}
            color={row.color}
            searchTerm={searchActive ? searchTerm : ''}
            setRef={setRowRef}
            chips={chipsForRow.get(row.line.id)}
            isLinked={hoveredRowIds.has(row.line.id) || flashed?.rowIds.has(row.line.id) === true}
            isFlashing={flashed?.rowIds.has(row.line.id) === true}
            onOpenItem={showInCompanion}
            onHoverItem={hover}
          />
        ))}
      </div>
      {rows.length > 0 && (
        <div className="meeting-transcript-overlay-actions">
          {searchActive ? (
            <div className="meeting-transcript-search-overlay">
              <SearchIcon />
              <input autoFocus type="text" placeholder="Search transcript..." value={searchTerm} onChange={(event) => setSearchTerm(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') focusMatch(1); if (event.key === 'Escape') closeSearch(); }} />
              {searchTerm.trim() && <span className="meeting-transcript-match-count">{matchIds.length === 0 ? 'No results' : `${Math.min(currentMatchIndex + 1, matchIds.length)} of ${matchIds.length}`}</span>}
              <span className="meeting-transcript-search-divider" />
              <button type="button" onClick={() => focusMatch(-1)} disabled={matchIds.length === 0} aria-label="Previous match"><ChevronIcon direction="up" /></button>
              <button type="button" onClick={() => focusMatch(1)} disabled={matchIds.length === 0} aria-label="Next match"><ChevronIcon direction="down" /></button>
              <button type="button" onClick={closeSearch} aria-label="Close search"><CloseIcon /></button>
            </div>
          ) : (
            <button type="button" className="meeting-transcript-icon-button" onClick={() => setSearchActive(true)} aria-label="Search transcript" title="Search transcript">
              <SearchIcon />
            </button>
          )}
          <button type="button" className="meeting-transcript-copy-all" onClick={copyAll} aria-label="Copy all transcript text" title="Copy all transcript text">
            {copied ? <CheckIcon /> : <CopyIcon />}
            <span>{copied ? 'Copied' : 'Copy All'}</span>
          </button>
        </div>
      )}
    </section>
  );
}

/**
 * Test-only render counters. `TranscriptRow` increments its own row's count
 * on every render (not just every commit), so a regression test can prove
 * that an unrelated re-render of `TranscriptPanel` does not force every row
 * to re-render, and that only the row backing a changed line re-renders.
 * These are unused by production code and carry no behavioral effect.
 */
const transcriptRowRenderCounts = new Map<string, number>();
export function __getTranscriptRowRenderCountForTests(id: string): number {
  return transcriptRowRenderCounts.get(id) ?? 0;
}
export function __resetTranscriptRowRenderCountsForTests(): void {
  transcriptRowRenderCounts.clear();
}

const TranscriptRow = memo(function TranscriptRow({ line, isGroupLeader, label, color, searchTerm, setRef, chips, isLinked, isFlashing, onOpenItem, onHoverItem }: {
  line: TranscriptLineDTO;
  isGroupLeader: boolean;
  label: string | null;
  color: string | null;
  searchTerm: string;
  setRef: (id: string, node: HTMLDivElement | null) => void;
  chips: TranscriptChip[] | undefined;
  isLinked: boolean;
  isFlashing: boolean;
  onOpenItem: ((itemId: string) => void) | undefined;
  onHoverItem: ((itemId: string | null) => void) | undefined;
}) {
  transcriptRowRenderCounts.set(line.id, (transcriptRowRenderCounts.get(line.id) ?? 0) + 1);
  const timestamp = formatTranscriptTimestamp(line.displayStart);
  const style = color ? { '--transcript-row-color': color } as CSSProperties : undefined;
  const hasChips = chips !== undefined && chips.length > 0 && onOpenItem !== undefined && onHoverItem !== undefined;
  return (
    <div ref={(node) => setRef(line.id, node)} className={`meeting-transcript-row${isGroupLeader ? ' is-group-leader' : ''}${label ? ' is-attributed' : ''}${line.isInterim ? ' is-interim' : ''}${hasChips ? ' has-links' : ''}${isLinked ? ' is-linked' : ''}${isFlashing ? ' is-link-flash' : ''}`} style={style}>
      {label ? (
        <span className="meeting-transcript-badge-column">
          {isGroupLeader && <span className="meeting-transcript-attribution-badge">{sourceIcon(line.source)}{label}</span>}
        </span>
      ) : null}
      <span className="meeting-transcript-timestamp">{timestamp}</span>
      <span className={label ? 'meeting-transcript-bubble' : 'meeting-transcript-plain-text'}>
        <HighlightedText text={line.text.trim()} query={searchTerm} />
      </span>
      {hasChips && <TranscriptLinkChips chips={chips} onOpenItem={onOpenItem} onHoverItem={onHoverItem} />}
    </div>
  );
});

/** The right-hand gutter of a transcript line: one chip per Companion item that spoke up here, or a single count chip that opens a list when there are several. */
function TranscriptLinkChips({ chips, onOpenItem, onHoverItem }: {
  chips: TranscriptChip[];
  onOpenItem: (itemId: string) => void;
  onHoverItem: (itemId: string | null) => void;
}) {
  const [listOpen, setListOpen] = useState(false);
  const containerRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (!listOpen) return undefined;
    const close = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setListOpen(false);
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [listOpen]);

  const open = (itemId: string) => {
    setListOpen(false);
    onHoverItem(null);
    onOpenItem(itemId);
  };

  if (chips.length === 1) {
    const [chip] = chips;
    return (
      <span className="meeting-transcript-link-gutter">
        <button
          type="button"
          className="meeting-transcript-link-chip"
          title={chip.summary}
          aria-label={`Show the ${chip.kindLabel.toLocaleLowerCase()} from the Companion: ${chip.summary}`}
          onClick={() => open(chip.id)}
          onMouseEnter={() => onHoverItem(chip.id)}
          onMouseLeave={() => onHoverItem(null)}
          onFocus={() => onHoverItem(chip.id)}
          onBlur={() => onHoverItem(null)}
        >
          {chip.kindLabel}
        </button>
      </span>
    );
  }

  return (
    <span className="meeting-transcript-link-gutter" ref={containerRef} onKeyDown={(event) => { if (event.key === 'Escape') setListOpen(false); }}>
      <button
        type="button"
        className="meeting-transcript-link-chip"
        aria-haspopup="true"
        aria-expanded={listOpen}
        aria-label={`${chips.length} Companion notes on this line`}
        onClick={() => setListOpen((current) => !current)}
      >
        {chips.length} notes
      </button>
      {listOpen && (
        <ul className="meeting-transcript-link-list" aria-label="Companion notes on this line">
          {chips.map((chip) => (
            <li key={chip.id}>
              <button
                type="button"
                onClick={() => open(chip.id)}
                onMouseEnter={() => onHoverItem(chip.id)}
                onMouseLeave={() => onHoverItem(null)}
                onFocus={() => onHoverItem(chip.id)}
                onBlur={() => onHoverItem(null)}
              >
                <span className="meeting-transcript-link-list-kind">{chip.kindLabel}</span>
                <span className="meeting-transcript-link-list-summary">{chip.summary}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </span>
  );
}

export default memo(TranscriptPanel, (previous, next) => (
  previous.transcript === next.transcript
  && previous.ui.transcriptionState === next.ui.transcriptionState
  && previous.ui.isApplyingWindowedRetranscription === next.ui.isApplyingWindowedRetranscription
  && previous.ui.isRecording === next.ui.isRecording
  && previous.ui.hasRecordedAudio === next.ui.hasRecordedAudio
  && previous.ui.isPostProcessing === next.ui.isPostProcessing
  && previous.ui.activePostProcessingMeetingId === next.ui.activePostProcessingMeetingId
  && previous.ui.displayedMeetingWorkOwnerId === next.ui.displayedMeetingWorkOwnerId
  && previous.ui.isCapturePaused === next.ui.isCapturePaused
  && previous.ui.isLiveTranscriptionEnabled === next.ui.isLiveTranscriptionEnabled
));

function HighlightedText({ text, query }: { text: string; query: string }) {
  const needle = query.trim();
  if (!needle) return <>{text}</>;
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(${escaped})`, 'ig'));
  return <>{parts.map((part, index) => part.toLocaleLowerCase() === needle.toLocaleLowerCase() ? <mark key={index}>{part}</mark> : <Fragment key={index}>{part}</Fragment>)}</>;
}

function sourceIcon(source: AudioSourceKindDTO | null) {
  if (!source) return null;
  return source === 'Microphone'
    ? <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5.5" y="1.5" width="5" height="8" rx="2.5" /><path d="M3.7 7.4a4.3 4.3 0 0 0 8.6 0h1.2a5.5 5.5 0 0 1-4.9 5.45V15H7.4v-2.15A5.5 5.5 0 0 1 2.5 7.4h1.2Z" /></svg>
    : <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 6h3l3-2.8v9.6L5 10H2V6Zm8.1-.8a4 4 0 0 1 0 5.6l-.8-.8a2.9 2.9 0 0 0 0-4l.8-.8Z" /></svg>;
}

function SearchIcon() {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><circle cx="6.8" cy="6.8" r="4.2" /><path d="m10 10 3.2 3.2" strokeLinecap="round" /></svg>;
}

function ChevronIcon({ direction }: { direction: 'up' | 'down' }) {
  return <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><path d={direction === 'up' ? 'm4 10 4-4 4 4' : 'm4 6 4 4 4-4'} strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
