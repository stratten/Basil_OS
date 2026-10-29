import { useSyncExternalStore } from 'react';

const EMPTY: readonly string[] = Object.freeze([]);
let currentPaths: readonly string[] = EMPTY;
const listeners = new Set<() => void>();

/** Native mirrors the files dropped onto the window while a follow-up is being recorded, in the order they will be sent. */
export function publishFollowUpCaptureReferences(paths: readonly string[]) {
  const unchanged = paths.length === currentPaths.length && paths.every((path, index) => path === currentPaths[index]);
  if (unchanged) return;
  currentPaths = paths.length === 0 ? EMPTY : Object.freeze([...paths]);
  listeners.forEach((listener) => listener());
}

export function useFollowUpCaptureReferences(): readonly string[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return currentPaths;
}

export function __resetFollowUpCaptureReferencesForTests() {
  currentPaths = EMPTY;
  listeners.clear();
}
