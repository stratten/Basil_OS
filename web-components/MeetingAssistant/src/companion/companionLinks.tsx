import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { focusCompanionItem, focusTranscript } from '../bridge/meetingBridge';
import type { MeetingFocusRequestDTO, TranscriptLineDTO } from '../bridge/types';
import { spanRowIds, timedRowFromLine } from './companionTranscriptLinks';
import type { CompanionItem } from './types';

/** How long a jumped-to card or span of transcript lines stays highlighted. */
export const LINK_FLASH_MS = 1600;

/** The transcript lines a Companion item came from, to scroll to and highlight. `key` is unique per request, so asking for the same span twice is two requests. */
export interface TranscriptFocus {
  itemId: string;
  start: number;
  end: number;
  key: string;
}

/** A request to show one Companion card stays current for this long, so a pane that mounts just after the request (a window that had to open) still acts on it, and one that remounts much later does not scroll again. */
export const COMPANION_FOCUS_FRESH_MS = 5000;

/** One Companion card to scroll to. */
export interface CompanionFocus {
  itemId: string;
  key: string;
  /** When the request was made, in milliseconds since the epoch. */
  issuedAt: number;
}

/**
 * The two-way connection between the transcript and the Companion's cards. Both windows that show the Companion supply it: the Notetaker window (which has the transcript and, usually, the embedded pane) and the detached Companion window (cards only, which asks the Notetaker window to scroll).
 */
export interface CompanionLinks {
  /** The Companion's items, for the chips beside transcript lines. Empty where there is no transcript. */
  items: CompanionItem[];
  hoveredItemId: string | null;
  hover: (itemId: string | null) => void;
  /** True when at least one transcript line maps to the item, so a card never offers a link that goes nowhere. */
  canShowInTranscript: (item: CompanionItem) => boolean;
  /** Card to transcript. */
  showInTranscript: (item: CompanionItem) => void;
  /** Transcript to card. */
  showInCompanion: (itemId: string) => void;
  transcriptFocus: TranscriptFocus | null;
  companionFocus: CompanionFocus | null;
}

const CompanionLinksContext = createContext<CompanionLinks | null>(null);

/** Null where nothing provides links (a pane rendered on its own), so cards and transcript lines simply show no link controls. */
export function useCompanionLinks(): CompanionLinks | null {
  return useContext(CompanionLinksContext);
}

export function CompanionLinksProvider({ value, children }: { value: CompanionLinks; children: ReactNode }) {
  return <CompanionLinksContext.Provider value={value}>{children}</CompanionLinksContext.Provider>;
}

interface UseCompanionLinksOptions {
  /** `notetaker` owns the transcript; `companion` is the detached card window. */
  role: 'notetaker' | 'companion';
  transcript: TranscriptLineDTO[];
  items: CompanionItem[];
  /** The latest native request to scroll something into view. */
  focusRequest: MeetingFocusRequestDTO | null;
  /** Notetaker only: the embedded Companion pane. Without one, a chip on a transcript line asks the detached window instead. */
  embeddedPane?: { available: boolean; reveal: () => void };
}

/** Builds the link state for one window. */
export function useCompanionLinksValue({ role, transcript, items, focusRequest, embeddedPane }: UseCompanionLinksOptions): CompanionLinks {
  const timedRows = useMemo(() => transcript.map(timedRowFromLine), [transcript]);
  const [hoveredItemId, setHoveredItemId] = useState<string | null>(null);
  const [transcriptFocus, setTranscriptFocus] = useState<TranscriptFocus | null>(null);
  const [companionFocus, setCompanionFocus] = useState<CompanionFocus | null>(null);
  const localCount = useRef(0);
  // A request that was already issued when this window opened is not replayed; one that arrives later, even a repeat of the same target, has a new nonce and is acted on.
  const handledNonce = useRef(focusRequest?.nonce ?? 0);
  const embeddedAvailable = embeddedPane?.available === true;
  const revealEmbedded = useRef(embeddedPane?.reveal);
  revealEmbedded.current = embeddedPane?.reveal;

  useEffect(() => {
    if (focusRequest === null || focusRequest.nonce <= handledNonce.current) return;
    handledNonce.current = focusRequest.nonce;
    if (focusRequest.target === 'transcript' && role === 'notetaker') {
      const { startSeconds, endSeconds } = focusRequest;
      if (typeof startSeconds !== 'number' || typeof endSeconds !== 'number') return;
      setTranscriptFocus({ itemId: focusRequest.itemId, start: startSeconds, end: endSeconds, key: `bridge:${focusRequest.nonce}` });
    } else if (focusRequest.target === 'companion' && role === 'companion') {
      setCompanionFocus({ itemId: focusRequest.itemId, key: `bridge:${focusRequest.nonce}`, issuedAt: Date.now() });
    }
  }, [focusRequest, role]);

  const canShowInTranscript = useCallback(
    (item: CompanionItem) => spanRowIds(timedRows, item.transcript_range).length > 0,
    [timedRows],
  );

  const showInTranscript = useCallback(
    (item: CompanionItem) => {
      const start = Math.max(0, Math.min(item.transcript_range.start, item.transcript_range.end));
      const end = Math.max(0, Math.max(item.transcript_range.start, item.transcript_range.end));
      if (role === 'notetaker') {
        localCount.current += 1;
        setTranscriptFocus({ itemId: item.id, start, end, key: `local:${localCount.current}` });
      } else {
        focusTranscript(item.id, start, end);
      }
    },
    [role],
  );

  const showInCompanion = useCallback(
    (itemId: string) => {
      if (role === 'notetaker' && !embeddedAvailable) {
        focusCompanionItem(itemId);
        return;
      }
      revealEmbedded.current?.();
      localCount.current += 1;
      setCompanionFocus({ itemId, key: `local:${localCount.current}`, issuedAt: Date.now() });
    },
    [role, embeddedAvailable],
  );

  return useMemo(
    () => ({ items, hoveredItemId, hover: setHoveredItemId, canShowInTranscript, showInTranscript, showInCompanion, transcriptFocus, companionFocus }),
    [items, hoveredItemId, canShowInTranscript, showInTranscript, showInCompanion, transcriptFocus, companionFocus],
  );
}
