import { describe, expect, it } from 'vitest';
import { companionPort, companionTargetIsRecording, companionTargetMeetingId, type CompanionTargetUi } from './companionTarget';

function ui(overrides: Partial<CompanionTargetUi> = {}): CompanionTargetUi {
  return {
    isRecording: false,
    isViewingPastMeeting: false,
    displayedMeetingWorkOwnerId: 'shown',
    selectedAnalysisModelId: null,
    recordingMeetingId: null,
    companionApiPort: 8123,
    ...overrides,
  };
}

describe('companionTargetMeetingId', () => {
  it('is null without UI state', () => {
    expect(companionTargetMeetingId(null)).toBeNull();
  });

  it('uses the live meeting while recording', () => {
    expect(companionTargetMeetingId(ui({ isRecording: true, recordingMeetingId: 'live' }))).toBe('live');
  });

  it('uses the displayed meeting when browsing a past meeting during a recording', () => {
    expect(companionTargetMeetingId(ui({ isRecording: true, isViewingPastMeeting: true, recordingMeetingId: 'live' }))).toBe('shown');
  });

  it('uses the displayed meeting when not recording and null when nothing is displayed', () => {
    expect(companionTargetMeetingId(ui())).toBe('shown');
    expect(companionTargetMeetingId(ui({ displayedMeetingWorkOwnerId: null }))).toBeNull();
  });
});

describe('companionTargetIsRecording', () => {
  it('is true only for a live meeting that is displayed', () => {
    expect(companionTargetIsRecording(ui({ isRecording: true, recordingMeetingId: 'live' }))).toBe(true);
    expect(companionTargetIsRecording(ui({ isRecording: true, recordingMeetingId: null }))).toBe(false);
    expect(companionTargetIsRecording(ui({ isRecording: true, isViewingPastMeeting: true, recordingMeetingId: 'live' }))).toBe(false);
    expect(companionTargetIsRecording(null)).toBe(false);
  });
});

describe('companionPort', () => {
  it('accepts valid ports and rejects everything else as 0', () => {
    expect(companionPort(ui())).toBe(8123);
    expect(companionPort(ui({ companionApiPort: 0 }))).toBe(0);
    expect(companionPort(ui({ companionApiPort: -5 }))).toBe(0);
    expect(companionPort(ui({ companionApiPort: 70000 }))).toBe(0);
    expect(companionPort(ui({ companionApiPort: 80.5 }))).toBe(0);
    expect(companionPort(ui({ companionApiPort: undefined }))).toBe(0);
    expect(companionPort(null)).toBe(0);
  });
});
