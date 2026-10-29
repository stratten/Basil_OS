import { useSyncExternalStore } from 'react';
import { normalizeDateDisplayStyle, type DateDisplayStyle } from '@shared/timestampDisplay';

// The formatter and style type live in shared so the Settings web view renders timestamps identically.
export { formatTimestampForDisplay } from '@shared/timestampDisplay';
export type { DateDisplayStyle } from '@shared/timestampDisplay';

// Module-level store for the host-provided date display preference.
// Mirrors themeBootstrap's host-driven application of theme/fonts, but exposes
// a subscription so React history surfaces re-render live when the host pushes
// a change via window.basilAgentTask.onDateStyleChanged.
let currentStyle: DateDisplayStyle = 'relative';
const listeners = new Set<() => void>();

export function applyHostDateStyle(style: string | undefined | null): void {
  const next = normalizeDateDisplayStyle(style);
  if (next === currentStyle) return;
  currentStyle = next;
  listeners.forEach(listener => listener());
}

export function getDateDisplayStyle(): DateDisplayStyle {
  return currentStyle;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React hook returning the current date display style, re-rendering on change. */
export function useDateDisplayStyle(): DateDisplayStyle {
  return useSyncExternalStore(subscribe, getDateDisplayStyle, getDateDisplayStyle);
}
