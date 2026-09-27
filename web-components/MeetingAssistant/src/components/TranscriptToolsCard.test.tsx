import { render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeetingUIStateDTO } from '../bridge/types';
import TranscriptToolsCard from './TranscriptToolsCard';

const intents = vi.hoisted(() => ({ setAutomation: vi.fn(), setPostProcessingModel: vi.fn(), startPostProcessing: vi.fn() }));
vi.mock('../bridge/meetingBridge', () => intents);

const toolsAnalysisCss = readFileSync('src/styles/meeting-assistant/tools-analysis.css', 'utf8');

const ui = {
  isPostProcessing: false,
  activePostProcessingMeetingId: null,
  selectedMeetingId: 'meeting-1',
  displayedMeetingWorkOwnerId: 'meeting-1',
  postProcessingModel: 'Whisper',
  availableModels: [{ id: 'whisper', name: 'Whisper', displayName: 'Whisper', provider: null, category: 'local' }],
  hasRecordedAudio: true,
  postProcessingAggregateProgress: 0,
  postProcessingStage: '',
  postProcessingMessage: '',
  postProcessingSourceTotal: 1,
  postProcessingSourceIndex: 0,
  windowRetranscriptionStatus: null,
  sessionAutoRetranscribeOnStop: false,
  sessionAutoAnalyzeOnComplete: false,
  sessionAutoRetranscribeDuringRecording: false,
  sessionAutoAnalyzeModes: ['summary'],
  sessionAutoAnalyzeTiming: 'after',
  sessionAutoAnalyzeCustomInstructions: '',
} as MeetingUIStateDTO;

describe('TranscriptToolsCard', () => {
  beforeEach(() => Object.values(intents).forEach((mock) => mock.mockReset()));

  it('renders the canonical labeled tool row and closed automation popover', () => {
    render(<TranscriptToolsCard ui={ui} />);
    expect(screen.getByRole('heading', { name: 'Transcript Tools' })).toBeInTheDocument();
    expect(screen.getByText('Model:')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Improve Transcript' }).querySelector('svg')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Add Speaker Labels' }).querySelector('svg')).not.toBeNull();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opens automation in a popover and reveals conditional options', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<TranscriptToolsCard ui={ui} />);
    await user.click(screen.getByRole('button', { name: 'Automation' }));
    expect(screen.getByRole('dialog', { name: 'Automation for this recording' })).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'Auto-analyze on complete' }));
    expect(intents.setAutomation).toHaveBeenCalledWith({ autoAnalyzeOnComplete: true });
    rerender(<TranscriptToolsCard ui={{ ...ui, sessionAutoAnalyzeOnComplete: true }} />);
    expect(screen.getByText('Run analysis')).toBeInTheDocument();
    expect(screen.getByText('Modes')).toBeInTheDocument();
  });

  it('uses the configured secondary color for analysis timing radios', async () => {
    const user = userEvent.setup();
    render(<TranscriptToolsCard ui={{ ...ui, sessionAutoAnalyzeOnComplete: true }} />);
    await user.click(screen.getByRole('button', { name: 'Automation' }));
    expect(screen.getAllByRole('radio')).toHaveLength(2);
    expect(toolsAnalysisCss).toMatch(/\.meeting-automation-analysis-options input\[type='radio'\] \{[\s\S]*accent-color: var\(--secondary\);/);
  });

  it('renders the automation popover through a portal into document.body, positioned as a fixed overlay', async () => {
    const user = userEvent.setup();
    render(<TranscriptToolsCard ui={ui} />);
    await user.click(screen.getByRole('button', { name: 'Automation' }));

    const dialog = screen.getByRole('dialog', { name: 'Automation for this recording' });
    // Rendered as a direct child of <body> (outside the card's DOM subtree),
    // so a scrolling ancestor of the Transcript Tools card can never clip it.
    expect(dialog.parentElement).toBe(document.body);
    expect(dialog.style.position).toBe('fixed');
  });

  it('spaces mode toggles with the fieldset gap alone, without an additional per-row margin', () => {
    // A `.meeting-switch-control` used inside the Modes fieldset must not
    // also carry its own top/bottom margin: that would stack on top of the
    // fieldset's `gap` and roughly double the space between adjacent
    // toggles (the reported "two lines of space" regression).
    expect(toolsAnalysisCss).toMatch(
      /\.meeting-automation-analysis-options \.meeting-switch-control \{[\s\S]*margin: 0;/,
    );
  });

  it('gives the popover a single consistent base font size instead of leaving radio/toggle labels at the browser default', () => {
    expect(toolsAnalysisCss).toMatch(/\.meeting-automation-popover \{[\s\S]*font-size: var\(--font-size-body\);/);
    expect(toolsAnalysisCss).toMatch(/\.meeting-switch-control \{[\s\S]*font-size: var\(--font-size-body\);/);
    expect(toolsAnalysisCss).toMatch(
      /\.meeting-automation-analysis-options fieldset label \{[\s\S]*font-size: var\(--font-size-body\);/,
    );
  });

  it('shows one-based source progress only for the meeting that owns the job', () => {
    const { rerender } = render(
      <TranscriptToolsCard
        ui={{
          ...ui,
          isPostProcessing: true,
          activePostProcessingMeetingId: 'meeting-1',
          displayedMeetingWorkOwnerId: 'meeting-1',
          postProcessingAggregateProgress: 0.417,
          postProcessingStage: 'transcription',
          postProcessingMessage: 'Re-transcribing: 12s / 00:30',
          postProcessingSourceIndex: 1,
          postProcessingSourceTotal: 2,
          postProcessingCurrentTime: 12.5,
          postProcessingTotalTime: 30,
          postProcessingETA: 17,
        }}
      />,
    );

    expect(screen.getByText(/transcription — Re-transcribing: 12s \/ 00:30 \(1\/2\)/)).toBeInTheDocument();
    expect(screen.getByText(/12.5s \(0:13\) \/ 30.0s \(0:30\) — 42% — ETA: ~17s/)).toBeInTheDocument();
    expect((document.querySelector('.meeting-progress-bar-fill') as HTMLElement).style.width).toBe('42%');

    rerender(
      <TranscriptToolsCard
        ui={{
          ...ui,
          isPostProcessing: true,
          activePostProcessingMeetingId: 'meeting-1',
          selectedMeetingId: 'meeting-2',
          displayedMeetingWorkOwnerId: 'meeting-2',
          postProcessingStage: 'transcription',
          postProcessingMessage: 'Re-transcribing: 12s / 00:30',
          postProcessingSourceIndex: 1,
          postProcessingSourceTotal: 2,
        }}
      />,
    );

    expect(screen.queryByText(/transcription — Re-transcribing/)).not.toBeInTheDocument();
    expect(screen.getByText('Post-processing is running for another meeting in the background.')).toBeInTheDocument();
  });
});
