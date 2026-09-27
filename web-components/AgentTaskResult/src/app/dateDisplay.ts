import { useSyncExternalStore } from 'react';

export type DateDisplayStyle = 'relative' | 'absolute';

// Module-level store for the host-provided date display preference.
// Mirrors themeBootstrap's host-driven application of theme/fonts, but exposes
// a subscription so React history surfaces re-render live when the host pushes
// a change via window.basilAgentTask.onDateStyleChanged.
let currentStyle: DateDisplayStyle = 'relative';
const listeners = new Set<() => void>();

function normalize(style: string | undefined | null): DateDisplayStyle {
  return style === 'absolute' ? 'absolute' : 'relative';
}

export function applyHostDateStyle(style: string | undefined | null): void {
  const next = normalize(style);
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

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/**
 * Format a timestamp for history display, mirroring the Swift
 * DateFormattingUtils semantics:
 *  - relative: "Today, 10:45 AM" / "Yesterday, 10:45 AM" / "Monday, 10:45 AM"
 *    (within the past week) / "Jun 28, 10:45 AM"
 *  - absolute: "2026-06-29 10:45 am" (always shows the year)
 * Both render in the viewer's local time zone.
 */
export function formatHistoryTimestamp(
  input: string | number | Date | undefined | null,
  style: DateDisplayStyle
): string {
  if (input === undefined || input === null || input === '') return '';
  const date = input instanceof Date ? input : new Date(input);
  if (Number.isNaN(date.getTime())) {
    return typeof input === 'string' ? input : '';
  }

  const pad = (n: number) => String(n).padStart(2, '0');
  const hours12 = date.getHours() % 12 || 12;
  const minutes = pad(date.getMinutes());
  const isPM = date.getHours() >= 12;

  if (style === 'absolute') {
    const year = date.getFullYear();
    const month = pad(date.getMonth() + 1);
    const day = pad(date.getDate());
    const ampm = isPM ? 'pm' : 'am';
    return `${year}-${month}-${day} ${hours12}:${minutes} ${ampm}`;
  }

  // Relative
  const timeStr = `${hours12}:${minutes} ${isPM ? 'PM' : 'AM'}`;
  const now = new Date();
  const dayDiff = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);

  if (dayDiff === 0) return `Today, ${timeStr}`;
  if (dayDiff === 1) return `Yesterday, ${timeStr}`;
  if (dayDiff > 1 && dayDiff < 7) {
    const weekday = date.toLocaleDateString(undefined, { weekday: 'long' });
    return `${weekday}, ${timeStr}`;
  }
  const monthDay = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return `${monthDay}, ${timeStr}`;
}
