import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { initialAssistantSessionState } from '../state/assistantSessionReducer';
import { AssistantSessionApp } from './AssistantSessionApp';

const {
  revision: _revision,
  hasSnapshot: _hasSnapshot,
  theme: _theme,
  ...basePayload
} = initialAssistantSessionState;

function sendSnapshot(revision: number, overrides: Record<string, unknown>) {
  act(() => {
    window.basilAssistantSession?.onEvent({
      type: 'snapshot',
      protocolVersion: 1,
      revision,
      ...basePayload,
      assistantOutput: 'Rehydrated output',
      editableContentSeed: 'Rehydrated output',
      shouldPersistUI: true,
      ...overrides,
    });
  });
}

describe('AssistantSessionApp switching a refinement recording to typed input', () => {
  const postMessage = vi.fn();

  beforeEach(() => {
    postMessage.mockReset();
    window.webkit = {
      messageHandlers: {
        assistantSessionBridge: { postMessage },
      },
    };
  });

  it('opens the typed refinement editor from the header during a rehydrated refinement recording', () => {
    render(<AssistantSessionApp />);
    sendSnapshot(1, {
      assistantSessionStatus: 'idle',
      transcriptionStatus: 'running',
      isRefinementMode: true,
      isRecording: true,
      showRefinementIndicator: true,
      inputCommitted: false,
    });

    expect(screen.queryByTitle('Switch to text entry')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Switch to typed refinement'));

    expect(postMessage).toHaveBeenCalledWith({ type: 'enterTypedRefinement' });
    expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'switchInputMode' }));

    sendSnapshot(2, {
      assistantSessionStatus: 'idle',
      transcriptionStatus: 'idle',
      isRefinementMode: true,
      isRecording: false,
      showRefinementIndicator: true,
      inputCommitted: false,
    });

    expect(screen.getByText('Refinement instruction:')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /stop recording/i })).not.toBeInTheDocument();
    expect(screen.queryByTitle('Switch to typed refinement')).not.toBeInTheDocument();
  });

  it('offers the switch during a normal session refinement recording too', () => {
    render(<AssistantSessionApp />);
    sendSnapshot(1, {
      assistantSessionStatus: 'idle',
      transcriptionStatus: 'running',
      isRefinementMode: true,
      isRecording: true,
      inputCommitted: true,
    });

    expect(screen.getByTitle('Switch to typed refinement')).toBeInTheDocument();
  });

  it('hides the initial-capture modality toggle on a result that is not recording', () => {
    render(<AssistantSessionApp />);
    sendSnapshot(1, {
      assistantSessionStatus: 'completed',
      transcriptionStatus: 'completed',
      inputCommitted: false,
    });

    expect(screen.queryByTitle('Switch to text entry')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Switch to typed refinement')).not.toBeInTheDocument();
  });

  it('hides the switch once the refinement upload is processing', () => {
    render(<AssistantSessionApp />);
    sendSnapshot(1, {
      assistantSessionStatus: 'running',
      transcriptionStatus: 'running',
      isRefinementMode: true,
      isRecording: false,
      inputCommitted: true,
    });

    expect(screen.queryByTitle('Switch to typed refinement')).not.toBeInTheDocument();
  });

  it('opens the typed refinement editor when native raises the request serial (history typed Refine)', () => {
    render(<AssistantSessionApp />);
    sendSnapshot(1, {
      assistantSessionStatus: 'idle',
      transcriptionStatus: 'idle',
      isRefinementMode: true,
      showRefinementIndicator: true,
      typedRefinementRequestSerial: 1,
    });

    expect(screen.getByText('Refinement instruction:')).toBeInTheDocument();
    expect(postMessage).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'startRefinementRecording' }));
  });

  it('does not reopen the editor for an already-handled serial', () => {
    render(<AssistantSessionApp />);
    sendSnapshot(1, {
      assistantSessionStatus: 'idle',
      transcriptionStatus: 'idle',
      isRefinementMode: true,
      typedRefinementRequestSerial: 1,
    });
    fireEvent.click(screen.getByTitle('Cancel typed refinement'));
    expect(screen.queryByText('Refinement instruction:')).not.toBeInTheDocument();

    sendSnapshot(2, {
      assistantSessionStatus: 'idle',
      transcriptionStatus: 'idle',
      isRefinementMode: true,
      typedRefinementRequestSerial: 1,
    });
    expect(screen.queryByText('Refinement instruction:')).not.toBeInTheDocument();
  });
});
