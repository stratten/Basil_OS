import { useSyncExternalStore } from 'react';

let currentLevel = 0;
const listeners = new Set<() => void>();

export function publishCaptureMeter(level: number) {
  const clamped = clampMeterLevel(level);
  if (currentLevel === clamped) return;
  currentLevel = clamped;
  listeners.forEach((listener) => listener());
}

export function useCaptureMeter(): number {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return currentLevel;
}

function getServerSnapshot() {
  return currentLevel;
}

function clampMeterLevel(level: number) {
  return Math.min(1, Math.max(0, level));
}

export function __resetCaptureMeterForTests() {
  currentLevel = 0;
  listeners.clear();
}
