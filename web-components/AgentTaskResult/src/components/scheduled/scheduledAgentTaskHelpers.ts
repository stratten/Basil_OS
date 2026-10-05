// Pure helpers + constants extracted from ScheduledAgentTaskDetail.tsx so the
// orchestrator component stays focused on state, effects, and layout. Nothing
// in here touches React; everything is referentially transparent and safe to
// unit test in isolation.
//
// Anything added here must remain JSX-free — keep this file as a `.ts` so
// accidental component additions get caught at the import site.

import type { ScheduledAgentTask } from '../../types';
import type { DropdownOption } from '../Dropdown';

// Mon=0 .. Sun=6 to match the backend contract.
export const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function getUserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

export function getCurrentTimeHHMM(): string {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}

export function getDefaultRunAtLocal(): string {
  // <input type="datetime-local"> wants YYYY-MM-DDTHH:MM in local time.
  // Default to "one hour from now", rounded down to the minute.
  const t = new Date(Date.now() + 60 * 60 * 1000);
  const yyyy = t.getFullYear();
  const mm = String(t.getMonth() + 1).padStart(2, '0');
  const dd = String(t.getDate()).padStart(2, '0');
  const hh = String(t.getHours()).padStart(2, '0');
  const min = String(t.getMinutes()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}T${hh}:${min}`;
}

export function buildTimezoneOptions(currentTz: string): DropdownOption<string>[] {
  let zones: string[] = [];
  try {
    // Available in Safari 15.4+ / modern WKWebView.
    const intlAny = Intl as unknown as { supportedValuesOf?: (k: string) => string[] };
    if (typeof intlAny.supportedValuesOf === 'function') {
      zones = intlAny.supportedValuesOf('timeZone');
    }
  } catch {
    zones = [];
  }
  if (zones.length === 0) {
    // Defensive fallback if Intl.supportedValuesOf is unavailable.
    zones = [
      'UTC',
      'America/New_York',
      'America/Chicago',
      'America/Denver',
      'America/Los_Angeles',
      'America/Phoenix',
      'America/Anchorage',
      'Pacific/Honolulu',
      'Europe/London',
      'Europe/Paris',
      'Europe/Berlin',
      'Europe/Madrid',
      'Europe/Rome',
      'Europe/Athens',
      'Europe/Moscow',
      'Asia/Dubai',
      'Asia/Kolkata',
      'Asia/Bangkok',
      'Asia/Singapore',
      'Asia/Hong_Kong',
      'Asia/Shanghai',
      'Asia/Tokyo',
      'Australia/Sydney',
      'Pacific/Auckland',
    ];
  }
  // Pin the user's current zone to the top, deduped.
  const ordered = [currentTz, ...zones.filter(z => z !== currentTz)];
  return ordered.map(z => ({
    value: z,
    label: z === currentTz ? `${z} (current)` : z,
  }));
}

// Convert a 24-hour "HH:MM" string (the backend storage format) into a
// 12-hour display string like "8:00 PM". Falls back to returning the input
// verbatim on any parse failure so we never swallow content. We standardize
// on 12-hour display throughout the scheduled-agent-task surfaces; if we ever
// introduce a user-level time-format preference, this is the single hook
// that needs to consult it.
export function formatTime12h(hhmm: string): string {
  const match = /^(\d{1,2}):(\d{2})$/.exec(hhmm.trim());
  if (!match) return hhmm;
  let hour = Number(match[1]);
  const minute = match[2];
  if (!Number.isFinite(hour) || hour < 0 || hour > 23) return hhmm;
  const period = hour >= 12 ? 'PM' : 'AM';
  hour = hour % 12;
  if (hour === 0) hour = 12;
  return `${hour}:${minute} ${period}`;
}

// Render a full Date in a compact 12-hour form, e.g. "Apr 17, 2026, 8:00 PM".
// Used for next-run and per-run timestamps so they visually match the
// schedule summary.
export function formatTimestamp12h(input: string | Date): string {
  const date = input instanceof Date ? input : new Date(input);
  if (Number.isNaN(date.getTime())) return String(input);
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

// Extract a display-friendly basename from a full filesystem path. Used by
// the Attached Files list so each row leads with the human-readable file or
// folder name and shows the full path beneath it in muted text. Trailing
// slashes are stripped first so a directory path like "/Users/me/Docs/"
// still yields "Docs" rather than an empty string. Falls back to the input
// itself when the path has no separators (e.g. a bare filename).
export function pathBasename(path: string): string {
  const trimmed = path.replace(/\/+$/, '');
  const idx = trimmed.lastIndexOf('/');
  if (idx < 0) return trimmed || path;
  return trimmed.slice(idx + 1) || path;
}

// Title is optional in the create form. When the user leaves it blank we
// derive a sensible default from the agent task body — first non-empty line,
// trimmed, capped at 60 chars with an ellipsis if we had to truncate. We
// intentionally cut at line breaks first so multi-line agent tasks don't
// produce a noisy single-line title. Falls back to "Scheduled Agent Task"
// only if the agent task body itself is somehow empty (the create button is
// disabled in that case anyway, so this is purely defensive).
export function deriveTitleFromAgentTask(agentTaskText: string): string {
  const firstLine = agentTaskText.split(/\r?\n/).map(s => s.trim()).find(s => s.length > 0) || '';
  if (!firstLine) return 'Scheduled Task';
  const MAX = 60;
  if (firstLine.length <= MAX) return firstLine;
  return `${firstLine.slice(0, MAX - 1).trimEnd()}…`;
}

export function summarizeSchedule(agentTask: ScheduledAgentTask): string {
  if (agentTask.schedule_type === 'one_time') {
    const runAt = String(agentTask.schedule_config.run_at || '');
    const rendered = runAt ? formatTimestamp12h(runAt) : 'unspecified time';
    return `One-time at ${rendered} (${agentTask.timezone})`;
  }
  const mode = String(agentTask.schedule_config.mode || 'daily');
  if (mode === 'interval') {
    return `Every ${String(agentTask.schedule_config.minutes || '?')} minutes`;
  }
  if (mode === 'weekly') {
    const dayNums = Array.isArray(agentTask.schedule_config.days) ? (agentTask.schedule_config.days as number[]) : [];
    const dayLabels = dayNums.map(n => WEEKDAY_LABELS[n] ?? String(n)).join(', ');
    const time = formatTime12h(String(agentTask.schedule_config.time || '09:00'));
    return `Weekly on [${dayLabels || '—'}] at ${time}`;
  }
  const time = formatTime12h(String(agentTask.schedule_config.time || '09:00'));
  return `Daily at ${time}`;
}
