import { describe, expect, it } from 'vitest';
import { emptyTimelineState } from './companionReducer';
import { companionCapacityNotice, companionDisplayLabel, companionHasContent, formatCheckedAt, companionStatusLabel, shouldShowCompanionPane } from './companionPaneState';
import { citationLabel, formatItemTime, itemCopyText } from './CompanionItemCard';
import { EMPTY_COMPANION_STATUS, type CompanionItem, type CompanionStatus } from './types';

function status(overrides: Partial<CompanionStatus>): CompanionStatus {
  return { ...EMPTY_COMPANION_STATUS, ...overrides };
}

function item(overrides: Partial<CompanionItem> = {}): CompanionItem {
  return {
    id: 'i1',
    seq: 0,
    kind: 'answer',
    text: 'Retries back off.',
    confidence: 0.9,
    citations: [],
    no_source: false,
    transcript_range: { start: 65, end: 70, turn_ids: [] },
    trigger: 'question',
    watch_id: null,
    truncated: false,
    pinned: false,
    dismissed: false,
    ...overrides,
  };
}

describe('companionStatusLabel', () => {
  it('covers every documented state', () => {
    expect(companionStatusLabel(status({ live: false, enabled: true }))).toEqual({ label: 'Saved notes', tone: 'off' });
    expect(companionStatusLabel(status({ live: true, enabled: false }))).toEqual({ label: 'Off', tone: 'off' });
    expect(companionStatusLabel(status({ live: true, enabled: true, capacity: 'paused' }))).toEqual({ label: 'Paused', tone: 'warn' });
    expect(companionStatusLabel(status({ live: true, enabled: true, capacity: 'deferred' }))).toEqual({ label: 'Slowed', tone: 'warn' });
    expect(companionStatusLabel(status({ live: true, enabled: true, investigating: 1 }))).toEqual({ label: 'Investigating', tone: 'busy' });
    expect(companionStatusLabel(status({ live: true, enabled: true, investigating: 1, capacity: 'paused' }))).toEqual({ label: 'Paused', tone: 'warn' });
    expect(companionStatusLabel(status({ live: true, enabled: true, evaluating: true }))).toEqual({ label: 'Thinking', tone: 'busy' });
    expect(companionStatusLabel(status({ live: true, enabled: true, mode: 'passive' }))).toEqual({ label: 'Standing by', tone: 'on' });
    expect(companionStatusLabel(status({ live: true, enabled: true }))).toEqual({ label: 'Listening', tone: 'on' });
  });

  it('lets a capacity warning outrank the evaluating state', () => {
    expect(companionStatusLabel(status({ live: true, enabled: true, capacity: 'paused', evaluating: true })).label).toBe('Paused');
  });
});

describe('companionCapacityNotice', () => {
  it('speaks plainly and never shows the raw reason code', () => {
    const paused = companionCapacityNotice(status({ live: true, enabled: true, capacity: 'paused', capacity_reason: 'lag' }));
    expect(paused).toContain('paused itself');
    expect(paused).not.toContain('lag');
    expect(companionCapacityNotice(status({ live: true, enabled: true, capacity: 'deferred' }))).toContain('slowing down');
  });

  it('is silent when healthy, off or not live', () => {
    expect(companionCapacityNotice(status({ live: true, enabled: true }))).toBeNull();
    expect(companionCapacityNotice(status({ live: true, enabled: false, capacity: 'paused' }))).toBeNull();
    expect(companionCapacityNotice(status({ live: false, enabled: true, capacity: 'paused' }))).toBeNull();
  });
});

describe('pane visibility', () => {
  it('detects any saved content', () => {
    expect(companionHasContent(emptyTimelineState)).toBe(false);
    expect(companionHasContent({ ...emptyTimelineState, items: [item()] })).toBe(true);
    expect(companionHasContent({ ...emptyTimelineState, chat: [{ id: 'm', role: 'user', text: 'x', meeting_time: 0, truncated: false, status: 'complete', seq: 0 }] })).toBe(true);
  });

  it('shows for an enabled or populated meeting unless hidden for that meeting', () => {
    expect(shouldShowCompanionPane({ meetingId: null, dismissedFor: null, isEnabled: true, hasContent: true })).toBe(false);
    expect(shouldShowCompanionPane({ meetingId: 'm1', dismissedFor: null, isEnabled: false, hasContent: false })).toBe(false);
    expect(shouldShowCompanionPane({ meetingId: 'm1', dismissedFor: null, isEnabled: true, hasContent: false })).toBe(true);
    expect(shouldShowCompanionPane({ meetingId: 'm1', dismissedFor: null, isEnabled: false, hasContent: true })).toBe(true);
    expect(shouldShowCompanionPane({ meetingId: 'm1', dismissedFor: 'm1', isEnabled: true, hasContent: true })).toBe(false);
    expect(shouldShowCompanionPane({ meetingId: 'm2', dismissedFor: 'm1', isEnabled: true, hasContent: true })).toBe(true);
  });
});

describe('item card helpers', () => {
  it('formats the transcript marker with padded minutes', () => {
    expect(formatItemTime(item())).toBe('[01:05]');
    expect(formatItemTime(item({ transcript_range: { start: 3725, end: 3730, turn_ids: [] } }))).toBe('[1:02:05]');
  });

  it('labels single-line and ranged citations', () => {
    expect(citationLabel({ path: 'a.py', line_start: 3, line_end: 3, excerpt: '' })).toBe('a.py:3');
    expect(citationLabel({ path: 'a.py', line_start: 3, line_end: 9, excerpt: '' })).toBe('a.py:3-9');
  });

  it('appends sources to the copied text only when there are citations', () => {
    expect(itemCopyText(item())).toBe('Retries back off.');
    const copied = itemCopyText(item({ citations: [{ path: 'src/retry.py', line_start: 12, line_end: 20, excerpt: 'x' }] }));
    expect(copied).toBe('Retries back off.\n\nSources:\n- src/retry.py:12-20');
  });
});

describe('companionDisplayLabel', () => {
  const checked = new Date(2026, 9, 16, 14, 5, 9);

  it('says when a listening Companion last looked, and only then', () => {
    expect(companionDisplayLabel('Listening', checked)).toBe(`Listening, last checked at ${formatCheckedAt(checked)}`);
    expect(companionDisplayLabel('Listening', null)).toBe('Listening');
    expect(companionDisplayLabel('Thinking', checked)).toBe('Thinking');
    expect(companionDisplayLabel('Standing by', checked)).toBe('Standing by');
    expect(companionDisplayLabel('Paused', checked)).toBe('Paused');
  });

  it('formats the time with hours, minutes and seconds', () => {
    expect(formatCheckedAt(checked)).toMatch(/05.*09/);
  });
});
