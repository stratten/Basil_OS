import { useSyncExternalStore } from 'react';

let currentLevel = 0;
const listeners = new Set<() => void>();

export function publishTranscriptionMeter(level: number): void {
  const clamped = clampMeterLevel(level);
  if (currentLevel === clamped) return;
  currentLevel = clamped;
  listeners.forEach((listener) => listener());
}

export function useTranscriptionMeter(): number {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): number {
  return currentLevel;
}

function getServerSnapshot(): number {
  return currentLevel;
}

function clampMeterLevel(level: number): number {
  return Math.min(1, Math.max(0, level));
}
