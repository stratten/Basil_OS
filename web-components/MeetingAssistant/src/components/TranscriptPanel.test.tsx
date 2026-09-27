import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TranscriptLineDTO } from '../bridge/types';
import TranscriptPanel, {
  buildTranscriptRows,
  __getTranscriptRowRenderCountForTests,
  __resetTranscriptRowRenderCountsForTests,
} from './TranscriptPanel';

const copyText = vi.hoisted(() => vi.fn());
vi.mock('../bridge/meetingBridge', () => ({ copyText }));

const line = (id: string, text: string, source: TranscriptLineDTO['source'], speakerId: string | null = null): TranscriptLineDTO => ({
  id, text, source, speakerId, isInterim: false, displayStart: '0:00:03', timelineStartSeconds: 3, timelineEndSeconds: 4, lineComplete: true,
});

describe('TranscriptPanel', () => {
  beforeEach(() => copyText.mockReset());

  it('groups consecutive attribution and prefers source labels', () => {
    const rows = buildTranscriptRows([
      line('1', 'First', 'Microphone', 'speaker9'),
      line('2', 'Second', 'Microphone', 'speaker9'),
      line('3', 'Third', null, 'speaker1'),
    ]);
    expect(rows.map((row) => [row.label, row.isGroupLeader])).toEqual([
      ['Microphone', true],
      ['Microphone', false],
      ['Speaker 2', true],
    ]);
  });

  it('hides overlay controls for an empty transcript', () => {
    render(<TranscriptPanel transcript={[]} ui={{ transcriptionState: 'idle', isApplyingWindowedRetranscription: false }} />);
    expect(screen.getByText('Transcript will appear here once recording starts.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Search transcript' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Copy all transcript text' })).not.toBeInTheDocument();
  });

  it('uses an active listening message once recording has started', () => {
    render(<TranscriptPanel transcript={[]} ui={{ transcriptionState: 'listening', isApplyingWindowedRetranscription: false, isRecording: true }} />);
    expect(screen.getByText('Listening for speech…')).toBeInTheDocument();
    expect(screen.queryByText('Transcript will appear here once recording starts.')).not.toBeInTheDocument();
  });

  it('points to Transcript Tools when audio was captured but no transcript was saved', () => {
    render(<TranscriptPanel transcript={[]} ui={{ transcriptionState: 'idle', isApplyingWindowedRetranscription: false, hasRecordedAudio: true }} />);
    expect(screen.getByText('No transcript was saved for this recording, but the audio was captured. Use Transcript Tools below to generate one.')).toBeInTheDocument();
    expect(screen.queryByText('Transcript will appear here once recording starts.')).not.toBeInTheDocument();
  });

  it('shows a generating message while post-processing is actively running for the displayed meeting', () => {
    render(<TranscriptPanel transcript={[]} ui={{
      transcriptionState: 'idle',
      isApplyingWindowedRetranscription: false,
      hasRecordedAudio: true,
      isPostProcessing: true,
      activePostProcessingMeetingId: 'meeting-1',
      displayedMeetingWorkOwnerId: 'meeting-1',
    }} />);
    expect(screen.getByText('Generating a transcript from the recorded audio…')).toBeInTheDocument();
    expect(screen.queryByText('No transcript was saved for this recording, but the audio was captured. Use Transcript Tools below to generate one.')).not.toBeInTheDocument();
  });

  it('does not show the generating message when post-processing is running for a different meeting', () => {
    render(<TranscriptPanel transcript={[]} ui={{
      transcriptionState: 'idle',
      isApplyingWindowedRetranscription: false,
      hasRecordedAudio: true,
      isPostProcessing: true,
      activePostProcessingMeetingId: 'meeting-2',
      displayedMeetingWorkOwnerId: 'meeting-1',
    }} />);
    expect(screen.getByText('No transcript was saved for this recording, but the audio was captured. Use Transcript Tools below to generate one.')).toBeInTheDocument();
    expect(screen.queryByText('Generating a transcript from the recorded audio…')).not.toBeInTheDocument();
  });

  it('renders badges and bubbles and opens search as an overlay without filtering rows', async () => {
    const user = userEvent.setup();
    render(<TranscriptPanel transcript={[line('1', 'Alpha match', 'Microphone'), line('2', 'Beta', 'SystemAudio')]} ui={{ transcriptionState: 'idle', isApplyingWindowedRetranscription: false }} />);
    expect(screen.getByText('Microphone')).toBeInTheDocument();
    expect(screen.getByText('System Audio')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Search transcript' }));
    await user.type(screen.getByPlaceholderText('Search transcript...'), 'Alpha');
    expect(screen.getByText('1 of 1')).toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
  });

  it('copies grouped transcript text with an indented, legible layout', async () => {
    const user = userEvent.setup();
    render(<TranscriptPanel transcript={[line('1', 'First', 'Microphone'), line('2', 'Second', 'Microphone')]} ui={{ transcriptionState: 'idle', isApplyingWindowedRetranscription: false }} />);
    await user.click(screen.getByRole('button', { name: 'Copy all transcript text' }));
    // One `[timestamp] Speaker` header per turn, with each spoken line
    // indented beneath it, instead of a run-on wall of unindented text.
    expect(copyText).toHaveBeenCalledWith('[00:03] Microphone\n    First\n    Second');
    expect(screen.getByText('Copied')).toBeInTheDocument();
  });

  it('separates speaker swaps with a blank line so turns are visually distinct', async () => {
    const user = userEvent.setup();
    render(<TranscriptPanel transcript={[line('1', 'First', 'Microphone'), line('2', 'Second', 'SystemAudio')]} ui={{ transcriptionState: 'idle', isApplyingWindowedRetranscription: false }} />);
    await user.click(screen.getByRole('button', { name: 'Copy all transcript text' }));
    expect(copyText).toHaveBeenCalledWith('[00:03] Microphone\n    First\n\n[00:03] System Audio\n    Second');
  });

  describe('render isolation', () => {
    beforeEach(() => __resetTranscriptRowRenderCountsForTests());

    it('does not re-render existing rows when an unrelated ui field changes on the same transcript reference', () => {
      const transcript = [line('1', 'First', 'Microphone'), line('2', 'Second', 'Microphone')];
      const baseUi = { transcriptionState: 'idle', isApplyingWindowedRetranscription: false, isRecording: false };
      const { rerender } = render(<TranscriptPanel transcript={transcript} ui={baseUi} />);
      expect(__getTranscriptRowRenderCountForTests('1')).toBe(1);
      expect(__getTranscriptRowRenderCountForTests('2')).toBe(1);

      rerender(<TranscriptPanel transcript={transcript} ui={{ ...baseUi, isRecording: true }} />);

      expect(__getTranscriptRowRenderCountForTests('1')).toBe(1);
      expect(__getTranscriptRowRenderCountForTests('2')).toBe(1);
    });

    it('re-renders only the row backing a changed transcript line', () => {
      const line1 = line('1', 'First', 'Microphone');
      const line2 = line('2', 'Second', 'Microphone');
      const baseUi = { transcriptionState: 'idle', isApplyingWindowedRetranscription: false };
      const { rerender } = render(<TranscriptPanel transcript={[line1, line2]} ui={baseUi} />);
      expect(__getTranscriptRowRenderCountForTests('1')).toBe(1);
      expect(__getTranscriptRowRenderCountForTests('2')).toBe(1);

      const updatedLine2 = { ...line2, text: 'Second, revised' };
      rerender(<TranscriptPanel transcript={[line1, updatedLine2]} ui={baseUi} />);

      expect(__getTranscriptRowRenderCountForTests('1')).toBe(1);
      expect(__getTranscriptRowRenderCountForTests('2')).toBe(2);
      expect(screen.getByText('Second, revised')).toBeInTheDocument();
    });
  });
});
