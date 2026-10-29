import type { CompanionTimelineState } from './companionReducer';
import type { CompanionStatus } from './types';

export type CompanionStatusTone = 'off' | 'on' | 'busy' | 'warn';

export function companionStatusLabel(status: CompanionStatus): { label: string; tone: CompanionStatusTone } {
  if (!status.live) return { label: 'Saved notes', tone: 'off' };
  if (!status.enabled) return { label: 'Off', tone: 'off' };
  if (status.capacity === 'paused') return { label: 'Paused', tone: 'warn' };
  if (status.capacity === 'deferred') return { label: 'Slowed', tone: 'warn' };
  if ((status.investigating ?? 0) > 0) return { label: 'Investigating', tone: 'busy' };
  if (status.evaluating) return { label: 'Thinking', tone: 'busy' };
  if (status.mode === 'passive') return { label: 'Standing by', tone: 'on' };
  return { label: 'Listening', tone: 'on' };
}

/** `HH:MM:SS` in the reader's locale, for "last checked at". */
export function formatCheckedAt(at: Date): string {
  return at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/** The label shown in the status row. A Companion that is simply listening says when it last looked, so a quiet pane does not look stalled. Any other state, and a Companion that has not looked yet, keeps its plain label. */
export function companionDisplayLabel(label: string, lastCheckedAt: Date | null): string {
  return label === 'Listening' && lastCheckedAt !== null ? `Listening, last checked at ${formatCheckedAt(lastCheckedAt)}` : label;
}

export function companionCapacityNotice(status: CompanionStatus): string | null {
  if (!status.live || !status.enabled) return null;
  if (status.capacity === 'paused') {
    return 'The Companion paused itself because transcription is falling behind. It resumes on its own once transcription catches up.';
  }
  if (status.capacity === 'deferred') {
    return 'The Companion is slowing down to let transcription catch up.';
  }
  return null;
}

export function companionHasContent(timeline: CompanionTimelineState): boolean {
  return (
    timeline.items.length > 0 ||
    timeline.chat.length > 0 ||
    timeline.watches.length > 0 ||
    timeline.roots.length > 0
  );
}

export function shouldShowCompanionPane(args: {
  meetingId: string | null;
  dismissedFor: string | null;
  isEnabled: boolean;
  hasContent: boolean;
}): boolean {
  if (args.meetingId === null) return false;
  if (args.dismissedFor === args.meetingId) return false;
  return args.isEnabled || args.hasContent;
}

/** The one-line description of the Companion's configuration, shown while the settings section is collapsed ("2 sources, 1 watch, research on"). */
export function companionSettingsSummary(args: { timeline: CompanionTimelineState; pendingSourceCount: number; researchOn: boolean | null }): string {
  const sources = args.timeline.roots.length + args.pendingSourceCount;
  const watches = args.timeline.watches.filter((watch) => watch.active).length;
  const parts = [
    `${sources === 0 ? 'No' : sources} ${sources === 1 ? 'source' : 'sources'}`,
    `${watches === 0 ? 'no' : watches} ${watches === 1 ? 'watch' : 'watches'}`,
  ];
  if (args.researchOn !== null) parts.push(`research ${args.researchOn ? 'on' : 'off'}`);
  return parts.join(', ');
}

/** True when nothing is configured yet, which is when the settings section opens by itself. */
export function companionNeedsSetup(args: { timeline: CompanionTimelineState; pendingSourceCount: number }): boolean {
  return args.timeline.roots.length === 0 && args.pendingSourceCount === 0 && args.timeline.watches.every((watch) => !watch.active);
}
