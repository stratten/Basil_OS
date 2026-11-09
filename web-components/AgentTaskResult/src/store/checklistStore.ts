import { useEffect, useMemo, useSyncExternalStore } from 'react';
import * as api from '../services/api';
import * as checklistApi from '../services/checklistApi';
import type { ChecklistCounts, ChecklistItemChanges, ChecklistItemDraft, ChecklistSnapshot } from '../services/checklistApi';
import { wsManager } from '../services/websocket';

export type ChecklistLoadState = 'idle' | 'loading' | 'ready' | 'error';

export interface ChecklistEntry {
  snapshot: ChecklistSnapshot | null;
  state: ChecklistLoadState;
  error: string | null;
}

/** The counter every compact surface shows: items done over items tracked, plus whether anything waits on the user. */
export interface ChecklistLiveCounts {
  done: number;
  total: number;
  waitingUser: number;
  closed: boolean;
}

const IDLE: ChecklistEntry = Object.freeze({ snapshot: null, state: 'idle', error: null });
// Chains whose checklist nobody is looking at stay cached so reopening one does not flash a loading state, but only this many of them.
const MAX_UNWATCHED_ENTRIES = 12;

const entries = new Map<string, ChecklistEntry>();
const interest = new Map<string, number>();
const requestSeq = new Map<string, number>();
const liveCounts = new Map<string, ChecklistLiveCounts>();
const unwatchedOrder: string[] = [];
const listeners = new Set<() => void>();
let detach: (() => void) | null = null;

function emit() {
  listeners.forEach(listener => listener());
}

function sameCounts(left: ChecklistLiveCounts | undefined, right: ChecklistLiveCounts): boolean {
  return Boolean(left)
    && left!.done === right.done
    && left!.total === right.total
    && left!.waitingUser === right.waitingUser
    && left!.closed === right.closed;
}

function rememberCounts(rootId: string, counts: ChecklistCounts | undefined, closedAt: string | null | undefined): void {
  if (!counts) return;
  const next: ChecklistLiveCounts = {
    done: counts.done,
    total: counts.total,
    waitingUser: counts.waiting_user,
    closed: Boolean(closedAt),
  };
  if (sameCounts(liveCounts.get(rootId), next)) return;
  liveCounts.set(rootId, next);
}

function setEntry(rootId: string, entry: ChecklistEntry): void {
  entries.set(rootId, entry);
  emit();
}

/** Reload one chain's checklist. The latest request wins, so a slow reply can never overwrite a newer one. */
export async function refreshChecklist(rootId: string): Promise<void> {
  if (!rootId || !api.isApiReady()) return;
  const seq = (requestSeq.get(rootId) ?? 0) + 1;
  requestSeq.set(rootId, seq);
  const previous = entries.get(rootId) ?? IDLE;
  if (previous.state !== 'ready') {
    setEntry(rootId, { snapshot: previous.snapshot, state: 'loading', error: null });
  }
  try {
    const snapshot = await checklistApi.getChecklist(rootId);
    if (requestSeq.get(rootId) !== seq) return;
    rememberCounts(rootId, snapshot.counts, snapshot.closed_at);
    setEntry(rootId, { snapshot, state: 'ready', error: null });
  } catch (error) {
    if (requestSeq.get(rootId) !== seq) return;
    const message = error instanceof Error ? error.message : 'The checklist could not be loaded.';
    setEntry(rootId, { snapshot: entries.get(rootId)?.snapshot ?? null, state: 'error', error: message });
  }
}

function handleEvent(event: { event_type: string; [key: string]: unknown }): void {
  if (event.event_type !== 'agent_checklist_updated') return;
  const rootId = typeof event.root_task_id === 'string' ? event.root_task_id : '';
  if (!rootId) return;
  const counts = event.counts as ChecklistCounts | undefined;
  const closedAt = typeof event.closed_at === 'string' ? event.closed_at : null;
  const before = liveCounts.get(rootId);
  rememberCounts(rootId, counts, closedAt);
  if (liveCounts.get(rootId) !== before) emit();
  for (const key of interest.keys()) {
    if (key === rootId || entries.get(key)?.snapshot?.root_task_id === rootId) void refreshChecklist(key);
  }
}

function attach() {
  const stopEvents = wsManager.subscribe(handleEvent);
  const stopConnect = wsManager.onConnect(() => {
    for (const key of interest.keys()) void refreshChecklist(key);
  });
  detach = () => {
    stopEvents();
    stopConnect();
  };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) attach();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && detach) {
      detach();
      detach = null;
    }
  };
}

