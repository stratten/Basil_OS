import type { AgentTaskHistoryItem } from '../../types';

/**
 * Adds a turn to a history list, or replaces the turn that already has its id, in place.
 *
 * The result view keys each earlier turn by its id, so two entries with one id leave React with ghost rows that cannot be opened and disappear on remount. Nothing else stops a second writer from adding a turn another writer already added, so every path that grows the list goes through here. The newer copy wins because it was snapshotted from live state, and the warning keeps the writer that duplicated the turn visible instead of hiding it.
 */
export function upsertHistoryItem(history: readonly AgentTaskHistoryItem[], item: AgentTaskHistoryItem): AgentTaskHistoryItem[] {
  const index = item.id ? history.findIndex(existing => existing.id === item.id) : -1;
  if (index < 0) return [...history, item];
  console.warn(`[AgentStore] Turn ${item.id} was already in the history, so it was replaced instead of listed twice.`);
  const next = [...history];
  next[index] = item;
  return next;
}

/** The same list with each id once, in the position of its first appearance and with the data of its last. A list that is already unique comes back as the same array. */
export function uniqueHistory(items: readonly AgentTaskHistoryItem[]): AgentTaskHistoryItem[] {
  const unique = items.reduce<AgentTaskHistoryItem[]>((kept, item) => upsertHistoryItem(kept, item), []);
  return unique.length === items.length ? (items as AgentTaskHistoryItem[]) : unique;
}
