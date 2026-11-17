import { useCallback, useSyncExternalStore } from 'react';

/** Whether the reader has folded the follow-up box away, per task chain. It lives in the page so it survives the box unmounting and remounting as a task finishes and restarts, and is gone when the app quits. A chain nobody has touched is open. */
const collapsedByTask = new Map<string, boolean>();
/** Chains whose box is folded because a run started, not because the reader folded it. Only these are unfolded again when the run finishes. */
const foldedForRun = new Set<string>();
/** Turns that have already had their one fold at run start, so a box that remounts mid-run (after an approval prompt, say) is not folded again over the reader's own unfold. */
const turnsFoldedAtStart = new Set<string>();
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

/** The reader's own fold or unfold. It ends any claim the run has on the box: whatever they chose stays until they change it. */
export function setFollowUpComposerCollapsed(taskKey: string, collapsed: boolean): void {
  foldedForRun.delete(taskKey);
  if (isFollowUpComposerCollapsed(taskKey) === collapsed) return;
  if (collapsed) collapsedByTask.set(taskKey, true);
  else collapsedByTask.delete(taskKey);
  emit();
}

/** Folds the box when a run starts, so the working surface gets the room. Done once per turn, and never over a box the reader already folded. Returns whether it folded the box. */
export function foldFollowUpComposerForRun(taskKey: string, turnId: string): boolean {
  if (turnsFoldedAtStart.has(turnId)) return false;
  turnsFoldedAtStart.add(turnId);
  if (isFollowUpComposerCollapsed(taskKey)) return false;
  collapsedByTask.set(taskKey, true);
  foldedForRun.add(taskKey);
  emit();
  return true;
}

/** Opens the box again when the run finishes, but only if the run is what folded it. A box the reader folded stays folded. Returns whether it unfolded the box. */
export function unfoldFollowUpComposerAfterRun(taskKey: string): boolean {
  if (!foldedForRun.delete(taskKey)) return false;
  if (!isFollowUpComposerCollapsed(taskKey)) return false;
  collapsedByTask.delete(taskKey);
  emit();
  return true;
}

/** Test seam: forget every chain's collapsed state. */
export function resetFollowUpComposerViews(): void {
  collapsedByTask.clear();
  foldedForRun.clear();
  turnsFoldedAtStart.clear();
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