function watch(rootId: string): () => void {
  interest.set(rootId, (interest.get(rootId) ?? 0) + 1);
  const index = unwatchedOrder.indexOf(rootId);
  if (index >= 0) unwatchedOrder.splice(index, 1);
  if (interest.get(rootId) === 1) void refreshChecklist(rootId);
  return () => {
    const remaining = (interest.get(rootId) ?? 1) - 1;
    if (remaining > 0) {
      interest.set(rootId, remaining);
      return;
    }
    interest.delete(rootId);
    unwatchedOrder.push(rootId);
    while (unwatchedOrder.length > MAX_UNWATCHED_ENTRIES) {
      const evicted = unwatchedOrder.shift()!;
      entries.delete(evicted);
      requestSeq.delete(evicted);
    }
  };
}

export interface ChecklistView {
  entry: ChecklistEntry;
  refresh: () => Promise<void>;
}

/** One chain's checklist, kept current by `agent_checklist_updated` events. Pass `enabled: false` to read the cache without fetching. */
export function useChecklist(rootId: string | undefined, enabled = true): ChecklistView {
  const entry = useSyncExternalStore(
    subscribe,
    () => (rootId ? entries.get(rootId) ?? IDLE : IDLE),
    () => IDLE,
  );
  useEffect(() => {
    if (!rootId || !enabled) return undefined;
    return watch(rootId);
  }, [rootId, enabled]);
  return useMemo(() => ({ entry, refresh: () => (rootId ? refreshChecklist(rootId) : Promise.resolve()) }), [entry, rootId]);
}

const NO_COUNTS: ChecklistLiveCounts | undefined = undefined;

/** The live counter for a chain, from the freshest event or fetch; `fallback` (a history row's counts) applies until one arrives. It never fetches. */
export function useChecklistCounts(rootId: string | undefined, fallback?: { done: number; total: number }): ChecklistLiveCounts {
  const live = useSyncExternalStore(
    subscribe,
    () => (rootId ? liveCounts.get(rootId) : NO_COUNTS),
    () => NO_COUNTS,
  );
  const fallbackDone = fallback?.done ?? 0;
  const fallbackTotal = fallback?.total ?? 0;
  return useMemo(
    () => live ?? { done: fallbackDone, total: fallbackTotal, waitingUser: 0, closed: false },
    [live, fallbackDone, fallbackTotal],
  );
}

async function mutate<T>(rootId: string, run: () => Promise<T>): Promise<T> {
  try {
    const result = await run();
    await refreshChecklist(rootId);
    return result;
  } catch (error) {
    // A conflict means the shown version is stale; load the latest so the retry starts from it.
    if (checklistApi.isChecklistConflict(error)) await refreshChecklist(rootId);
    throw error;
  }
}

export interface ChecklistActions {
  addItem: (draft: ChecklistItemDraft) => Promise<unknown>;
  updateItem: (itemId: string, changes: ChecklistItemChanges) => Promise<unknown>;
  archiveItem: (itemId: string, archived: boolean) => Promise<unknown>;
  closeList: (closed: boolean) => Promise<unknown>;
  saveNotes: (content: string, expectedRevision: number) => Promise<unknown>;
  offerAsTodo: (itemId: string) => Promise<{ todo_id: string; status: string }>;
}

export function checklistActions(rootId: string): ChecklistActions {
  return {
    addItem: draft => mutate(rootId, () => checklistApi.addChecklistItem(rootId, draft)),
    updateItem: (itemId, changes) => mutate(rootId, () => checklistApi.updateChecklistItem(rootId, itemId, changes)),
    archiveItem: (itemId, archived) => mutate(rootId, () => checklistApi.archiveChecklistItem(rootId, itemId, archived)),
    closeList: closed => mutate(rootId, () => checklistApi.closeChecklist(rootId, closed)),
    saveNotes: (content, expectedRevision) => mutate(rootId, () => checklistApi.saveChecklistNotes(rootId, content, expectedRevision)),
    offerAsTodo: itemId => mutate(rootId, () => checklistApi.offerChecklistItemAsTodo(rootId, itemId)),
  };
}

/** Test helper: drop all cached state. */
export function resetChecklistStoreForTests() {
  entries.clear();
  interest.clear();
  requestSeq.clear();
  liveCounts.clear();
  unwatchedOrder.length = 0;
  emit();
}
