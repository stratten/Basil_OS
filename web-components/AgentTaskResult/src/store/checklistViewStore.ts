import { useSyncExternalStore } from 'react';

/**
 * What the reader has opened of a chain's checklist: whether the full window is open, and on which item. It lives in the page, so it survives the surfaces unmounting and is gone when the app quits. The window never opens on its own.
 */
interface ChecklistView {
  windowRoot: string | null;
  // The item the window should show selected when it opens from a row.
  windowItemId: string | null;
}

let view: ChecklistView = { windowRoot: null, windowItemId: null };
const listeners = new Set<() => void>();

function publish(next: ChecklistView) {
  view = next;
  listeners.forEach(listener => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function openChecklistWindow(rootId: string, itemId?: string): void {
  const nextItem = itemId ?? null;
  if (view.windowRoot === rootId && view.windowItemId === nextItem) return;
  publish({ ...view, windowRoot: rootId, windowItemId: nextItem });
}

export function closeChecklistWindow(): void {
  if (view.windowRoot === null) return;
  publish({ ...view, windowRoot: null, windowItemId: null });
}

export function useChecklistWindowRoot(): string | null {
  return useSyncExternalStore(subscribe, () => view.windowRoot, () => null);
}

export function useChecklistWindowItemId(): string | null {
  return useSyncExternalStore(subscribe, () => view.windowItemId, () => null);
}

/** Test seam: forget everything the reader opened. */
export function resetChecklistViewForTests(): void {
  publish({ windowRoot: null, windowItemId: null });
}
