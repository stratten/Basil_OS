import { useSyncExternalStore } from 'react';

/**
 * Where a history search result should land: the item that was opened (an Agent Task chain or a chat), the words that
 * were searched for, and the sections of that item (turns or messages) that contain them. The sidebar publishes it
 * when a result is chosen while the search box has text, and the viewing surface consumes it to open, scroll to, and
 * highlight the matching section.
 */
export interface SearchFocus {
  /** Id of the opened item: the root task id of a chain, or a conversation id. */
  scopeId: string;
  query: string;
  tokens: string[];
  /** Ids of the turns or messages of the scope that contain the query, in display order. */
  matchedIds: string[];
  /** Distinguishes two selections of the same scope so each one navigates once. */
  nonce: number;
}

let currentFocus: SearchFocus | null = null;
let nextNonce = 0;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach(listener => listener());
}

export function publishSearchFocus(focus: Omit<SearchFocus, 'nonce'>): void {
  nextNonce += 1;
  currentFocus = { ...focus, nonce: nextNonce };
  emit();
}

export function clearSearchFocus(): void {
  if (!currentFocus) return;
  currentFocus = null;
  emit();
}

export function getSearchFocus(): SearchFocus | null {
  return currentFocus;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React hook returning the current search focus, re-rendering when it is published or cleared. */
export function useSearchFocus(): SearchFocus | null {
  return useSyncExternalStore(subscribe, getSearchFocus, getSearchFocus);
}
