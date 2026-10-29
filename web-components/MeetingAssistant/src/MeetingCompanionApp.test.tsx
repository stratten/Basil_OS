import { act, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MeetingCompanionApp from './MeetingCompanionApp';

const hoisted = vi.hoisted(() => ({
  eventHandler: null as ((event: unknown) => void) | null,
  useCompanionSpy: vi.fn(),
}));

vi.mock('./bridge/meetingBridge', () => ({
  registerEventHandler: vi.fn((cb: (event: unknown) => void) => {
    hoisted.eventHandler = cb;
  }),
  reportReady: vi.fn(),
  toggleWindowCollapse: vi.fn(),
}));

vi.mock('./lib/hostAppearance', () => ({
  applyMeetingHostFonts: vi.fn(),
  applyMeetingHostTheme: vi.fn(),
}));

vi.mock('./components/WindowChrome', () => ({
  default: ({ title, subtitle }: { title: string; subtitle?: string; children?: ReactNode }) => (
    <output data-testid="chrome">{`${title}|${subtitle ?? ''}`}</output>
  ),
}));

vi.mock('./companion/useCompanion', () => ({
  useCompanion: (args: unknown) => {
    hoisted.useCompanionSpy(args);
    return { state: { phase: 'ready', baselineSeq: 0, timeline: { items: [], chat: [] }, status: { mode: 'active' } }, isEnabled: true, setMode: vi.fn() };
  },
}));

vi.mock('./companion/CompanionPane', () => ({
  default: ({ variant, isTargetRecording }: { variant: string; isTargetRecording: boolean }) => (
    <output data-testid="pane">{`${variant}|${String(isTargetRecording)}`}</output>
  ),
}));

function snapshot(ui: Record<string, unknown>): unknown {
  return { type: 'snapshot', revision: 1, selectionGeneration: 1, protocolVersion: 4, ui };
}

afterEach(() => {
  hoisted.eventHandler = null;
  hoisted.useCompanionSpy.mockClear();
});

describe('MeetingCompanionApp', () => {
  it('waits for the first snapshot and keeps the store idle', () => {
    render(<MeetingCompanionApp />);
    expect(screen.getByText('Connecting to Notetaker…')).toBeInTheDocument();
    expect(hoisted.useCompanionSpy).toHaveBeenLastCalledWith({ meetingId: null, port: 0, selectedModelId: null, isRecording: false });
  });

  it('explains when there is no meeting to show', () => {
    render(<MeetingCompanionApp />);
    act(() => {
      hoisted.eventHandler?.(snapshot({ isRecording: false, isViewingPastMeeting: false, displayedMeetingWorkOwnerId: null, selectedAnalysisModelId: null, companionApiPort: 8123, meetingName: '' }));
    });
    expect(screen.getByText('Start or open a meeting to see its Companion.')).toBeInTheDocument();
  });

  it('binds the pane to the live meeting, the port and the picker model', () => {
    render(<MeetingCompanionApp />);
    act(() => {
      hoisted.eventHandler?.(
        snapshot({
          isRecording: true,
          isCapturePaused: false,
          isViewingPastMeeting: false,
          displayedMeetingWorkOwnerId: 'shown',
          recordingMeetingId: 'live-mic',
          selectedAnalysisModelId: 'model-a',
          companionApiPort: 8123,
          meetingName: 'Weekly sync',
        }),
      );
    });
    expect(screen.getByTestId('pane')).toHaveTextContent('detached|true');
    expect(screen.getByTestId('chrome')).toHaveTextContent('Companion|Weekly sync');
    expect(hoisted.useCompanionSpy).toHaveBeenLastCalledWith({ meetingId: 'live-mic', port: 8123, selectedModelId: 'model-a', isRecording: true });
  });

  it('shows saved notes for the displayed meeting once recording has ended', () => {
    render(<MeetingCompanionApp />);
    act(() => {
      hoisted.eventHandler?.(snapshot({ isRecording: false, isViewingPastMeeting: false, displayedMeetingWorkOwnerId: 'finished', recordingMeetingId: null, selectedAnalysisModelId: null, companionApiPort: 8123, meetingName: '' }));
    });
    expect(screen.getByTestId('pane')).toHaveTextContent('detached|false');
    expect(hoisted.useCompanionSpy).toHaveBeenLastCalledWith({ meetingId: 'finished', port: 8123, selectedModelId: null, isRecording: false });
  });
});
