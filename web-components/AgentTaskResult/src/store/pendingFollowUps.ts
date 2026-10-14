import { useSyncExternalStore } from 'react';
import * as api from '../services/api';
import { wsManager } from '../services/websocket';

export type PendingFollowUpsByRoot = Readonly<Record<string, string>>;

const EMPTY: PendingFollowUpsByRoot = Object.freeze({});

let snapshot: PendingFollowUpsByRoot = EMPTY;
let requestSeq = 0;
let detach: (() => void) | null = null;
const listeners = new Set<() => void>();

function sameSnapshot(left: PendingFollowUpsByRoot, right: PendingFollowUpsByRoot): boolean {
  const leftKeys = Object.keys(left);
  if (leftKeys.length !== Object.keys(right).length) return false;
  return leftKeys.every(key => left[key] === right[key]);
}

function publish(next: PendingFollowUpsByRoot) {
  if (sameSnapshot(snapshot, next)) return;
  snapshot = next;
  listeners.forEach(listener => listener());
}

/** Reload the durable list of chains that are waiting on a scheduled follow-up check. The latest request wins. */
export async function refreshPendingFollowUps(): Promise<void> {
  if (!api.isApiReady()) return;
  const seq = ++requestSeq;
  try {
    const response = await api.getPendingFollowUps();
    if (seq !== requestSeq) return;
    const next: Record<string, string> = {};
    for (const item of response.follow_ups ?? []) {
      if (item.root_task_id && item.due_at) next[item.root_task_id] = item.due_at;
    }
    publish(next);
  } catch (error) {
    if (seq === requestSeq) {
      console.warn('[PendingFollowUps] Failed to load pending follow-ups:', error);
    }
  }
}

function attach() {
  const stopEvents = wsManager.subscribe(event => {
    if (event.event_type === 'agent_task_follow_up_changed') {
      void refreshPendingFollowUps();
    }
  });
  const stopConnect = wsManager.onConnect(() => {
    void refreshPendingFollowUps();
  });
  detach = () => {
    stopEvents();
    stopConnect();
  };
  void refreshPendingFollowUps();
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

/** Due time (ISO) of the soonest scheduled follow-up for each chain root that is waiting on one. */
export function usePendingFollowUps(): PendingFollowUpsByRoot {
  return useSyncExternalStore(subscribe, () => snapshot, () => EMPTY);
}

/** Test helper: drop all cached state. */
export function resetPendingFollowUpsForTests() {
  requestSeq += 1;
  snapshot = EMPTY;
}
