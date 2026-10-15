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
