import { useCallback, useEffect, useSyncExternalStore } from 'react';
import type { CompanionKindFilter } from './companionStreamSelectors';

/** What the reader has seen and how they arranged the pane for one meeting. It lives in the page, so it survives the pane unmounting while the sidebar is hidden and returning, and is gone when the app quits. */
export interface CompanionViewState {
  /** The highest `seq` the reader has had in view; null until the pane first hydrates for the meeting. */
  lastSeenSeq: number | null;
  pinnedOpen: boolean;
  /** Null until the reader chooses; the pane then opens settings only when nothing is configured yet. */
  settingsOpen: boolean | null;
  composerCollapsed: boolean;
  kindFilter: CompanionKindFilter;
  /** Whether the stream also shows a row for every evaluation, including the ones that stayed silent. Off until the reader asks. */
  showConsidered: boolean;
}

const DEFAULT_VIEW: CompanionViewState = { lastSeenSeq: null, pinnedOpen: true, settingsOpen: null, composerCollapsed: false, kindFilter: 'all', showConsidered: false };

const views = new Map<string, CompanionViewState>();
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** A pane with no meeting (a host that has none to name) shares one anonymous view. */
const NO_MEETING_KEY = '';

export function getCompanionView(meetingId: string | null): CompanionViewState {
  return views.get(meetingId ?? NO_MEETING_KEY) ?? DEFAULT_VIEW;
}

export function updateCompanionView(meetingId: string | null, patch: Partial<CompanionViewState>): void {
  const current = getCompanionView(meetingId);
  const next: CompanionViewState = { ...current, ...patch };
  if (next.lastSeenSeq !== null && current.lastSeenSeq !== null && patch.lastSeenSeq !== undefined) {
    next.lastSeenSeq = Math.max(current.lastSeenSeq, next.lastSeenSeq);
  }
  if ((Object.keys(next) as (keyof CompanionViewState)[]).every((key) => next[key] === current[key])) return;
  views.set(meetingId ?? NO_MEETING_KEY, next);
  emit();
}

/** Test seam: forget every meeting's view state. */
export function resetCompanionViews(): void {
  views.clear();
  emit();
}

export interface CompanionViewController {
  view: CompanionViewState;
  update: (patch: Partial<CompanionViewState>) => void;
  /** Records that everything up to `seq` has been in view. Never moves backward. */
  markSeen: (seq: number) => void;
}

/** The view state for a meeting. On the first hydrated render for a meeting the backlog counts as already seen, so a reopened meeting never reports its whole history as new. */
export function useCompanionView(meetingId: string | null, hydratedBaselineSeq: number | null): CompanionViewController {
  const view = useSyncExternalStore(
    subscribe,
    () => getCompanionView(meetingId),
    () => DEFAULT_VIEW,
  );

  useEffect(() => {
    if (hydratedBaselineSeq === null) return;
    if (getCompanionView(meetingId).lastSeenSeq === null) updateCompanionView(meetingId, { lastSeenSeq: hydratedBaselineSeq });
  }, [meetingId, hydratedBaselineSeq]);

  const update = useCallback(
    (patch: Partial<CompanionViewState>) => updateCompanionView(meetingId, patch),
    [meetingId],
  );
  const markSeen = useCallback(
    (seq: number) => updateCompanionView(meetingId, { lastSeenSeq: seq }),
    [meetingId],
  );
  return { view, update, markSeen };
}
