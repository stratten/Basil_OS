import { useCallback, useSyncExternalStore } from 'react';

/** Whether the reader has folded the follow-up box away, per task chain. It lives in the page so it survives the box unmounting and remounting as a task finishes and restarts, and is gone when the app quits. A chain nobody has touched is open. */
const collapsedByTask = new Map<string, boolean>();
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

export function isFollowUpComposerCollapsed(taskKey: string): boolean {
  return collapsedByTask.get(taskKey) ?? false;
}

export function setFollowUpComposerCollapsed(taskKey: string, collapsed: boolean): void {
  if (isFollowUpComposerCollapsed(taskKey) === collapsed) return;
  if (collapsed) collapsedByTask.set(taskKey, true);
  else collapsedByTask.delete(taskKey);
  emit();
}

/** Test seam: forget every chain's collapsed state. */
export function resetFollowUpComposerViews(): void {
  collapsedByTask.clear();
  emit();
}

export function useFollowUpComposerCollapsed(taskKey: string): [boolean, (collapsed: boolean) => void] {
  const collapsed = useSyncExternalStore(
    subscribe,
    () => isFollowUpComposerCollapsed(taskKey),
    () => false,
  );
  const update = useCallback((next: boolean) => setFollowUpComposerCollapsed(taskKey, next), [taskKey]);
  return [collapsed, update];
}
